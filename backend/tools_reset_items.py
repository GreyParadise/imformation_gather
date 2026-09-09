import sqlite3

c = sqlite3.connect("data/app.db")
c.execute("DELETE FROM news_items")
c.execute("UPDATE articles SET status='candidate' WHERE status='listed'")
c.commit()
print("reset:", dict(c.execute("SELECT status, COUNT(1) FROM articles GROUP BY status").fetchall()))
