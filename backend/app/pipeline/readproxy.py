import hashlib
import hmac
import html as htmllib
import json
import re
import time
import urllib.parse
from datetime import datetime, timezone

import httpx
import trafilatura

from .. import db
from ..settings import HTTP_TIMEOUT
from .extract import html_to_text
from .httpclient import make_async_client

TTL_HOURS = 12
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMG_TAG_RE = re.compile(r'(<img[^>]*?)\ssrc="([^"]+)"([^>]*?>)', re.I)
SRCSET_RE = re.compile(r'\s+(?:srcset|data-srcset|loading)=("[^"]*"|\'[^\']*\'|[^\s>]+)', re.I)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sign_token(article_id: int) -> str:
    if not __token_key():
        return "dev"
    exp = int(time.time()) + 7 * 86400
    sig = hmac.new(__token_key().encode(), f"{article_id}:{exp}".encode(), hashlib.sha256).hexdigest()[:16]
    return f"{exp}.{sig}"


def __token_key() -> str:
    from ..settings import APP_KEY
    return APP_KEY


def verify_token(article_id: int, token: str | None) -> bool:
    key = __token_key()
    if not key:
        return True
    if not token:
        return False
    try:
        exp_s, sig = token.split(".", 1)
        if int(exp_s) < time.time():
            return False
        want = hmac.new(key.encode(), f"{article_id}:{exp_s}".encode(), hashlib.sha256).hexdigest()[:16]
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


def _abs_images(urls, base: str) -> list[str]:
    out, seen = [], set()
    for u in urls or []:
        if not u or u.startswith("data:"):
            continue
        absu = urllib.parse.urljoin(base, u.strip())
        if not absu.startswith("http") or absu in seen or _is_blocked_target(absu):
            continue
        seen.add(absu)
        out.append(absu)
    return out[:8]


def _paragraphize(text: str) -> str:
    if not text:
        return ""
    if "\n" in text:
        parts = [p.strip() for p in text.split("\n") if p.strip()]
    else:
        sents = re.split(r"(?<=[。！？；])", text)
        sents = [s for s in sents if s.strip()]
        parts = [" ".join(sents[i:i + 4]) for i in range(0, len(sents), 4)]
    return "".join(f"<p>{htmllib.escape(p)}</p>" for p in parts)


def build_rss_reader(a: dict, tok: str):
    body = (a.get("body") or "").strip()
    imgs_raw = []
    if a.get("body_imgs"):
        try:
            imgs_raw = json.loads(a["body_imgs"])
        except json.JSONDecodeError:
            imgs_raw = []
    if len(body) < 200:
        return None
    images = _abs_images(imgs_raw, a["url"])
    html_out = _paragraphize(body)
    if a.get("cover") and not images:
        images = _abs_images([a["cover"]], a["url"])
    img_tags = "".join(
        f'<img src="/api/img/{a["id"]}/{i}?t={tok}" alt="" loading="lazy"/>' for i in range(min(len(images), 3))
    )
    return {"html": img_tags + html_out, "images": images, "text_len": len(body)}


async def fetch_and_extract(client: httpx.AsyncClient, article_id: int, url: str):
    try:
        resp = await client.get(url, headers=BROWSER_HEADERS, timeout=HTTP_TIMEOUT, follow_redirects=True)
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
            include_tables=True,
            favor_recall=True,
        )
    except Exception:
        pass
    meta = None
    try:
        meta = trafilatura.extract_metadata(resp.text)
    except Exception:
        pass
    if not body_html:
        return None
    images: list[str] = []
    tok = sign_token(article_id)

    def repl(m: re.Match) -> str:
        src = m.group(2)
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
    text_len = len(html_to_text(body_html))
    return {
        "html": body_html,
        "images": images,
        "page_title": getattr(meta, "title", None) if meta else None,
        "byline": getattr(meta, "author", None) if meta else None,
        "text_len": text_len,
    }


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


def _store(article_id: int, url: str, html: str, images: list[str], page_title, byline, source: str):
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO reader_cache(article_id,url,html,images,page_title,byline,fetched_at,source) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(article_id) DO UPDATE SET "
            "url=excluded.url, html=excluded.html, images=excluded.images, "
            "page_title=excluded.page_title, byline=excluded.byline, fetched_at=excluded.fetched_at, source=excluded.source",
            (article_id, url, html, json.dumps(images), page_title, byline, _now_iso(), source),
        )


async def get_reader(article_id: int):
    with db.get_db() as conn:
        a = conn.execute(
            "SELECT a.id, a.url, a.title, a.body, a.cover, a.body_imgs FROM articles a WHERE a.id=?", (article_id,)
        ).fetchone()
    if not a:
        return {"error": "not_found"}
    url = a["url"]
    if _is_blocked_target(url) or not url.startswith("http"):
        return {"error": "blocked"}
    hit = cached(article_id)
    if hit:
        hit["title"] = a["title"]
        hit["source"] = hit.get("source") or "web"
        return hit

    web = None
    async with make_async_client() as client:
        try:
            web = await fetch_and_extract(client, article_id, url)
        except Exception:
            web = None

    rss = build_rss_reader(dict(a), sign_token(article_id))
    web_len = web["text_len"] if web else 0
    rss_len = rss["text_len"] if rss else 0

    if web and web_len >= 600 and (rss_len == 0 or web_len >= rss_len * 0.6):
        chosen, source = web, "web"
    elif rss and rss_len >= 200 and (not web or rss_len > web_len * 1.4):
        chosen, source = rss, "rss"
    elif web:
        chosen, source = web, "web_partial"
    else:
        return {"error": "extract_failed", "url": url}

    _store(article_id, url, chosen["html"], chosen.get("images") or [], chosen.get("page_title"), chosen.get("byline"), source)
    return {
        "article_id": article_id,
        "url": url,
        "title": a["title"],
        "page_title": chosen.get("page_title"),
        "byline": chosen.get("byline"),
        "html": chosen["html"],
        "images": chosen.get("images") or [],
        "source": source,
        "fetched_at": _now_iso(),
    }


async def proxy_image(client: httpx.AsyncClient, img_url: str, referer: str | None):
    headers = dict(BROWSER_HEADERS)
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
