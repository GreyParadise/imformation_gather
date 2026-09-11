import asyncio
import re

import httpx
import trafilatura

from ..settings import HTTP_TIMEOUT, UA

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
BLOCK_END_RE = re.compile(r"</(p|div|br|li|h[1-6]|blockquote|article|section|tr)\s*/?>|<br\s*/?>", re.I)
IMG_SRC_RE_FIRST = re.compile(r'<img[^>]+src=["\'](https?://[^"\']+)', re.I)
IMG_ALL_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)


def imgs_from_html(html: str) -> list[str]:
    if not html:
        return []
    out, seen = [], set()
    for m in IMG_ALL_RE.finditer(html):
        src = m.group(1)
        if src.startswith("data:") or src in seen:
            continue
        seen.add(src)
        out.append(src)
    return out


def html_to_text(html: str) -> str:
    if not html:
        return ""
    text = BLOCK_END_RE.sub("\n\n", html)
    text = TAG_RE.sub(" ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    lines = [WS_RE.sub(" ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


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


OG_IMG_RES = [
    re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I),
    re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
]


JUNK_COVER_RE = re.compile(r"(logo|favicon|icon|placeholder|sprite|avatar|banner\.gif|1x1)", re.I)


def _valid_cover(img, base_url: str) -> str | None:
    if not img:
        return None
    from urllib.parse import urljoin
    absu = urljoin(base_url, img.strip())
    if not absu.startswith("http"):
        return None
    if JUNK_COVER_RE.search(absu):
        return None
    return absu


async def fetch_cover(client: httpx.AsyncClient, url: str):
    try:
        resp = await client.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT, follow_redirects=True)
        if resp.status_code >= 400:
            return None
        html = resp.text[:400000]
    except httpx.HTTPError:
        return None
    try:
        meta = trafilatura.extract_metadata(html)
        img = getattr(meta, "image", None) if meta else None
        if img:
            cov = _valid_cover(img, url)
            if cov:
                return cov
    except Exception:
        pass
    for rx in OG_IMG_RES:
        m = rx.search(html)
        if m:
            cov = _valid_cover(m.group(1), url)
            if cov:
                return cov
    m = IMG_SRC_RE_FIRST.search(html)
    if m:
        cov = _valid_cover(m.group(1), url)
        if cov:
            return cov
    return None


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


async def cover_batch(client: httpx.AsyncClient, items: list[dict], concurrency: int = 6):
    sem = asyncio.Semaphore(concurrency)

    async def worker(item: dict):
        async with sem:
            cover = await fetch_cover(client, item["url"])
        if cover and not item.get("cover"):
            item["cover"] = cover

    await asyncio.gather(*(worker(it) for it in items))
