"""SQLite: пачки сообщений, очередь публикации, реестр медиа, состояние токена."""

import json
import os
import sqlite3
import threading
import time
import uuid

from config import DB_PATH

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS bursts (
    id            TEXT PRIMARY KEY,
    chat_id       INTEGER NOT NULL,
    candidates    TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'open',
    attempts      INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    threads_ids   TEXT,
    publish_after REAL NOT NULL DEFAULT 0,
    last_msg_at   REAL NOT NULL,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bursts_status ON bursts(status, publish_after);
CREATE INDEX IF NOT EXISTS idx_bursts_chat ON bursts(chat_id, status, last_msg_at);

CREATE TABLE IF NOT EXISTS seen_messages (
    chat_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS media (
    key        TEXT PRIMARY KEY,
    path       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    mime       TEXT NOT NULL DEFAULT 'application/octet-stream',
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


# --- Дедупликация входящих сообщений ---

def mark_seen(chat_id: int, message_id: int) -> bool:
    """True, если сообщение новое. False, если уже обрабатывали."""
    with _lock:
        try:
            _conn.execute(
                "INSERT INTO seen_messages (chat_id, message_id, created_at) VALUES (?, ?, ?)",
                (chat_id, message_id, time.time()),
            )
            _conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


# --- Пачки ---

def add_candidate(chat_id: int, candidate: dict, burst_window: float,
                  burst_wait: float, grouped_id=None) -> str:
    """
    Кладёт вариант поста в открытую пачку этого чата либо создаёт новую.

    Если у сообщения есть grouped_id (альбом), медиа подклеивается
    к уже существующему кандидату той же группы.
    """
    now = time.time()
    with _lock:
        row = _conn.execute(
            "SELECT * FROM bursts WHERE chat_id = ? AND status = 'open'"
            " AND last_msg_at > ? ORDER BY created_at DESC LIMIT 1",
            (chat_id, now - burst_window),
        ).fetchone()

        if row:
            candidates = json.loads(row["candidates"])

            if grouped_id is not None:
                for c in candidates:
                    if c.get("grouped_id") == grouped_id:
                        c["media"].extend(candidate["media"])
                        if not c.get("text"):
                            c["text"] = candidate.get("text", "")
                        _conn.execute(
                            "UPDATE bursts SET candidates = ?, last_msg_at = ?,"
                            " publish_after = ?, updated_at = ? WHERE id = ?",
                            (json.dumps(candidates), now, now + burst_wait, now, row["id"]),
                        )
                        _conn.commit()
                        return row["id"]

            candidates.append(candidate)
            _conn.execute(
                "UPDATE bursts SET candidates = ?, last_msg_at = ?,"
                " publish_after = ?, updated_at = ? WHERE id = ?",
                (json.dumps(candidates), now, now + burst_wait, now, row["id"]),
            )
            _conn.commit()
            return row["id"]

        burst_id = uuid.uuid4().hex
        _conn.execute(
            "INSERT INTO bursts (id, chat_id, candidates, status, publish_after,"
            " last_msg_at, created_at, updated_at)"
            " VALUES (?, ?, ?, 'open', ?, ?, ?, ?)",
            (burst_id, chat_id, json.dumps([candidate]), now + burst_wait, now, now, now),
        )
        _conn.commit()
        return burst_id


def claim_ready_bursts(limit: int = 5) -> list:
    """Забирает созревшие пачки и помечает их processing."""
    now = time.time()
    with _lock:
        rows = _conn.execute(
            "SELECT * FROM bursts WHERE status IN ('open', 'pending')"
            " AND publish_after <= ? ORDER BY created_at LIMIT ?",
            (now, limit),
        ).fetchall()
        if rows:
            _conn.executemany(
                "UPDATE bursts SET status = 'processing', updated_at = ? WHERE id = ?",
                [(now, r["id"]) for r in rows],
            )
            _conn.commit()
        return [dict(r) for r in rows]


def mark_posted(burst_id: str, threads_ids: list):
    now = time.time()
    with _lock:
        _conn.execute(
            "UPDATE bursts SET status = 'posted', threads_ids = ?, error = NULL,"
            " updated_at = ? WHERE id = ?",
            (json.dumps(threads_ids), now, burst_id),
        )
        _conn.commit()


def mark_skipped(burst_id: str, reason: str):
    now = time.time()
    with _lock:
        _conn.execute(
            "UPDATE bursts SET status = 'skipped', error = ?, updated_at = ? WHERE id = ?",
            (reason[:200], now, burst_id),
        )
        _conn.commit()


def mark_retry(burst_id: str, error: str, retry_after: float, max_attempts: int):
    now = time.time()
    with _lock:
        row = _conn.execute("SELECT attempts FROM bursts WHERE id = ?", (burst_id,)).fetchone()
        attempts = (row["attempts"] if row else 0) + 1
        status = "pending" if attempts < max_attempts else "failed"
        _conn.execute(
            "UPDATE bursts SET status = ?, attempts = ?, error = ?, publish_after = ?,"
            " updated_at = ? WHERE id = ?",
            (status, attempts, error[:1000], retry_after, now, burst_id),
        )
        _conn.commit()


def requeue_stuck(older_than_seconds: int = 900):
    """Возвращает в очередь пачки, зависшие в processing после рестарта."""
    cutoff = time.time() - older_than_seconds
    with _lock:
        _conn.execute(
            "UPDATE bursts SET status = 'pending' WHERE status = 'processing'"
            " AND updated_at < ?",
            (cutoff,),
        )
        _conn.commit()


def stats() -> dict:
    with _lock:
        rows = _conn.execute(
            "SELECT status, COUNT(*) AS n FROM bursts GROUP BY status"
        ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def recent_bursts(limit: int = 20) -> list:
    with _lock:
        rows = _conn.execute(
            "SELECT id, status, attempts, error, candidates, created_at FROM bursts"
            " ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        cands = json.loads(d.pop("candidates") or "[]")
        d["variants"] = len(cands)
        d["preview"] = (cands[0].get("text", "")[:80] if cands else "")
        out.append(d)
    return out


# --- Медиа ---

def register_media(path: str, kind: str, mime: str) -> str:
    key = uuid.uuid4().hex
    with _lock:
        _conn.execute(
            "INSERT INTO media (key, path, kind, mime, created_at) VALUES (?, ?, ?, ?, ?)",
            (key, path, kind, mime, time.time()),
        )
        _conn.commit()
    return key


def get_media(key: str):
    with _lock:
        row = _conn.execute("SELECT * FROM media WHERE key = ?", (key,)).fetchone()
    return dict(row) if row else None


def old_media(older_than_seconds: int) -> list:
    cutoff = time.time() - older_than_seconds
    with _lock:
        rows = _conn.execute(
            "SELECT * FROM media WHERE created_at < ?", (cutoff,)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_media(key: str):
    with _lock:
        _conn.execute("DELETE FROM media WHERE key = ?", (key,))
        _conn.commit()


# --- Состояние ---

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
