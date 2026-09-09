import sqlite3
from contextlib import contextmanager

from .settings import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS categories (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'rss',
    url TEXT NOT NULL,
    category TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'news',
    weight REAL NOT NULL DEFAULT 1.0,
    enabled INTEGER NOT NULL DEFAULT 1,
    etag TEXT,
    last_modified TEXT,
    last_fetch_at TEXT,
    fail_count INTEGER NOT NULL DEFAULT 0,
    health TEXT NOT NULL DEFAULT 'ok'
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    url_hash TEXT NOT NULL UNIQUE,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    title TEXT NOT NULL,
    body TEXT,
    cover TEXT,
    author TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    simhash INTEGER,
    dup_of INTEGER,
    status TEXT NOT NULL DEFAULT 'raw',
    drop_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_articles_simhash ON articles(simhash);

CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL UNIQUE REFERENCES articles(id),
    summary TEXT,
    tags TEXT,
    cluster_id TEXT,
    cluster_size INTEGER DEFAULT 1,
    heat REAL DEFAULT 0,
    is_relevant INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embeddings (
    article_id INTEGER PRIMARY KEY REFERENCES articles(id),
    model TEXT NOT NULL,
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL
);
"""


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as db:
        db.executescript(SCHEMA)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
