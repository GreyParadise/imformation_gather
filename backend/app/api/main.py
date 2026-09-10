import base64
import binascii
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import feedparser
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .. import db
from ..pipeline.httpclient import make_async_client
from ..pipeline import readproxy
from ..settings import APP_KEY

app = FastAPI(title="InfoGather API", lifespan=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

OPEN_API_PATHS = {"/api/health"}


def verify_key(x_app_key: Optional[str] = Header(None)):
    if not APP_KEY:
        return
    import hmac
    if not x_app_key or not hmac.compare_digest(x_app_key, APP_KEY):
        raise HTTPException(status_code=401, detail="invalid app key")


Auth = Depends(verify_key)


@app.on_event("startup")
async def startup():
    db.init_db()


@app.middleware("http")
async def auth_middleware(request, call_next):
    path = request.url.path
    if path.startswith("/api/img/") or path.startswith("/api/cover/"):
        if APP_KEY:
            import hmac
            header_ok = False
            key = request.headers.get("x-app-key")
            if key:
                header_ok = hmac.compare_digest(key, APP_KEY)
            parts = path.split("/")
            try:
                aid = int(parts[3])
            except (IndexError, ValueError):
                return JSONResponse401()
            if not (header_ok or readproxy.verify_token(aid, request.query_params.get("t"))):
                return JSONResponse401()
    elif path.startswith("/api/") and path not in OPEN_API_PATHS and request.method != "OPTIONS":
        if APP_KEY:
            import hmac
            key = request.headers.get("x-app-key")
            if not key or not hmac.compare_digest(key, APP_KEY):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "invalid app key"}, status_code=401)
    return await call_next(request)


def JSONResponse401():
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": "invalid or missing media token"}, status_code=401)


def _encode_cursor(published_at: str, article_id: int) -> str:
    raw = json.dumps([published_at, article_id])
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, int]:
    try:
        published_at, article_id = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return str(published_at), int(article_id)
    except (ValueError, binascii.Error, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="bad cursor")


def _decode_offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        v = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return int(v[0]) if isinstance(v, list) else int(v)
    except Exception:
        return 0


def _esc_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


PER_SOURCE_QUOTA = 10


def scatter(rows: list[dict], cap: int = PER_SOURCE_QUOTA) -> list[dict]:
    srcs: dict[int, list] = {}
    for r in rows:
        srcs.setdefault(r["source_id"], []).append(r)
    idx = {k: 0 for k in srcs}
    cnt = {k: 0 for k in srcs}
    out: list[dict] = []
    n = len(rows)
    for limit in (cap, cap * 3, n + 1):
        while len(out) < n:
            best_sid, best_t = None, None
            for sid, lst in srcs.items():
                i = idx[sid]
                if i >= len(lst) or cnt[sid] >= limit:
                    continue
                t = lst[i]["published_at"]
                if best_t is None or t > best_t:
                    best_sid, best_t = sid, t
            if best_sid is None:
                break
            out.append(srcs[best_sid][idx[best_sid]])
            idx[best_sid] += 1
            cnt[best_sid] += 1
    return out


@app.get("/api/health")
async def health():
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/categories", dependencies=[Auth])
async def categories():
    with db.get_db() as conn:
        rows = conn.execute(
            """
            SELECT c.key, c.name, COUNT(n.id) AS count
            FROM categories c
            LEFT JOIN sources s ON s.category = c.key
            LEFT JOIN articles a ON a.source_id = s.id AND a.status = 'listed'
            LEFT JOIN news_items n ON n.article_id = a.id
            GROUP BY c.key ORDER BY c.key
            """
        ).fetchall()
    return {"categories": [dict(r) for r in rows]}


@app.get("/api/news", dependencies=[Auth])
async def news(
    category: Optional[str] = Query(None),
    before: Optional[str] = Query(None),
    size: int = Query(30, ge=1, le=50),
    q: Optional[str] = Query(None),
    source: Optional[int] = Query(None),
    tag: Optional[str] = Query(None),
):
    offset = _decode_offset(before)
    where = ["n.is_relevant = 1"]
    params: list = []
    if category:
        where.append("s.category = ?")
        params.append(category)
    if source:
        where.append("s.id = ?")
        params.append(source)
    if tag:
        where.append("n.tags LIKE ? ESCAPE '\\'")
        params.append(f'%"{_esc_like(tag)}"%')
    if q:
        where.append("(a.title LIKE ? ESCAPE '\\' OR n.summary LIKE ? ESCAPE '\\' OR n.tags LIKE ? ESCAPE '\\')")
        like = f"%{_esc_like(q)}%"
        params += [like, like, like]
    where_sql = " AND ".join(where)
    base_from = f"""
        FROM news_items n
        JOIN articles a ON a.id = n.article_id
        JOIN sources s ON s.id = a.source_id
        WHERE {where_sql}
    """
    select_cols = """
        SELECT a.id, a.source_id, a.url, a.title, a.cover, a.published_at,
               n.summary, n.tags, n.cluster_size, n.heat,
               s.name AS source_name, s.category
    """
    with db.get_db() as conn:
        total = conn.execute(f"SELECT COUNT(1) c {base_from}", params).fetchone()["c"]
        if q:
            sql = f"{select_cols} {base_from} ORDER BY a.published_at DESC, a.id DESC LIMIT ? OFFSET ?"
            rows = [dict(r) for r in conn.execute(sql, (*params, size + 1, offset)).fetchall()]
            page = rows[:size]
            has_more = offset + size < total
        else:
            fetch_limit = max(offset + size + 1, 600)
            sql = f"{select_cols} {base_from} ORDER BY a.published_at DESC, a.id DESC LIMIT ?"
            allrows = [dict(r) for r in conn.execute(sql, (*params, fetch_limit)).fetchall()]
            truncated = len(allrows) >= fetch_limit
            ordered = scatter(allrows)
            page = ordered[offset: offset + size]
            has_more = offset + size < len(ordered) or truncated
    for r in page:
        try:
            r["tags"] = json.loads(r["tags"] or "[]")
        except json.JSONDecodeError:
            r["tags"] = []
        if r.get("cover"):
            r["cover_token"] = readproxy.sign_token(r["id"])
    if has_more:
        raw = json.dumps(str(offset + size))
        next_cursor = base64.urlsafe_b64encode(raw.encode()).decode()
    else:
        next_cursor = None
    return {"records": page, "next_cursor": next_cursor, "total": total}


@app.get("/api/tags", dependencies=[Auth])
async def tags_api(category: Optional[str] = Query(None)):
    from collections import Counter
    where = ["n.is_relevant = 1"]
    params: list = []
    if category:
        where.append("s.category = ?")
        params.append(category)
    with db.get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT n.tags FROM news_items n
            JOIN articles a ON a.id = n.article_id
            JOIN sources s ON s.id = a.source_id
            WHERE {' AND '.join(where)}
            """,
            params,
        ).fetchall()
    counter: Counter = Counter()
    for r in rows:
        try:
            for t in json.loads(r["tags"] or "[]"):
                counter[str(t)] += 1
        except json.JSONDecodeError:
            pass
    return {"tags": [{"name": k, "count": v} for k, v in counter.most_common(24)]}


@app.get("/api/read/{article_id}", dependencies=[Auth])
async def read_article(article_id: int):
    result = await readproxy.get_reader(article_id)
    if "error" in result and result.get("error") in ("not_found", "blocked"):
        raise HTTPException(status_code=404 if result["error"] == "not_found" else 400, detail=result["error"])
    return {
        "article_id": article_id,
        "title": result.get("title"),
        "page_title": result.get("page_title"),
        "byline": result.get("byline"),
        "url": result.get("url"),
        "html": result.get("html"),
        "error": result.get("error"),
        "cached_at": result.get("fetched_at"),
    }


@app.get("/api/img/{article_id}/{idx}")
async def proxy_img(article_id: int, idx: int):
    hit = readproxy.cached(article_id)
    if not hit:
        raise HTTPException(status_code=404, detail="not cached")
    images = hit.get("images") or []
    if idx < 0 or idx >= len(images):
        raise HTTPException(status_code=400, detail="bad index")
    async with make_async_client() as client:
        got = await readproxy.proxy_image(client, images[idx], hit.get("url"))
    if not got:
        raise HTTPException(status_code=404, detail="image unavailable")
    content, ct = got
    from fastapi.responses import Response
    return Response(content=content, media_type=ct, headers={"Cache-Control": "public, max-age=604800"})


@app.get("/api/cover/{article_id}")
async def proxy_cover(article_id: int):
    with db.get_db() as conn:
        row = conn.execute("SELECT cover, url FROM articles WHERE id=?", (article_id,)).fetchone()
    if not row or not row["cover"] or readproxy._is_blocked_target(row["cover"]):
        raise HTTPException(status_code=404, detail="no cover")
    async with make_async_client() as client:
        got = await readproxy.proxy_image(client, row["cover"], row["url"])
    if not got:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(row["cover"])
    content, ct = got
    from fastapi.responses import Response
    return Response(content=content, media_type=ct, headers={"Cache-Control": "public, max-age=604800"})


@app.get("/api/updates", dependencies=[Auth])
async def updates(
    before: Optional[str] = Query(None),
    size: int = Query(30, ge=1, le=50),
):
    where = ["s.mode = 'subscription'", "s.enabled = 1", "a.dup_of IS NULL"]
    params: list = []
    if before:
        pub, aid = _decode_cursor(before)
        where.append("(a.published_at < ? OR (a.published_at = ? AND a.id < ?))")
        params += [pub, pub, aid]
    sql = f"""
        SELECT a.id, a.url, a.title, a.cover, a.published_at,
               s.name AS source_name, s.category
        FROM articles a JOIN sources s ON s.id = a.source_id
        WHERE {' AND '.join(where)}
        ORDER BY a.published_at DESC, a.id DESC
        LIMIT ?
    """
    params.append(size + 1)
    with db.get_db() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    has_more = len(rows) > size
    rows = rows[:size]
    next_cursor = _encode_cursor(rows[-1]["published_at"], rows[-1]["id"]) if has_more and rows else None
    return {"records": rows, "next_cursor": next_cursor}


@app.get("/api/stats", dependencies=[Auth])
async def stats():
    with db.get_db() as conn:
        out = {
            "sources_total": conn.execute("SELECT COUNT(1) c FROM sources").fetchone()["c"],
            "sources_ok": conn.execute("SELECT COUNT(1) c FROM sources WHERE health='ok' AND enabled=1").fetchone()["c"],
            "articles_total": conn.execute("SELECT COUNT(1) c FROM articles").fetchone()["c"],
            "news_total": conn.execute("SELECT COUNT(1) c FROM news_items").fetchone()["c"],
            "last_fetch": conn.execute("SELECT MAX(last_fetch_at) t FROM sources").fetchone()["t"],
        }
    return out


@app.get("/api/news/item/{article_id}", dependencies=[Auth])
async def news_item(article_id: int):
    with db.get_db() as conn:
        row = conn.execute(
            """
            SELECT a.id, a.url, a.title, a.cover, a.published_at, substr(a.body, 1, 800) AS excerpt,
                   n.summary, n.tags, n.cluster_id, n.cluster_size, n.heat,
                   s.name AS source_name, s.category
            FROM news_items n
            JOIN articles a ON a.id = n.article_id
            JOIN sources s ON s.id = a.source_id
            WHERE a.id = ?
            """,
            (article_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    r = dict(row)
    try:
        r["tags"] = json.loads(r["tags"] or "[]")
    except json.JSONDecodeError:
        r["tags"] = []
    if r.get("cover"):
        r["cover_token"] = readproxy.sign_token(article_id)
    if r.get("cluster_id"):
        with db.get_db() as conn:
            others = conn.execute(
                "SELECT s.name AS source_name, a.url, a.title FROM news_items n "
                "JOIN articles a ON a.id=n.article_id JOIN sources s ON s.id=a.source_id "
                "WHERE n.cluster_id=? AND n.article_id!=? ORDER BY a.published_at DESC LIMIT 5",
                (r["cluster_id"], article_id),
            ).fetchall()
        r["related"] = [dict(o) for o in others]
    r.pop("cluster_id", None)
    return r


@app.post("/api/sources/test", dependencies=[Auth])
async def test_source(payload: dict):
    url = (payload.get("url") or "").strip()
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="url must start with http")
    async with make_async_client(timeout=20, follow_redirects=True) as client:
        try:
            resp = await client.get(url)
        except Exception as e:
            return {"ok": False, "error": type(e).__name__}
    feed = feedparser.parse(resp.content)
    if not feed.entries:
        return {"ok": False, "error": "no feed entries parsed"}
    return {
        "ok": True,
        "feed_title": getattr(feed.feed, "title", "") or "",
        "count": len(feed.entries),
        "samples": [
            {"title": e.get("title", ""), "url": e.get("link", ""), "published": e.get("published", "")}
            for e in feed.entries[:5]
        ],
    }


def _slug_from_url(url: str) -> str:
    import hashlib
    from urllib.parse import urlsplit
    host = urlsplit(url).netloc.lower().replace("www.", "")
    return host.replace(".", "_") + "_" + hashlib.md5(url.encode()).hexdigest()[:6]


@app.post("/api/sources", dependencies=[Auth])
async def add_source(payload: dict):
    url = (payload.get("url") or "").strip()
    name = (payload.get("name") or "").strip()
    category = payload.get("category") or "tech_ai"
    mode = payload.get("mode") or "news"
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="url must start with http")
    test = await test_source({"url": url})
    if not test["ok"]:
        raise HTTPException(status_code=422, detail=f"源无法解析为 RSS: {test.get('error')}")
    key = _slug_from_url(url)
    cat_name = (payload.get("category_name") or "").strip()
    with db.get_db() as conn:
        if cat_name:
            conn.execute(
                "INSERT INTO categories(key,name) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET name=excluded.name",
                (category, cat_name),
            )
        exists = conn.execute("SELECT id FROM sources WHERE url=?", (url,)).fetchone()
        if exists:
            raise HTTPException(status_code=409, detail="该 URL 已存在")
        conn.execute(
            "INSERT INTO sources(key,name,type,url,category,mode,weight,enabled) VALUES(?,?,?,?,?,?,1.0,1)",
            (key, name or test["feed_title"] or key, "rss", url, category, mode),
        )
    return {"ok": True, "key": key, "name": name or test["feed_title"]}


@app.get("/api/sources", dependencies=[Auth])
async def list_sources():
    with db.get_db() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.key, s.name, s.type, s.url, s.category, s.mode, s.enabled,
                   s.health, s.fail_count, s.last_fetch_at,
                   COUNT(a.id) AS article_count
            FROM sources s LEFT JOIN articles a ON a.source_id = s.id
            GROUP BY s.id ORDER BY s.category, s.id
            """
        ).fetchall()
    return {"sources": [dict(r) for r in rows]}


@app.patch("/api/sources/{source_id}", dependencies=[Auth])
async def update_source(source_id: int, payload: dict):
    allowed = {k: payload[k] for k in ("enabled", "name", "category", "mode", "weight") if k in payload}
    if not allowed:
        raise HTTPException(status_code=400, detail="no editable fields")
    sets = ", ".join(f"{k}=?" for k in allowed)
    with db.get_db() as conn:
        if not conn.execute("SELECT id FROM sources WHERE id=?", (source_id,)).fetchone():
            raise HTTPException(status_code=404, detail="not found")
        conn.execute(f"UPDATE sources SET {sets} WHERE id=?", (*allowed.values(), source_id))
    return {"ok": True}


@app.delete("/api/sources/{source_id}", dependencies=[Auth])
async def delete_source(source_id: int):
    with db.get_db() as conn:
        row = conn.execute("SELECT id FROM sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        conn.execute("DELETE FROM news_items WHERE article_id IN (SELECT id FROM articles WHERE source_id=?)", (source_id,))
        conn.execute("DELETE FROM embeddings WHERE article_id IN (SELECT id FROM articles WHERE source_id=?)", (source_id,))
        conn.execute("DELETE FROM articles WHERE source_id=?", (source_id,))
        conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
    return {"ok": True}


_dist = Path(__file__).resolve().parents[3] / "app" / "dist"
if _dist.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_dist, html=True), name="h5")


def run():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    run()
