"""SQLite-хранилище: очередь постов, реестр медиа, состояние токена."""

import json
import os
import sqlite3
import threading
import time
import uuid

from config import DB_PATH

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id              TEXT PRIMARY KEY,
    chat_id         INTEGER NOT NULL,
    message_id      INTEGER NOT NULL,
    media_group_id  TEXT,
    text            TEXT NOT NULL DEFAULT '',
    media           TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'pending',
    attempts        INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    threads_ids     TEXT,
    publish_after   REAL NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_msg ON posts(chat_id, message_id);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status, publish_after);
CREATE INDEX IF NOT EXISTS idx_posts_group ON posts(media_group_id);

CREATE TABLE IF NOT EXISTS media (
    key        TEXT PRIMARY KEY,
    file_id    TEXT NOT NULL,
    kind       TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


_conn = _connect()


def init():
    with _lock:
        _conn.executescript(SCHEMA)
        _conn.commit()


# --- Посты ---

def upsert_post(chat_id: int, message_id: int, media_group_id, text: str,
                media: list, publish_after: float) -> str:
    """
    Создаёт пост или, если это следующая часть альбома, дописывает медиа
    к уже существующей записи той же группы.

    Возвращает id записи.
    """
    now = time.time()
    with _lock:
        # Часть альбома: подклеиваем к существующей группе, если она ещё не ушла в работу.
        if media_group_id:
            row = _conn.execute(
                "SELECT * FROM posts WHERE media_group_id = ? AND status = 'pending'"
                " ORDER BY created_at LIMIT 1",
                (str(media_group_id),),
            ).fetchone()
            if row:
                merged_media = json.loads(row["media"]) + media
                # У альбома подпись есть только у одного элемента — берём непустую.
                merged_text = row["text"] or text
                _conn.execute(
                    "UPDATE posts SET media = ?, text = ?, publish_after = ?, updated_at = ?"
                    " WHERE id = ?",
                    (json.dumps(merged_media), merged_text, publish_after, now, row["id"]),
                )
                _conn.commit()
                return row["id"]

        post_id = uuid.uuid4().hex
        try:
            _conn.execute(
                "INSERT INTO posts (id, chat_id, message_id, media_group_id, text, media,"
                " status, attempts, publish_after, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)",
                (
                    post_id, chat_id, message_id,
                    str(media_group_id) if media_group_id else None,
                    text, json.dumps(media), publish_after, now, now,
                ),
            )
            _conn.commit()
            return post_id
        except sqlite3.IntegrityError:
            # Telegram повторил доставку того же message_id — не дублируем.
            row = _conn.execute(
                "SELECT id FROM posts WHERE chat_id = ? AND message_id = ?",
                (chat_id, message_id),
            ).fetchone()
            return row["id"] if row else ""


def claim_ready_posts(limit: int = 5) -> list:
    """Забирает готовые к публикации посты и помечает их как processing."""
    now = time.time()
    with _lock:
        rows = _conn.execute(
            "SELECT * FROM posts WHERE status = 'pending' AND publish_after <= ?"
            " ORDER BY created_at LIMIT ?",
            (now, limit),
        ).fetchall()
        if rows:
            ids = [r["id"] for r in rows]
            _conn.executemany(
                "UPDATE posts SET status = 'processing', updated_at = ? WHERE id = ?",
                [(now, i) for i in ids],
            )
            _conn.commit()
        return [dict(r) for r in rows]


def mark_posted(post_id: str, threads_ids: list):
    now = time.time()
    with _lock:
        _conn.execute(
            "UPDATE posts SET status = 'posted', threads_ids = ?, error = NULL,"
            " updated_at = ? WHERE id = ?",
            (json.dumps(threads_ids), now, post_id),
        )
        _conn.commit()


def mark_retry(post_id: str, error: str, retry_after: float, max_attempts: int):
    """Возвращает пост в очередь либо помечает как окончательно упавший."""
    now = time.time()
    with _lock:
        row = _conn.execute("SELECT attempts FROM posts WHERE id = ?", (post_id,)).fetchone()
        attempts = (row["attempts"] if row else 0) + 1
        status = "pending" if attempts < max_attempts else "failed"
        _conn.execute(
            "UPDATE posts SET status = ?, attempts = ?, error = ?, publish_after = ?,"
            " updated_at = ? WHERE id = ?",
            (status, attempts, error[:1000], retry_after, now, post_id),
        )
        _conn.commit()


def requeue_stuck(older_than_seconds: int = 600):
    """Возвращает в очередь посты, зависшие в processing (например, после рестарта)."""
    cutoff = time.time() - older_than_seconds
    with _lock:
        _conn.execute(
            "UPDATE posts SET status = 'pending' WHERE status = 'processing' AND updated_at < ?",
            (cutoff,),
        )
        _conn.commit()


def stats() -> dict:
    with _lock:
        rows = _conn.execute(
            "SELECT status, COUNT(*) AS n FROM posts GROUP BY status"
        ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def recent_posts(limit: int = 20) -> list:
    with _lock:
        rows = _conn.execute(
            "SELECT id, message_id, status, attempts, error, created_at FROM posts"
            " ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# --- Медиа ---

def register_media(file_id: str, kind: str) -> str:
    """Регистрирует file_id и возвращает случайный ключ для публичной ссылки."""
    key = uuid.uuid4().hex
    with _lock:
        _conn.execute(
            "INSERT INTO media (key, file_id, kind, created_at) VALUES (?, ?, ?, ?)",
            (key, file_id, kind, time.time()),
        )
        _conn.commit()
    return key


def get_media(key: str):
    with _lock:
        row = _conn.execute("SELECT * FROM media WHERE key = ?", (key,)).fetchone()
    return dict(row) if row else None


# --- Состояние (токен и прочее) ---

def get_state(key: str, default=None):
    with _lock:
        row = _conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(key: str, value: str):
    with _lock:
        _conn.execute(
            "INSERT INTO state (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        _conn.commit()
