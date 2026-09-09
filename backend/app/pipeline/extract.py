import asyncio
import re

import httpx
import trafilatura

from ..settings import HTTP_TIMEOUT, UA

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def html_to_text(html: str) -> str:
    if not html:
        return ""
    text = TAG_RE.sub(" ", html)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    return WS_RE.sub(" ", text).strip()


async def enrich_article(client: httpx.AsyncClient, url: str):
    try:
        resp = await client.get(
            url,
            headers={"User-Agent": UA},
            timeout=HTTP_TIMEOUT,
            follow_redirects=True,
        )
        if resp.status_code >= 400:
            return None
        html = resp.text
    except httpx.HTTPError:
        return None
    meta = trafilatura.extract_metadata(html)
    body = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
    )
    cover = getattr(meta, "image", None) if meta else None
    return {"body": body, "cover": cover, "meta_date": getattr(meta, "date", None) if meta else None}


async def enrich_batch(client: httpx.AsyncClient, items: list[dict], concurrency: int = 8):
    sem = asyncio.Semaphore(concurrency)

    async def worker(item: dict):
        async with sem:
            info = await enrich_article(client, item["url"])
        if not info:
            return
        if info.get("body"):
            item["body"] = info["body"]
        if info.get("cover") and not item.get("cover"):
            item["cover"] = info["cover"]

    await asyncio.gather(*(worker(it) for it in items))
