import json
from collections import Counter

import httpx
from dotenv import dotenv_values

cfg = dotenv_values(".env")
K = cfg["APP_KEY"]
H = {"X-App-Key": K}
B = "http://127.0.0.1:8000"
ok = True

def check(name, cond, extra=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + (f" | {extra}" if extra else ""))
    ok = ok and cond

r = httpx.get(B + "/api/health", timeout=10)
check("health", r.status_code == 200)

d = httpx.get(B + "/api/news", params={"size": 30}, headers=H, timeout=15).json()
c1 = Counter(x["source_name"] for x in d["records"])
check("feed size/total", len(d["records"]) == 30 and d["total"] > 800, f"total={d['total']}")
check("scatter: per-source<=10", all(v <= 10 for v in c1.values()), str(dict(c1)))
cov = sum(1 for x in d["records"] if x.get("cover"))
check("page1 has covers", cov >= 8, f"{cov}/30 with cover")
tokrec = next((x for x in d["records"] if x.get("cover")), None)

d2 = httpx.get(B + "/api/news", params={"size": 30, "before": d["next_cursor"]}, headers=H, timeout=15).json()
ids1 = {x["id"] for x in d["records"]}
ids2 = {x["id"] for x in d2["records"]}
check("page2 no overlap", not (ids1 & ids2), f"{len(ids2)} rows")

dq = httpx.get(B + "/api/news", params={"q": "OpenAI"}, headers=H, timeout=15).json()
check("search q=OpenAI", len(dq["records"]) > 0 and all("openai" in (x["title"] + (x["summary"] or "")).lower() for x in dq["records"]), f"hits={dq['total']}")

dt = httpx.get(B + "/api/tags", headers=H, timeout=15).json()
check("tags facet", len(dt["tags"]) > 5, str([t["name"] for t in dt["tags"][:5]]))

if dt["tags"]:
    tg = dt["tags"][0]["name"]
    dtf = httpx.get(B + "/api/news", params={"tag": tg}, headers=H, timeout=15).json()
    check("filter by tag", dtf["total"] > 0, f"tag={tg} total={dtf['total']}")

ds = httpx.get(B + "/api/sources", headers=H, timeout=15).json()
ithome = next(s for s in ds["sources"] if s["key"] == "ithome")
dsf = httpx.get(B + "/api/news", params={"source": ithome["id"]}, headers=H, timeout=15).json()
check("filter by source", dsf["total"] > 0 and all(x["source_name"] == "IT之家" for x in dsf["records"]), f"total={dsf['total']}")

if tokrec:
    cid = tokrec["id"]
    ctok = tokrec["cover_token"]
    r = httpx.get(f"{B}/api/cover/{cid}", params={"t": ctok}, timeout=30, follow_redirects=True)
    check("cover proxy ok", r.status_code == 200 and r.headers["content-type"].startswith("image"), f"{r.headers.get('content-type')} {len(r.content)}B")
    r = httpx.get(f"{B}/api/cover/{cid}", timeout=15)
    check("cover no token -> 401", r.status_code == 401)
    r = httpx.get(f"{B}/api/cover/{cid}", params={"t": "9999999999.deadbeefdeadbeef"}, timeout=15)
    check("cover bad token -> 401", r.status_code == 401)

dr = httpx.get(f"{B}/api/read/{tokrec['id'] if tokrec else 1}", headers=H, timeout=40)
rd = dr.json()
check("read ithome article", rd.get("html") and len(rd["html"]) > 300, f"html={len(rd.get('html') or '')} err={rd.get('error')}")
if rd.get("html") and "/api/img/" in rd["html"]:
    import re as _re
    m = _re.search(r'src="(/api/img/\d+/\d+\?t=[^"]+)"', rd["html"])
    check("reader html has proxied imgs", bool(m))
    if m:
        r = httpx.get(B + m.group(1), timeout=30)
        check("reader img proxy", r.status_code == 200 and r.headers["content-type"].startswith("image"), f"{r.status_code} {r.headers.get('content-type','')[:30]}")

hn = httpx.get(B + "/api/news", params={"q": "Hacker News 测试不存在关键词zzz"}, headers=H, timeout=15).json()
check("search empty ok", hn["records"] == [])

print("\nALL PASS" if ok else "\nSOME FAILED")
