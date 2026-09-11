import re
from calendar import timegm
from datetime import datetime, timezone
from urllib.parse import urljoin

import feedparser
import httpx

from ..settings import HTTP_TIMEOUT, UA
from .extract import imgs_from_html

IMG_SRC_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)
IMG_EXT_RE = re.compile(r"\.(jpe?g|png|webp|gif|avif)(\?|$)", re.I)


JUNK_COVER_RE = re.compile(r"(logo|favicon|icon|placeholder|sprite|avatar|1x1)", re.I)


def _clean_cover(url, base):
    if not url:
        return None
    absu = urljoin(base, url.strip()) if base else url.strip()
    if not absu.startswith("http") or JUNK_COVER_RE.search(absu):
        return None
    return absu


def _entry_cover(entry, link: str, payload_html: str) -> str | None:
    for key in ("media_thumbnail", "media_content"):
        for m in entry.get(key) or []:
            url = m.get("url") if isinstance(m, dict) else None
            if not url:
                continue
            medium = (m.get("medium") or "") if isinstance(m, dict) else ""
            mtype = (m.get("type") or "") if isinstance(m, dict) else ""
            if key == "media_thumbnail" or medium == "image" or mtype.startswith("image") or IMG_EXT_RE.search(url):
                cov = _clean_cover(url, link)
                if cov:
                    return cov
    for enc in entry.get("enclosures") or []:
        url = enc.get("url") if isinstance(enc, dict) else None
        if url and (str(enc.get("type", "")).startswith("image") or IMG_EXT_RE.search(url)):
            cov = _clean_cover(url, link)
            if cov:
                return cov
    it_img = entry.get("itunes_image")
    if isinstance(it_img, dict) and it_img.get("href"):
        cov = _clean_cover(it_img["href"], link)
        if cov:
            return cov
    m = IMG_SRC_RE.search(payload_html or "")
    if m:
        cov = _clean_cover(m.group(1), link)
        if cov:
            return cov
    return None


def _ts(struct) -> str | None:
    try:
        dt = datetime.fromtimestamp(timegm(struct), tz=timezone.utc)
        return dt.isoformat()
    except Exception:
        return None


def _entry_published(entry) -> str | None:
    for field in ("published_parsed", "updated_parsed"):
        v = getattr(entry, field, None) or entry.get(field)
        if v:
            return _ts(v)
    return None


async def fetch_feed(client: httpx.AsyncClient, url: str, etag: str | None, last_modified: str | None):
    headers = {"User-Agent": UA}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        resp = await client.get(url, headers=headers, timeout=HTTP_TIMEOUT, follow_redirects=True)
    except httpx.HTTPError as e:
        return {"ok": False, "error": type(e).__name__, "not_modified": False, "entries": []}
    if resp.status_code == 304:
        return {"ok": True, "not_modified": True, "error": None, "etag": etag, "last_modified": last_modified, "entries": []}
    if resp.status_code >= 400:
        return {"ok": False, "error": f"HTTP {resp.status_code}", "not_modified": False, "entries": []}
    feed = feedparser.parse(resp.content)
    entries = []
    for e in feed.entries:
        link = (e.get("link") or "").strip()
        if not link:
            continue
        body_html = ""
        if e.get("content"):
            body_html = e["content"][0].get("value", "")
        elif e.get("summary"):
            body_html = e["summary"]
        entries.append({
            "url": link,
            "title": (e.get("title") or "").strip(),
            "author": (e.get("author") or "").strip() or None,
            "published_at": _entry_published(e),
            "payload_html": body_html,
            "payload_imgs": imgs_from_html(body_html)[:6],
            "cover": _entry_cover(e, link, body_html),
        })
    return {
        "ok": True,
        "not_modified": False,
        "error": None,
        "etag": resp.headers.get("etag"),
        "last_modified": resp.headers.get("last-modified"),
        "entries": entries,
    }
