import asyncio
import json

from openai import AsyncOpenAI

from ..settings import DASHSCOPE_API_KEY, QWEN_BASE_URL, QWEN_EMBEDDING_MODEL, QWEN_MODEL, PROXY_URL

_client: AsyncOpenAI | None = None

SYSTEM_SUMMARY = (
    "你是中文资讯摘要助手。根据给定的新闻标题与正文，输出一个 JSON 对象，字段：\n"
    'summary: 不超过120字的中文摘要，直接陈述事实，不要"本文"、"文章"等词\n'
    "tags: 1-3 个中文标签词\n"
    "is_relevant: 布尔值，表示是否属于科技/AI/学术研究类有效资讯（促销、招聘、水文、标题党为 false）\n"
    "只输出 JSON，不要输出其他内容。"
)


def client() -> AsyncOpenAI:
    global _client
    if not DASHSCOPE_API_KEY:
        raise RuntimeError("DASHSCOPE_API_KEY 未配置，请在 backend/.env 中填写")
    if _client is None:
        kwargs = {"api_key": DASHSCOPE_API_KEY, "base_url": QWEN_BASE_URL}
        if PROXY_URL:
            import httpx
            kwargs["http_client"] = httpx.AsyncClient(proxy=PROXY_URL)
        _client = AsyncOpenAI(**kwargs)
    return _client


async def summarize(title: str, body: str):
    resp = await client().chat.completions.create(
        model=QWEN_MODEL,
        temperature=0.3,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_SUMMARY},
            {"role": "user", "content": f"标题：{title}\n正文：{(body or '')[:800]}"},
        ],
    )
    try:
        data = json.loads(resp.choices[0].message.content)
    except (json.JSONDecodeError, TypeError):
        data = {"summary": None, "tags": [], "is_relevant": True}
    tokens = (resp.usage.total_tokens if resp.usage else 0) or 0
    return data, tokens


async def embed_texts(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), 10):
        batch = texts[i:i + 10]
        resp = await client().embeddings.create(model=QWEN_EMBEDDING_MODEL, input=batch)
        out.extend(d.embedding for d in resp.data)
        await asyncio.sleep(0.2)
    return out
