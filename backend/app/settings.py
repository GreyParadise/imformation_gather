import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "data"
CONFIG_DIR = BACKEND_DIR / "config"
DB_PATH = DATA_DIR / "app.db"
SOURCES_YML = CONFIG_DIR / "sources.yml"

load_dotenv(BACKEND_DIR / ".env")


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default


LLM_API_KEY = _env("LLM_API_KEY", "DASHSCOPE_API_KEY")
LLM_BASE_URL = _env("LLM_BASE_URL", "QWEN_BASE_URL", default="https://chat.iphy.ac.cn/api/v1")
LLM_MODEL = _env("LLM_MODEL", "QWEN_MODEL", default="glm-5.3-flash")
LLM_MODEL_CHAIN = _env("LLM_MODEL_CHAIN", "QWEN_MODEL_CHAIN")
EMBED_MODEL = _env("EMBED_MODEL", "QWEN_EMBEDDING_MODEL")
EMBED_MODEL_CHAIN = _env("EMBED_MODEL_CHAIN", "QWEN_EMBED_MODEL_CHAIN")
LLM_TIMEOUT = float(_env("LLM_TIMEOUT", default="60"))
APP_KEY = os.getenv("APP_KEY", "")
PROXY_URL = os.getenv("PROXY_URL") or None

HTTP_TIMEOUT = 20
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 InfoGatherBot/0.1"
)
