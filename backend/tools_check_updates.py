import httpx
from dotenv import dotenv_values

k = dotenv_values(".env")["APP_KEY"]
H = {"X-App-Key": k}
B = "http://127.0.0.1:8000"

r = httpx.get(B + "/api/updates", params={"size": 3}, headers=H, timeout=15)
d = r.json()
print("updates:", r.status_code, "| records:", len(d["records"]), "| cursor:", bool(d["next_cursor"]))
if d["records"]:
    print("sample:", {k2: str(v)[:40] for k2, v in d["records"][0].items()})

srcs = httpx.get(B + "/api/sources", headers=H, timeout=15).json()["sources"]
test = [s for s in srcs if s["key"] == "test_sub_arxiv_ro"]
if test:
    dr = httpx.delete(f"{B}/api/sources/{test[0]['id']}", headers=H, timeout=15)
    print("cleanup test source:", dr.status_code)
