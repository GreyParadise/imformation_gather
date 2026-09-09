import asyncio
import json
import re

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from ..settings import (
    EMBED_MODEL,
    EMBED_MODEL_CHAIN,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_MODEL_CHAIN,
    LLM_TIMEOUT,
    PROXY_URL,
)

MODEL_CHAIN = [m.strip() for m in LLM_MODEL_CHAIN.split(",") if m.strip()] or [LLM_MODEL, "glm-5.3", "deepseek-v4-pro"]
EMB_CHAIN = [m.strip() for m in EMBED_MODEL_CHAIN.split(",") if m.strip()] or ([EMBED_MODEL] if EMBED_MODEL else [])

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}

_client: AsyncOpenAI | None = None
_active_chat_model: str | None = None
_active_embed_model: str | None = None
_embedding_disabled = False


class EmbeddingUnavailable(RuntimeError):
    pass


SYSTEM_SUMMARY = (
    "你是中文资讯摘要助手。根据给定的新闻标题与正文，输出一个 JSON 对象，字段：\n"
    'summary: 不超过120字的中文摘要，直接陈述事实，不要"本文"、"文章"等词\n'
    "tags: 1-3 个中文标签词\n"
    "is_relevant: 布尔值，表示是否属于科技/AI/学术研究类有效资讯（促销、招聘、水文、标题党为 false）\n"
    "只输出 JSON，不要输出其他内容。"
)


def client() -> AsyncOpenAI:
    global _client
    if not LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY 未配置，请在 backend/.env 中填写")
    if _client is None:
        kwargs = {
            "api_key": LLM_API_KEY,
            "base_url": LLM_BASE_URL,
            "timeout": httpx.Timeout(LLM_TIMEOUT, connect=10.0),
            "max_retries": 0,
        }
        if PROXY_URL:
            kwargs["http_client"] = httpx.AsyncClient(proxy=PROXY_URL)
        _client = AsyncOpenAI(**kwargs)
    return _client


def _retryable(e: Exception) -> bool:
    if isinstance(e, (APITimeoutError, APIConnectionError)):
        return True
    if isinstance(e, APIStatusError):
        return e.status_code in RETRYABLE_STATUS or e.status_code == 404
    return False


def _order(chain: list[str], active: str | None) -> list[str]:
    if active and active in chain:
        return [active] + [m for m in chain if m != active]
    return list(chain)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    raise ValueError("model output is not valid JSON")


async def _chat_once(model: str, messages: list[dict], json_mode: bool):
    kwargs: dict = {"model": model, "messages": messages, "temperature": 0.3}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        return await client().chat.completions.create(**kwargs)
    except APIStatusError as e:
        if json_mode and e.status_code in (400, 422):
            kwargs.pop("response_format")
            return await client().chat.completions.create(**kwargs)
        raise


async def summarize(title: str, body: str):
    global _active_chat_model
    messages = [
        {"role": "system", "content": SYSTEM_SUMMARY},
        {"role": "user", "content": f"标题：{title}\n正文：{(body or '')[:800]}"},
    ]
    last_err: Exception | None = None
    for model in _order(MODEL_CHAIN, _active_chat_model):
        try:
            resp = await _chat_once(model, messages, json_mode=True)
            _active_chat_model = model
            try:
                data = _parse_json(resp.choices[0].message.content)
            except ValueError:
                data = {"summary": (resp.choices[0].message.content or "")[:120], "tags": [], "is_relevant": True}
            tokens = (resp.usage.total_tokens if resp.usage else 0) or 0
            return data, tokens, model
        except Exception as e:
            last_err = e
            if not _retryable(e):
                raise
            status = getattr(e, "status_code", type(e).__name__)
            print(f"  [model-fallback] {model} 失败({status}) -> 尝试下一个", flush=True)
    raise RuntimeError(f"所有 chat 模型均失败: {last_err}")


async def embed_texts(texts: list[str]) -> list[list[float]]:
    global _active_embed_model, _embedding_disabled
    if _embedding_disabled or not EMB_CHAIN:
        raise EmbeddingUnavailable("embedding 未配置或已禁用")
    out: list[list[float]] = []
    for i in range(0, len(texts), 10):
        batch = texts[i:i + 10]
        last_err: Exception | None = None
        for model in _order(EMB_CHAIN, _active_embed_model):
            try:
                resp = await client().embeddings.create(model=model, input=batch)
                _active_embed_model = model
                out.extend(d.embedding for d in resp.data)
                break
            except APIStatusError as e:
                last_err = e
                if e.status_code in (401, 403, 404):
                    _embedding_disabled = True
                    raise EmbeddingUnavailable(f"网关拒绝 embeddings ({e.status_code})") from e
                if not _retryable(e):
                    raise
                print(f"  [embed-fallback] {model} 失败({e.status_code}) -> 尝试下一个", flush=True)
            except Exception as e:
                last_err = e
                if not _retryable(e):
                    raise
                print(f"  [embed-fallback] {model} 失败({type(e).__name__}) -> 尝试下一个", flush=True)
        else:
            raise EmbeddingUnavailable(f"所有 embedding 模型失败: {last_err}")
        await asyncio.sleep(0.2)
    return out
