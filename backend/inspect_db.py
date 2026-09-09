import sqlite3

c = sqlite3.connect("data/app.db")
c.row_factory = sqlite3.Row

def q(sql):
    return [dict(r) for r in c.execute(sql)]

print("per-source:")
for r in q("select s.name, count(1) c from articles a join sources s on s.id=a.source_id group by s.name order by c desc"):
    print(" ", r["name"], r["c"])
print("body stats:", q("select sum(body is null) no_body, sum(length(body)<200) short_body, sum(cover is not null) with_cover, max(length(body)) max_len from articles"))
print("recent 10:")
for r in q("select a.title, s.name src, a.published_at, length(a.body) blen from articles a join sources s on s.id=a.source_id order by a.published_at desc limit 10"):
    print(" -", (r["published_at"] or "")[:10], f"[{r['src']}]", r["title"][:52], "body:", r["blen"])
