import json
import sqlite3

c = sqlite3.connect("data/app.db")
c.row_factory = sqlite3.Row
rows = c.execute(
    "SELECT n.id, n.article_id, n.summary, n.tags, n.is_relevant, n.cluster_size, a.title "
    "FROM news_items n JOIN articles a ON a.id=n.article_id ORDER BY n.id"
).fetchall()
print("news_items:", len(rows))
for r in rows[:15]:
    print("-", r["title"][:30], "=>", (r["summary"] or "")[:60], "| tags:", r["tags"], "| rel:", r["is_relevant"])
print("status dist:", dict(c.execute("SELECT status, COUNT(1) FROM articles GROUP BY status").fetchall()))
