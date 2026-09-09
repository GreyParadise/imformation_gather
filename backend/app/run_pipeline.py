import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

from . import db
from .pipeline.cluster import find_cluster, pack_vec, unpack_vec
from .pipeline.llm import embed_texts, summarize
from .pipeline.rules import hard_filter

WINDOW_HOURS = 72
BATCH_LIMIT = 300
LLM_CONCURRENCY = 4


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_candidates(conn, limit: int):
    return conn.execute(
        """
        SELECT a.id, a.title, a.body, a.url, a.source_id, s.weight, s.mode, s.category
        FROM articles a JOIN sources s ON s.id = a.source_id
        WHERE a.dup_of IS NULL AND a.status IN ('raw','candidate') AND s.mode='news' AND s.enabled=1
        ORDER BY a.id ASC LIMIT ?
        """,
        (limit,),
    ).fetchall()


async def run_pipeline(limit: int = BATCH_LIMIT) -> dict:
    t0 = time.time()
    stats = {"candidates": 0, "dropped_rules": 0, "embedded": 0, "joined_cluster": 0, "new_clusters": 0, "tokens": 0}
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
                conn.execute("UPDATE articles SET status='candidate' WHERE id=?", (c["id"],), )
                passed.append(dict(c))
    if not passed:
        return stats

    with db.get_db() as conn:
        have = {r["article_id"]: unpack_vec(r["vector"]) for r in conn.execute(
            "SELECT article_id, vector FROM embeddings WHERE article_id IN (%s)" % ",".join("?" * len(passed)),
            [p["id"] for p in passed],
        ).fetchall()}
    missing = [p for p in passed if p["id"] not in have]
    if missing:
        texts = [f"{p['title']}. {(p['body'] or '')[:200]}" for p in missing]
        vecs = await embed_texts(texts)
        with db.get_db() as conn:
            for p, v in zip(missing, vecs):
                conn.execute(
                    "INSERT INTO embeddings(article_id, model, vector, created_at) VALUES(?,?,?,?)",
                    (p["id"], "text-embedding-v3", pack_vec(v), now_iso()),
                )
                have[p["id"]] = v
        stats["embedded"] = len(missing)

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)).isoformat()
    reps = []
    cluster_members = {}
    with db.get_db() as conn:
        rows = conn.execute(
            """
            SELECT n.cluster_id, n.article_id AS rep_id, e.vector, n.cluster_size, n.heat
            FROM news_items n JOIN embeddings e ON e.article_id = n.article_id
            WHERE n.created_at > ?
            """,
            (cutoff,),
        ).fetchall()
    for r in rows:
        if r["cluster_id"] not in cluster_members:
            reps.append((r["cluster_id"], unpack_vec(r["vector"])))
            cluster_members[r["cluster_id"]] = {"size": r["cluster_size"], "heat": r["heat"], "article_id": r["rep_id"]}

    new_clusters: dict[str, dict] = {}
    joins: list[tuple[str, dict]] = []
    for p in passed:
        vec = have.get(p["id"])
        if vec is None:
            continue
        cid = find_cluster(vec, reps)
        if cid:
            joins.append((cid, p))
        else:
            cid = uuid.uuid4().hex
            reps.append((cid, vec))
            new_clusters[cid] = p

    for cid, p in joins:
        with db.get_db() as conn:
            conn.execute("UPDATE articles SET status='clustered' WHERE id=?", (p["id"],))
            conn.execute(
                "UPDATE news_items SET cluster_size = cluster_size + 1, heat = heat + ? WHERE cluster_id=?",
                (p["weight"], cid),
            )
        stats["joined_cluster"] += 1

    sem = asyncio.Semaphore(LLM_CONCURRENCY)

    async def make_item(cid: str, p: dict):
        async with sem:
            try:
                data, tokens = await summarize(p["title"], p["body"])
            except Exception as e:
                print(f"  [LLM-ERR] {p['id']}: {e}", flush=True)
                data, tokens = {"summary": (p["body"] or "")[:120], "tags": [], "is_relevant": True}, 0
        summary = data.get("summary") or (p["body"] or "")[:120]
        tags = json.dumps(data.get("tags") or [], ensure_ascii=False)
        relevant = 1 if data.get("is_relevant", True) else 0
        with db.get_db() as conn:
            conn.execute(
                "UPDATE articles SET status='listed' WHERE id=?",
                (p["id"],),
            )
            conn.execute(
                "INSERT INTO news_items(article_id, summary, tags, cluster_id, cluster_size, heat, is_relevant, created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (p["id"], summary, tags, cid, 1, p["weight"], relevant, now_iso()),
            )
        stats["tokens"] += tokens
        stats["new_clusters"] += 1

    await asyncio.gather(*(make_item(cid, p) for cid, p in new_clusters.items()))
    stats["elapsed"] = round(time.time() - t0, 1)
    return stats


async def main():
    try:
        stats = await run_pipeline()
        print(f"[pipeline] {json.dumps(stats, ensure_ascii=False)}", flush=True)
    except RuntimeError as e:
        print(f"[pipeline] 跳过: {e}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
