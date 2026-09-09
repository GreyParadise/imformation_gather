import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

from . import db
from .pipeline.cluster import find_cluster, find_cluster_by_simhash, pack_vec, unpack_vec
from .pipeline.llm import EmbeddingUnavailable, RateLimited, embed_texts, summarize
from .pipeline.rules import hard_filter
from .settings import EMBED_MODEL

WINDOW_HOURS = 72
BATCH_LIMIT = 300
LLM_CONCURRENCY = 2
LLM_MIN_INTERVAL = float(__import__("os").getenv("LLM_MIN_INTERVAL", "7.5"))
MASK64 = (1 << 64) - 1


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_candidates(conn, limit: int):
    return conn.execute(
        """
        SELECT a.id, a.title, a.body, a.url, a.simhash, a.source_id, s.weight, s.mode, s.category
        FROM articles a JOIN sources s ON s.id = a.source_id
        WHERE a.dup_of IS NULL AND a.status IN ('raw','candidate') AND s.mode='news' AND s.enabled=1
        ORDER BY a.id ASC LIMIT ?
        """,
        (limit,),
    ).fetchall()


async def run_pipeline(limit: int = BATCH_LIMIT) -> dict:
    t0 = time.time()
    stats = {"candidates": 0, "dropped_rules": 0, "clustering": "embedding", "joined_cluster": 0,
             "new_clusters": 0, "tokens": 0, "models": {}}
    db.init_db()
    with db.get_db() as conn:
        cands = fetch_candidates(conn, limit)
    if not cands:
        return stats
    stats["candidates"] = len(cands)

    passed = []
    for c in cands:
        ok, reason = hard_filter(c["title"], c["body"])
        with db.get_db() as conn:
            if not ok:
                conn.execute("UPDATE articles SET status='dropped', drop_reason=? WHERE id=?", (reason, c["id"]))
                stats["dropped_rules"] += 1
            else:
                conn.execute("UPDATE articles SET status='candidate' WHERE id=?", (c["id"],))
                passed.append(dict(c))
    if not passed:
        return stats

    vec_map: dict[int, list[float]] = {}
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)).isoformat()

    try:
        with db.get_db() as conn:
            for r in conn.execute(
                "SELECT article_id, vector FROM embeddings WHERE article_id IN (%s)" % ",".join("?" * len(passed)),
                [p["id"] for p in passed],
            ).fetchall():
                vec_map[r["article_id"]] = unpack_vec(r["vector"])
        missing = [p for p in passed if p["id"] not in vec_map]
        if missing:
            texts = [f"{p['title']}. {(p['body'] or '')[:200]}" for p in missing]
            vecs = await embed_texts(texts)
            with db.get_db() as conn:
                for p, v in zip(missing, vecs):
                    conn.execute(
                        "INSERT INTO embeddings(article_id, model, vector, created_at) VALUES(?,?,?,?)",
                        (p["id"], EMBED_MODEL or "unknown", pack_vec(v), now_iso()),
                    )
                    vec_map[p["id"]] = v
        with db.get_db() as conn:
            rep_rows = conn.execute(
                """
                SELECT n.cluster_id, n.article_id AS rep_id, e.vector AS vec, a.simhash AS sh,
                       n.cluster_size, n.heat
                FROM news_items n
                JOIN articles a ON a.id = n.article_id
                JOIN embeddings e ON e.article_id = n.article_id
                WHERE n.created_at > ?
                """,
                (cutoff,),
            ).fetchall()
        reps = []
        seen = set()
        for r in rep_rows:
            if r["cluster_id"] not in seen and r["vec"] is not None:
                seen.add(r["cluster_id"])
                reps.append((r["cluster_id"], unpack_vec(r["vec"])))
    except EmbeddingUnavailable as e:
        stats["clustering"] = "simhash"
        print(f"  [cluster-degrade] {e}", flush=True)
        reps = []
        with db.get_db() as conn:
            rep_rows = conn.execute(
                "SELECT n.cluster_id, a.simhash FROM news_items n JOIN articles a ON a.id=n.article_id WHERE n.created_at > ?",
                (cutoff,),
            ).fetchall()
        seen = set()
        for r in rep_rows:
            if r["cluster_id"] not in seen and r["simhash"] is not None:
                seen.add(r["cluster_id"])
                reps.append((r["cluster_id"], r["simhash"] & MASK64))

    new_clusters: dict[str, dict] = {}
    joins: list[tuple[str, dict]] = []
    for p in passed:
        if stats["clustering"] == "embedding":
            vec = vec_map.get(p["id"])
            if vec is None:
                continue
            cid = find_cluster(vec, reps)
            if cid is None:
                cid = uuid.uuid4().hex
                reps.append((cid, vec))
                new_clusters[cid] = p
            else:
                joins.append((cid, p))
        else:
            sh = (p["simhash"] or 0) & MASK64
            cid = find_cluster_by_simhash(sh, reps)
            if cid is None:
                cid = uuid.uuid4().hex
                reps.append((cid, sh))
                new_clusters[cid] = p
            else:
                joins.append((cid, p))

    for cid, p in joins:
        with db.get_db() as conn:
            conn.execute("UPDATE articles SET status='clustered' WHERE id=?", (p["id"],))
            conn.execute(
                "UPDATE news_items SET cluster_size = cluster_size + 1, heat = heat + ? WHERE cluster_id=?",
                (p["weight"], cid),
            )
        stats["joined_cluster"] += 1

    sem = asyncio.Semaphore(LLM_CONCURRENCY)
    pace_lock = asyncio.Lock()
    last_call = [0.0]
    rate_stop = asyncio.Event()
    rate_hit = [False]

    async def make_item(cid: str, p: dict):
        async with sem:
            if rate_stop.is_set():
                return
            async with pace_lock:
                wait = LLM_MIN_INTERVAL - (time.monotonic() - last_call[0])
                if wait > 0:
                    await asyncio.sleep(wait)
                last_call[0] = time.monotonic()
            try:
                data, tokens, used_model = await summarize(p["title"], p["body"])
                stats["models"][used_model] = stats["models"].get(used_model, 0) + 1
            except RateLimited as e:
                if not rate_hit[0]:
                    rate_hit[0] = True
                    print(f"  [429] 网关限流({e.retry_after:.0f}s 后可恢复)，本轮提前结束，剩余留待下轮", flush=True)
                rate_stop.set()
                return
            except Exception as e:
                print(f"  [LLM-ERR] {p['id']}: {e}", flush=True)
                return
        summary = data.get("summary") or (p["body"] or "")[:120]
        tags = json.dumps(data.get("tags") or [], ensure_ascii=False)
        relevant = 1 if data.get("is_relevant", True) else 0
        with db.get_db() as conn:
            conn.execute("UPDATE articles SET status='listed' WHERE id=?", (p["id"],))
            conn.execute(
                "INSERT INTO news_items(article_id, summary, tags, cluster_id, cluster_size, heat, is_relevant, created_at) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(article_id) DO UPDATE SET summary=excluded.summary, "
                "tags=excluded.tags, cluster_id=excluded.cluster_id, is_relevant=excluded.is_relevant",
                (p["id"], summary, tags, cid, 1, p["weight"], relevant, now_iso()),
            )
        stats["tokens"] += tokens
        stats["new_clusters"] += 1

    await asyncio.gather(*(make_item(cid, p) for cid, p in new_clusters.items()))
    stats["rate_limited"] = rate_hit[0]
    stats["elapsed"] = round(time.time() - t0, 1)
    return stats


async def main():
    stats = await run_pipeline()
    print(f"[pipeline] {json.dumps(stats, ensure_ascii=False)}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
