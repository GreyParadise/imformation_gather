import httpx
from dotenv import dotenv_values

cfg = dotenv_values(".env")
key = cfg.get("DASHSCOPE_API_KEY", "")
base = cfg.get("QWEN_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
print(f"key loaded: {bool(key)} (len={len(key)}), base={base}")
if key:
    r = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    print("HTTP", r.status_code)
    if r.status_code == 200:
        ids = sorted(m["id"] for m in r.json().get("data", []))
        interesting = [i for i in ids if any(p in i for p in ("qwen", "embedding", "deepseek", "kimi", "glm", "MiniMax"))]
        print(f"total {len(ids)} models, showing {len(interesting)}:")
        for i in interesting:
            print(" ", i)
    else:
        print(r.text[:300])
