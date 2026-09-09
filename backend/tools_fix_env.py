import sys

from dotenv import dotenv_values

vals = dotenv_values(".env")
key = vals.get("LLM_API_KEY") or vals.get("DASHSCOPE_API_KEY") or ""
if not key:
    print("WARN: 当前 .env 中没有 API key，保持不覆盖")
    sys.exit(1)
lines = [
    f"LLM_API_KEY={key}",
    vals.get("LLM_BASE_URL") or "LLM_BASE_URL=https://chat.iphy.ac.cn/api/v1",
    "LLM_MODEL=glm-5.3-flash",
    "LLM_MODEL_CHAIN=glm-5.3-flash,glm-5.3,deepseek-v4-flash-vision-exp,deepseek-v4-pro",
    "LLM_TIMEOUT=60",
    "EMBED_MODEL=",
    f"PROXY_URL={vals.get('PROXY_URL', 'http://127.0.0.1:7890')}",
    f"APP_KEY={vals.get('APP_KEY', '')}",
]
open(".env", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("rewritten keys OK")
