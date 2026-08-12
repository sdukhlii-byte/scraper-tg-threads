"""Чтение группы через юзер-сессию Telethon.

Бот не получает сообщения других ботов — это ограничение Bot API, которое
не обходится правами админа. Поэтому источник читается обычным аккаунтом.
"""

import asyncio
import logging
import mimetypes
import os
import uuid

from telethon import TelegramClient, events
from telethon.sessions import StringSession

import db
import post_filter
from config import (
    BURST_WAIT_SECONDS,
    BURST_WINDOW_SECONDS,
    MEDIA_DIR,
    PUBLIC_BASE_URL,
    SOURCE_CHAT_ID,
    TELEGRAM_API_HASH,
    TELEGRAM_API_ID,
    TELEGRAM_STRING_SESSION,
)

log = logging.getLogger("source")

_client = None


def media_public_url(key: str) -> str:
    return f"{PUBLIC_BASE_URL}/media/{key}"


def _kind_of(message) -> str:
    """Определяет, годится ли вложение для Threads и чем оно является."""
    if message.photo:
        return "image"
    if message.video or message.gif or message.video_note:
        return "video"

    doc = getattr(message, "document", None)
    if doc:
        mime = getattr(doc, "mime_type", "") or ""
        if mime.startswith("image/"):
            return "image"
        if mime.startswith("video/"):
            return "video"
    return ""


async def _save_media(message) -> list:
    """Скачивает вложение в MEDIA_DIR и регистрирует его для раздачи наружу."""
    kind = _kind_of(message)
    if not kind:
        return []

    os.makedirs(MEDIA_DIR, exist_ok=True)
    base = os.path.join(MEDIA_DIR, uuid.uuid4().hex)

    try:
        path = await message.download_media(file=base)
    except Exception as e:
        log.error("Не удалось скачать медиа из msg %s: %s", message.id, e)
        return []

    if not path:
        return []

    mime = mimetypes.guess_type(path)[0] or (
        "image/jpeg" if kind == "image" else "video/mp4"
    )
    key = db.register_media(path, kind, mime)
    log.info("Сохранено медиа %s (%s)", os.path.basename(path), kind)
    return [{"kind": kind, "key": key}]


async def _handle(event):
    message = event.message
    chat_id = event.chat_id

    if chat_id != SOURCE_CHAT_ID:
        return

    if not db.mark_seen(chat_id, message.id):
        return

    text = (message.text or message.message or "").strip()
    media = await _save_media(message)

    if not text and not media:
        return

    # Отсекаем посты без фразы-маркера. У альбома подпись есть только у одной
    # части, поэтому части альбома пропускаем дальше — решение примет воркер.
    grouped_id = getattr(message, "grouped_id", None)
    if not grouped_id and not post_filter.matches(text):
        log.info("msg %s без фразы-маркера — пропускаю", message.id)
        return

    candidate = {
        "message_id": message.id,
        "text": text,
        "media": media,
        "grouped_id": grouped_id,
    }

    burst_id = db.add_candidate(
        chat_id=chat_id,
        candidate=candidate,
        burst_window=BURST_WINDOW_SECONDS,
        burst_wait=BURST_WAIT_SECONDS,
        grouped_id=grouped_id,
    )
    log.info("msg %s -> пачка %s (текст %d симв., медиа %d)",
             message.id, burst_id[:8], len(text), len(media))


async def start():
    """Запускает клиент и вешает обработчик новых сообщений."""
    global _client

    _client = TelegramClient(
        StringSession(TELEGRAM_STRING_SESSION),
        TELEGRAM_API_ID,
        TELEGRAM_API_HASH,
    )
    _client.add_event_handler(_handle, events.NewMessage(chats=SOURCE_CHAT_ID))

    await _client.start()
    me = await _client.get_me()
    log.info("Подключён как %s (id %s)", me.username or me.first_name, me.id)

    try:
        entity = await _client.get_entity(SOURCE_CHAT_ID)
        log.info("Слушаю источник: %s", getattr(entity, "title", SOURCE_CHAT_ID))
    except Exception as e:
        log.error("Не удалось получить чат %s: %s", SOURCE_CHAT_ID, e)

    asyncio.create_task(_client.run_until_disconnected())


async def stop():
    if _client:
        await _client.disconnect()


async def list_dialogs():
    """Вспомогательное: показать доступные чаты с их id."""
    out = []
    async for dialog in _client.iter_dialogs():
        out.append({"id": dialog.id, "title": dialog.name})
    return out
