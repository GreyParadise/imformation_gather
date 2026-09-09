from calendar import timegm
from datetime import datetime, timezone

import feedparser
import httpx

from ..settings import HTTP_TIMEOUT, UA


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
        })
    return {
        "ok": True,
        "not_modified": False,
        "error": None,
        "etag": resp.headers.get("etag"),
        "last_modified": resp.headers.get("last-modified"),
        "entries": entries,
    }
