import asyncio
import json
import sqlite3
from datetime import datetime, timezone

from app.run_collect import collect_all

c = sqlite3.connect("data/app.db")
now = datetime.now(timezone.utc).isoformat()
c.execute(
    "INSERT INTO sources(key,name,type,url,category,mode,weight,enabled) "
    "VALUES('test_sub_arxiv_ro','测试订阅更新','rss','https://rss.arxiv.org/rss/cs.RO','academic','subscription',1.0,1) "
    "ON CONFLICT(key) DO NOTHING"
)
c.commit()
c.close()

stats = asyncio.run(collect_all(full=False))
print("collect:", json.dumps(stats, ensure_ascii=False))

q = """
    SELECT a.id, a.title, s.name source_name, a.published_at
    FROM articles a JOIN sources s ON s.id=a.source_id
    WHERE s.mode='subscription' AND s.enabled=1 AND a.dup_of IS NULL
    ORDER BY a.published_at DESC LIMIT 5
"""
c = sqlite3.connect("data/app.db")
c.row_factory = sqlite3.Row
rows = [dict(r) for r in c.execute(q)]
c.close()
print("subscription rows:", len(rows))
for r in rows:
    print(" -", r["title"][:40], "|", r["source_name"], "|", (r["published_at"] or "")[:10])
