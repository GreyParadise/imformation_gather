import asyncio
import random

from app import db
from app.pipeline.extract import fetch_cover
from app.pipeline.httpclient import make_async_client

CONCURRENCY = 6
PER_SOURCE_CAP = 60


async def main():
    db.init_db()
    with db.get_db() as conn:
        from collections import defaultdict
        rows = conn.execute(
            "SELECT a.id, a.url, a.source_id FROM articles a "
            "JOIN sources s ON s.id = a.source_id "
            "WHERE a.cover IS NULL AND a.dup_of IS NULL AND s.mode='news' AND s.enabled=1 "
            "ORDER BY a.id DESC"
        ).fetchall()
        existing = [dict(r) for r in rows]
    by_src: dict[int, list] = defaultdict(list)
    for r in existing:
        by_src[r["source_id"]].append(r)
    targets = [r for lst in by_src.values() for r in lst[:PER_SOURCE_CAP]]
    print(f"backfill targets: {len(targets)}")

    sem = asyncio.Semaphore(CONCURRENCY)
    done = {"ok": 0, "fail": 0}

    async def worker(client, item):
        async with sem:
            cover = await fetch_cover(client, item["url"])
            if cover:
                with db.get_db() as conn:
                    conn.execute("UPDATE articles SET cover=? WHERE id=?", (cover, item["id"]))
                done["ok"] += 1
            else:
                done["fail"] += 1
            await asyncio.sleep(0.1 + random.random() * 0.2)

    async with make_async_client() as client:
        await asyncio.gather(*(worker(client, t) for t in targets))
    print(f"done: ok={done['ok']} fail={done['fail']}")

    with db.get_db() as conn:
        r = conn.execute("SELECT COUNT(1) t, SUM(cover IS NOT NULL) c FROM articles WHERE dup_of IS NULL").fetchone()
    print(f"overall cover coverage now: {r['c']}/{r['t']} = {100*r['c']//r['t']}%")


if __name__ == "__main__":
    asyncio.run(main())
