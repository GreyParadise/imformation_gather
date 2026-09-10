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
    if path.startswith("/api/") and path not in OPEN_API_PATHS and request.method != "OPTIONS":
        if APP_KEY:
            import hmac
            key = request.headers.get("x-app-key")
            if not key or not hmac.compare_digest(key, APP_KEY):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "invalid app key"}, status_code=401)
    return await call_next(request)


def _encode_cursor(published_at: str, article_id: int) -> str:
    raw = json.dumps([published_at, article_id])
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, int]:
    try:
        published_at, article_id = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return str(published_at), int(article_id)
    except (ValueError, binascii.Error, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="bad cursor")


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
):
    where = ["n.is_relevant = 1"]
    params: list = []
    if category:
        where.append("s.category = ?")
        params.append(category)
    if before:
        pub, aid = _decode_cursor(before)
        where.append("(a.published_at < ? OR (a.published_at = ? AND a.id < ?))")
        params += [pub, pub, aid]
    sql = f"""
        SELECT a.id, a.url, a.title, a.cover, a.published_at,
               n.summary, n.tags, n.cluster_size, n.heat,
               s.name AS source_name, s.category
        FROM news_items n
        JOIN articles a ON a.id = n.article_id
        JOIN sources s ON s.id = a.source_id
        WHERE {' AND '.join(where)}
        ORDER BY a.published_at DESC, a.id DESC
        LIMIT ?
    """
    params.append(size + 1)
    with db.get_db() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    has_more = len(rows) > size
    rows = rows[:size]
    for r in rows:
        try:
            r["tags"] = json.loads(r["tags"] or "[]")
        except json.JSONDecodeError:
            r["tags"] = []
    next_cursor = None
    if has_more and rows:
        next_cursor = _encode_cursor(rows[-1]["published_at"], rows[-1]["id"])
    return {"records": rows, "next_cursor": next_cursor}


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
