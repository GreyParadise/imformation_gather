import httpx
from dotenv import dotenv_values

cfg = dotenv_values(".env")
key = cfg["APP_KEY"]
B = "http://127.0.0.1:8000"

r = httpx.get(B + "/api/health", timeout=10)
print("health:", r.status_code)

r = httpx.get(B + "/api/news", params={"size": 3}, headers={"X-App-Key": "wrong-key"}, timeout=10)
print("wrong key ->", r.status_code, r.json())

r = httpx.get(B + "/api/news", params={"size": 3}, headers={"X-App-Key": key}, timeout=10)
d = r.json()
print("correct key ->", r.status_code, "| records:", len(d["records"]), "| cursor:", (d["next_cursor"] or "")[:20] + "...")
rec = d["records"][0]
print("sample:", {k: (str(v)[:50] if v else v) for k, v in rec.items()})

if d["next_cursor"]:
    r2 = httpx.get(B + "/api/news", params={"size": 3, "before": d["next_cursor"]}, headers={"X-App-Key": key}, timeout=10)
    d2 = r2.json()
    ids1 = {x["id"] for x in d["records"]}
    ids2 = {x["id"] for x in d2["records"]}
    print("page2 ->", r2.status_code, "| overlap with page1:", ids1 & ids2)

r = httpx.get(B + "/api/categories", headers={"X-App-Key": key}, timeout=10)
print("categories:", r.json())

r = httpx.get(B + "/api/news", params={"size": 5, "category": "academic"}, headers={"X-App-Key": key}, timeout=10)
print("academic filter ->", r.status_code, "| got:", len(r.json()["records"]))
