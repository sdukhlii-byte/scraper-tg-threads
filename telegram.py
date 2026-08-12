"""Взаимодействие с Telegram Bot API."""

import logging

import requests

from config import (
    PUBLIC_BASE_URL,
    TELEGRAM_API,
    TELEGRAM_FILE_API,
    TELEGRAM_WEBHOOK_SECRET,
)

log = logging.getLogger("telegram")


def set_webhook() -> bool:
    """Регистрирует вебхук. Вызывается при старте сервиса."""
    url = f"{PUBLIC_BASE_URL}/telegram/webhook"
    try:
        r = requests.post(
            f"{TELEGRAM_API}/setWebhook",
            data={
                "url": url,
                "secret_token": TELEGRAM_WEBHOOK_SECRET,
                "allowed_updates": '["channel_post"]',
                "drop_pending_updates": "false",
            },
            timeout=30,
        )
        ok = r.ok and r.json().get("ok")
        log.info("setWebhook %s -> %s", url, r.text[:200])
        return bool(ok)
    except Exception as e:
        log.error("Не удалось зарегистрировать вебхук: %s", e)
        return False


def get_file_path(file_id: str) -> str:
    r = requests.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id}, timeout=30)
    r.raise_for_status()
    return r.json()["result"]["file_path"]


def stream_file(file_id: str):
    """Возвращает (iterator, content_type) для проксирования файла наружу."""
    file_path = get_file_path(file_id)
    r = requests.get(f"{TELEGRAM_FILE_API}/{file_path}", stream=True, timeout=120)
    r.raise_for_status()
    content_type = r.headers.get("Content-Type", "application/octet-stream")
    return r.iter_content(chunk_size=64 * 1024), content_type


def extract_media(post: dict) -> list:
    """
    Достаёт медиа из поста канала в виде [{"kind": ..., "file_id": ...}].
    Стикеры, голосовые и кружки пропускаются — Threads их не принимает.
    """
    media = []

    if "photo" in post:
        # Последний элемент — максимальное разрешение.
        media.append({"kind": "image", "file_id": post["photo"][-1]["file_id"]})

    if "video" in post:
        media.append({"kind": "video", "file_id": post["video"]["file_id"]})

    if "animation" in post:
        media.append({"kind": "video", "file_id": post["animation"]["file_id"]})

    doc = post.get("document")
    if doc:
        mime = doc.get("mime_type", "")
        if mime.startswith("image/"):
            media.append({"kind": "image", "file_id": doc["file_id"]})
        elif mime.startswith("video/"):
            media.append({"kind": "video", "file_id": doc["file_id"]})

    return media


def extract_text(post: dict) -> str:
    return (post.get("text") or post.get("caption") or "").strip()


def media_public_url(key: str) -> str:
    return f"{PUBLIC_BASE_URL}/media/{key}"
