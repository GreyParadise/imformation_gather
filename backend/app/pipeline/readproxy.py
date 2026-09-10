import hashlib
import hmac
import json
import re
import time
import urllib.parse
from datetime import datetime, timezone

import httpx
import trafilatura

from .. import db
from ..settings import APP_KEY, HTTP_TIMEOUT, UA
from .httpclient import make_async_client

TTL_HOURS = 12
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMG_TAG_RE = re.compile(r'(<img[^>]*?)\ssrc="([^"]+)"([^>]*?>)', re.I)
SRCSET_RE = re.compile(r'\s+(?:srcset|data-srcset|loading)=("[^"]*"|\'[^\']*\'|[^\s>]+)', re.I)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sign_token(article_id: int) -> str:
    if not APP_KEY:
        return "dev"
    exp = int(time.time()) + 7 * 86400
    sig = hmac.new(APP_KEY.encode(), f"{article_id}:{exp}".encode(), hashlib.sha256).hexdigest()[:16]
    return f"{exp}.{sig}"


def verify_token(article_id: int, token: str | None) -> bool:
    if not APP_KEY:
        return True
    if not token:
        return False
    try:
        exp_s, sig = token.split(".", 1)
        if int(exp_s) < time.time():
            return False
        want = hmac.new(APP_KEY.encode(), f"{article_id}:{exp_s}".encode(), hashlib.sha256).hexdigest()[:16]
        return hmac.compare_digest(want, sig)
    except (ValueError, TypeError):
        return False


def _is_blocked_target(url: str) -> bool:
    import ipaddress
    host = urllib.parse.urlsplit(url).hostname or ""
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        return host in ("localhost", "metadata.google.internal") or host.endswith(".local")


async def fetch_and_extract(client: httpx.AsyncClient, article_id: int, url: str):
    try:
        resp = await client.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT, follow_redirects=True)
        if resp.status_code >= 400 or "html" not in resp.headers.get("content-type", "text/html"):
            return None
    except httpx.HTTPError:
        return None
    body_html = None
    try:
        body_html = trafilatura.extract(
            resp.text,
            output_format="html",
            include_formatting=True,
            include_links=False,
            include_images=True,
            include_comments=False,
            favor_recall=True,
        )
    except Exception:
        pass
    meta = None
    try:
        meta = trafilatura.extract_metadata(resp.text)
    except Exception:
        pass
    if not body_html or len(body_html) < 120:
        return None
    images: list[str] = []

    tok = sign_token(article_id)

    def repl(m: re.Match) -> str:
        tag, src = m.group(0), m.group(2)
        if src.startswith("data:"):
            return ""
        absu = urllib.parse.urljoin(url, src)
        if not absu.startswith("http") or _is_blocked_target(absu):
            return ""
        if absu not in images:
            images.append(absu)
        idx = images.index(absu)
        return m.group(1) + f' src="/api/img/{article_id}/{idx}?t={tok}"' + m.group(3)

    body_html = SRCSET_RE.sub("", body_html)
    body_html = IMG_TAG_RE.sub(repl, body_html)
    row = {
        "article_id": article_id,
        "url": url,
        "html": body_html,
        "images": images,
        "page_title": getattr(meta, "title", None) if meta else None,
        "byline": getattr(meta, "author", None) if meta else None,
    }
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO reader_cache(article_id,url,html,images,page_title,byline,fetched_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(article_id) DO UPDATE SET "
            "url=excluded.url, html=excluded.html, images=excluded.images, "
            "page_title=excluded.page_title, byline=excluded.byline, fetched_at=excluded.fetched_at",
            (article_id, url, body_html, json.dumps(images), row["page_title"], row["byline"], _now_iso()),
        )
    return row


def cached(article_id: int):
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT * FROM reader_cache WHERE article_id=? AND fetched_at > datetime('now', ?)",
            (article_id, f"-{TTL_HOURS} hours"),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["images"] = json.loads(d["images"] or "[]")
    except json.JSONDecodeError:
        d["images"] = []
    return d


async def get_reader(article_id: int):
    with db.get_db() as conn:
        a = conn.execute(
            "SELECT a.id, a.url, a.title FROM articles a WHERE a.id=?", (article_id,)
        ).fetchone()
    if not a:
        return {"error": "not_found"}
    url = a["url"]
    if _is_blocked_target(url) or not url.startswith("http"):
        return {"error": "blocked"}
    hit = cached(article_id)
    if hit:
        hit["title"] = a["title"]
        return hit
    async with make_async_client() as client:
        fresh = await fetch_and_extract(client, article_id, url)
    if fresh:
        fresh["title"] = a["title"]
        return fresh
    return {"error": "extract_failed", "url": url}


async def proxy_image(client: httpx.AsyncClient, img_url: str, referer: str | None):
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    try:
        resp = await client.get(img_url, headers=headers, timeout=HTTP_TIMEOUT, follow_redirects=True)
    except httpx.HTTPError:
        return None
    ct = resp.headers.get("content-type", "")
    if resp.status_code >= 400 or not ct.startswith("image") or len(resp.content) > MAX_IMAGE_BYTES:
        return None
    return resp.content, ct
