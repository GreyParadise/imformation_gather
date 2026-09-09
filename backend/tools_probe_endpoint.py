import time

import httpx
from dotenv import dotenv_values

cfg = dotenv_values(".env")
base = cfg["QWEN_BASE_URL"].rstrip("/")
key = cfg["DASHSCOPE_API_KEY"]
H = {"Authorization": "Bearer " + key}

print("--- embedding probes ---")
for name in ["text-embedding-v3", "bge-large-zh-v1.5", "Qwen3-Embedding", "embedding-3-small"]:
    try:
        r = httpx.post(base + "/embeddings", headers=H, json={"model": name, "input": ["测试"]}, timeout=30)
        info = ("dim=" + str(len(r.json()["data"][0]["embedding"]))) if r.status_code == 200 else r.text[:80]
        print(name, r.status_code, info)
    except Exception as e:
        print(name, "ERR", type(e).__name__)

print("--- chat speed + json_mode probe ---")
for mid in ["glm-5.3-flash", "glm-5.3", "deepseek-v4-pro", "deepseek-v4-flash-vision-exp"]:
    t0 = time.time()
    body = {
        "model": mid,
        "messages": [
            {"role": "system", "content": "你是一个只输出 JSON 的助手"},
            {"role": "user", "content": "给出 {\"ok\": true}"},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    try:
        r = httpx.post(base + "/chat/completions", headers=H, json=body, timeout=120)
        dt = time.time() - t0
        if r.status_code == 200:
            c = r.json()["choices"][0]["message"]["content"]
            print(mid, "json_mode OK", f"{dt:.1f}s", repr(c[:40]))
        else:
            print(mid, r.status_code, f"{dt:.1f}s", r.text[:120])
    except Exception as e:
        print(mid, "ERR", type(e).__name__, f"{time.time()-t0:.1f}s")
