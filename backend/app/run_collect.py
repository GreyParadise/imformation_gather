import asyncio
import json
import sys
import time
from datetime import datetime, timedelta, timezone

import yaml

from . import db
from .pipeline.dedupe import hamming, normalize_url, simhash64, url_hash
from .pipeline.extract import cover_batch, enrich_batch, html_to_text
from .pipeline.fetch import fetch_feed
from .pipeline.httpclient import make_async_client
from .settings import SOURCES_YML

MASK64 = (1 << 64) - 1
SIMHASH_DISTANCE = 3
MIN_BODY_LEN = 200
RECENT_DAYS = 7


def to_db_int(v: int) -> int:
    v &= MASK64
    return v - (1 << 64) if v >= (1 << 63) else v


def from_db_int(v: int) -> int:
    return v & MASK64 if v is not None else 0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_and_sync_sources(conn) -> list[dict]:
    cfg = yaml.safe_load(SOURCES_YML.read_text(encoding="utf-8"))
    for cat in cfg.get("categories", []):
        conn.execute(
            "INSERT INTO categories(key,name) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET name=excluded.name",
            (cat["key"], cat["name"]),
        )
    sources = []
    for s in cfg.get("sources", []):
        conn.execute(
            """
            INSERT INTO sources(key,name,type,url,category,mode,weight,enabled)
            VALUES(:key,:name,:type,:url,:category,:mode,:weight,:enabled)
            ON CONFLICT(key) DO UPDATE SET
                name=excluded.name, type=excluded.type, url=excluded.url,
                category=excluded.category, mode=excluded.mode, weight=excluded.weight,
                enabled=excluded.enabled
            """,
            {
                "key": s["key"], "name": s["name"], "type": s.get("type", "rss"),
                "url": s["url"], "category": s["category"], "mode": s.get("mode", "news"),
                "weight": s.get("weight", 1.0), "enabled": 1 if s.get("enabled", True) else 0,
            },
        )
        sources.append(s)
    return sources


async def collect_all(full: bool = False, per_source_cap: int = 30) -> dict:
    stats = {"new_articles": 0, "dropped_dup": 0, "enriched": 0, "covers": 0, "sources_ok": 0, "sources_fail": 0, "not_modified": 0}
    db.init_db()
    with db.get_db() as conn:
        load_and_sync_sources(conn)
        enabled = [dict(r) for r in conn.execute("SELECT key FROM sources WHERE enabled=1").fetchall()]
        existing_hashes = {row["url_hash"] for row in conn.execute("SELECT url_hash FROM articles")}
        recent = conn.execute(
            "SELECT id, simhash FROM articles WHERE dup_of IS NULL AND fetched_at > ? ORDER BY id DESC LIMIT 5000",
            ((datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).isoformat(),),
        ).fetchall()
        recent_hashes = [(r["id"], from_db_int(r["simhash"])) for r in recent if r["simhash"] is not None]

    new_inserts: list[dict] = []

    async with make_async_client() as client:
        sem = asyncio.Semaphore(6)

        async def run_source(src_key: str):
            with db.get_db() as conn:
                row = conn.execute("SELECT * FROM sources WHERE key=?", (src_key,)).fetchone()
            async with sem:
                result = await fetch_feed(client, row["url"], None if full else row["etag"], None if full else row["last_modified"])
            articles = []
            if result["ok"] and not result["not_modified"]:
                for entry in result["entries"][:per_source_cap]:
                    norm = normalize_url(entry["url"])
                    h = url_hash(entry["url"])
                    if not norm or h in existing_hashes:
                        continue
                    body_text = html_to_text(entry.get("payload_html", ""))
                    sh = simhash64(entry["title"] + " " + body_text[:120])
                    articles.append({
                        "url_hash": h,
                        "source_id": row["id"],
                        "url": norm,
                        "title": entry["title"],
                        "body": body_text or None,
                        "cover": entry.get("cover"),
                        "author": entry.get("author"),
                        "published_at": entry.get("published_at") or now_iso(),
                        "fetched_at": now_iso(),
                        "simhash": sh,
                        "source_mode": row["mode"],
                        "body_imgs": json.dumps(entry.get("payload_imgs") or [], ensure_ascii=False) if entry.get("payload_imgs") else None,
                    })
            with db.get_db() as conn:
                inserted_keys = []
                for a in articles:
                    try:
                        conn.execute(
                            "INSERT INTO articles(url,url_hash,source_id,title,body,cover,author,published_at,fetched_at,simhash,body_imgs) "
                            "VALUES(:url,:url_hash,:source_id,:title,:body,:cover,:author,:published_at,:fetched_at,:simhash,:body_imgs)",
                            {**a, "simhash": to_db_int(a["simhash"])},
                        )
                        inserted_keys.append(a)
                        existing_hashes.add(a["url_hash"])
                    except Exception:
                        continue
                if result["ok"]:
                    conn.execute(
                        "UPDATE sources SET last_fetch_at=?, fail_count=0, health='ok', "
                        "etag=COALESCE(?, etag), last_modified=COALESCE(?, last_modified) WHERE key=?",
                        (now_iso(), result.get("etag"), result.get("last_modified"), src_key),
                    )
                    if result["not_modified"]:
                        stats["not_modified"] += 1
                    else:
                        stats["sources_ok"] += 1
                else:
                    conn.execute(
                        "UPDATE sources SET last_fetch_at=?, fail_count=fail_count+1, "
                        "health=CASE WHEN fail_count+1>=5 THEN 'failing' ELSE 'degraded' END WHERE key=?",
                        (now_iso(), src_key),
                    )
                    stats["sources_fail"] += 1
                    print(f"  [FAIL] {src_key}: {result['error']}", flush=True)
            new_inserts.extend(inserted_keys)

        await asyncio.gather(*(run_source(s["key"]) for s in enabled))

    need_enrich = [a for a in new_inserts if a.get("source_mode") == "news" and (not a["body"] or len(a["body"]) < MIN_BODY_LEN)]
    if need_enrich:
        async with make_async_client() as client:
            await enrich_batch(client, need_enrich)
        with db.get_db() as conn:
            for a in need_enrich:
                if a.get("body") and len(a["body"]) >= MIN_BODY_LEN:
                    conn.execute(
                        "UPDATE articles SET body=?, cover=COALESCE(?, cover), simhash=? WHERE url_hash=?",
                        (a["body"], a.get("cover"), to_db_int(simhash64(a["title"] + " " + a["body"][:120])), a["url_hash"]),
                    )
                    a["simhash"] = simhash64(a["title"] + " " + a["body"][:120])
                    stats["enriched"] += 1

    from collections import defaultdict
    by_src: dict[int, list] = defaultdict(list)
    for a in new_inserts:
        if a.get("source_mode") == "news" and not a.get("cover"):
            by_src[a["source_id"]].append(a)
    need_cover = [a for lst in by_src.values() for a in lst[:20]]
    if need_cover:
        async with make_async_client() as client:
            await cover_batch(client, need_cover)
        with db.get_db() as conn:
            for a in need_cover:
                if a.get("cover"):
                    conn.execute("UPDATE articles SET cover=? WHERE url_hash=?", (a["cover"], a["url_hash"]))
                    stats["covers"] += 1

    with db.get_db() as conn:
        pool = list(recent_hashes)
        for a in new_inserts:
            sh = a["simhash"]
            match_id = None
            for rid, rsh in pool:
                if hamming(sh, rsh) <= SIMHASH_DISTANCE:
                    match_id = rid
                    break
            if match_id is not None:
                conn.execute(
                    "UPDATE articles SET dup_of=?, status='dropped', drop_reason='simhash_dup' "
                    "WHERE url_hash=? AND dup_of IS NULL",
                    (match_id, a["url_hash"]),
                )
                stats["dropped_dup"] += 1
            else:
                pool.append((conn.execute("SELECT id FROM articles WHERE url_hash=?", (a["url_hash"],)).fetchone()["id"], sh))
        stats["new_articles"] = len(new_inserts)
        stats["db_total"] = conn.execute("SELECT COUNT(*) c FROM articles").fetchone()["c"]
        stats["db_candidates"] = conn.execute("SELECT COUNT(*) c FROM articles WHERE dup_of IS NULL").fetchone()["c"]
    return stats


def main():
    full = "--full" in sys.argv
    t0 = time.time()
    stats = asyncio.run(collect_all(full=full))
    print(f"[collect] {json.dumps(stats, ensure_ascii=False)} in {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
