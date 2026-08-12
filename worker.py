"""Фоновый воркер: разгребает очередь постов, делает ретраи, продлевает токен."""

import json
import logging
import threading
import time

import db
import telegram
import threads_api
from config import MAX_ATTEMPTS, WORKER_INTERVAL_SECONDS

log = logging.getLogger("worker")

_stop = threading.Event()

TOKEN_CHECK_INTERVAL = 12 * 3600
_last_token_check = 0.0


def _backoff(attempts: int) -> float:
    """Экспоненциальная задержка: 1, 2, 4, 8, 16 минут."""
    return time.time() + min(60 * (2 ** attempts), 3600)


def _process_post(post: dict):
    media_entries = json.loads(post["media"] or "[]")
    media = [
        {"kind": m["kind"], "url": telegram.media_public_url(m["key"])}
        for m in media_entries
    ]

    log.info("Публикую пост %s (msg %s, медиа: %d)",
             post["id"], post["message_id"], len(media))

    threads_ids = threads_api.publish(post["text"], media)
    db.mark_posted(post["id"], threads_ids)
    log.info("Опубликовано: %s", threads_ids)


def _tick():
    global _last_token_check

    db.requeue_stuck()

    for post in db.claim_ready_posts():
        try:
            _process_post(post)
        except Exception as e:
            attempts = post["attempts"] + 1
            log.error("Ошибка публикации %s (попытка %d): %s", post["id"], attempts, e)
            db.mark_retry(post["id"], str(e), _backoff(post["attempts"]), MAX_ATTEMPTS)

    if time.time() - _last_token_check > TOKEN_CHECK_INTERVAL:
        _last_token_check = time.time()
        try:
            threads_api.refresh_token_if_needed()
        except Exception as e:
            log.warning("Проверка токена не удалась: %s", e)


def _loop():
    log.info("Воркер запущен, интервал %d сек", WORKER_INTERVAL_SECONDS)
    while not _stop.is_set():
        try:
            _tick()
        except Exception as e:
            log.exception("Сбой в цикле воркера: %s", e)
        _stop.wait(WORKER_INTERVAL_SECONDS)


def start():
    threading.Thread(target=_loop, daemon=True, name="worker").start()


def stop():
    _stop.set()
