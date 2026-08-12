"""Фоновый воркер: публикует созревшие пачки, делает ретраи, продлевает токен."""

import json
import logging
import os
import re
import threading
import time

import db
import post_filter
import selector
import telegram_source
import threads_api
from config import (
    ALLOW_EMPTY_TEXT,
    MAX_ATTEMPTS,
    STRIP_HASHTAGS,
    WORKER_INTERVAL_SECONDS,
)

log = logging.getLogger("worker")

_stop = threading.Event()

TOKEN_CHECK_INTERVAL = 12 * 3600
MEDIA_TTL_SECONDS = 3 * 24 * 3600
_last_token_check = 0.0
_last_cleanup = 0.0


def _backoff(attempts: int) -> float:
    return time.time() + min(60 * (2 ** attempts), 3600)


def _clean_text(text: str) -> str:
    text = post_filter.strip_phrase(text)
    if STRIP_HASHTAGS:
        text = re.sub(r"(?m)^\s*#\S+(\s+#\S+)*\s*$", "", text)
        text = re.sub(r"\s+#\S+", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _process_burst(burst: dict):
    candidates = json.loads(burst["candidates"] or "[]")
    chosen = selector.choose(candidates)

    # Пустой результат = в пачке не нашлось текста с фразой-маркером
    # (например, прилетели только картинки или служебные сообщения).
    if not chosen:
        log.info("Пачка %s без подходящего текста — пропускаю", burst["id"][:8])
        db.mark_skipped(burst["id"], "нет текста с фразой-маркером")
        return

    text = _clean_text(chosen.get("text", ""))
    media = [
        {"kind": m["kind"], "url": telegram_source.media_public_url(m["key"])}
        for m in chosen.get("media", [])
    ]

    if not text and not media:
        db.mark_skipped(burst["id"], "после обработки не осталось контента")
        return
    if not text and not ALLOW_EMPTY_TEXT:
        db.mark_skipped(burst["id"], "пост без текста")
        return

    log.info("Публикую пачку %s (msg %s, медиа %d)",
             burst["id"][:8], chosen.get("message_id"), len(media))

    threads_ids = threads_api.publish(text, media)
    db.mark_posted(burst["id"], threads_ids)
    log.info("Опубликовано: %s", threads_ids)


def _cleanup_media():
    """Удаляет скачанные файлы старше TTL, чтобы Volume не разрастался."""
    for entry in db.old_media(MEDIA_TTL_SECONDS):
        try:
            if os.path.exists(entry["path"]):
                os.remove(entry["path"])
        except Exception as e:
            log.warning("Не удалось удалить %s: %s", entry["path"], e)
        db.delete_media(entry["key"])


def _tick():
    global _last_token_check, _last_cleanup

    db.requeue_stuck()

    for burst in db.claim_ready_bursts():
        try:
            _process_burst(burst)
        except Exception as e:
            attempts = burst["attempts"] + 1
            log.error("Ошибка публикации %s (попытка %d): %s",
                      burst["id"][:8], attempts, e)
            db.mark_retry(burst["id"], str(e), _backoff(burst["attempts"]), MAX_ATTEMPTS)

    now = time.time()

    if now - _last_token_check > TOKEN_CHECK_INTERVAL:
        _last_token_check = now
        try:
            threads_api.refresh_token_if_needed()
        except Exception as e:
            log.warning("Проверка токена не удалась: %s", e)

    if now - _last_cleanup > 6 * 3600:
        _last_cleanup = now
        _cleanup_media()


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
