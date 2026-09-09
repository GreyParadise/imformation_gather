import httpx

from ..settings import PROXY_URL, UA


def make_async_client(**kwargs) -> httpx.AsyncClient:
    kwargs.setdefault("headers", {"User-Agent": UA})
    if PROXY_URL:
        kwargs["proxy"] = PROXY_URL
    return httpx.AsyncClient(**kwargs)
