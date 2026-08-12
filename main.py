"""
TG-канал → Threads: автопостинг.

Один сервис:
  - принимает channel_post по вебхуку,
  - складывает в SQLite (дедупликация, склейка альбомов, ретраи),
  - фоновый воркер публикует в Threads,
  - отдаёт медиа наружу по временной публичной ссылке (Threads качает сам).
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

import db
import telegram
import threads_api
import worker
from config import (
    ALBUM_WAIT_SECONDS,
    ALLOW_EMPTY_TEXT,
    ALLOWED_CHANNEL_ID,
    AUTO_SET_WEBHOOK,
    TELEGRAM_WEBHOOK_SECRET,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    log.info("База готова: %s", db.DB_PATH if hasattr(db, "DB_PATH") else "")

    try:
        me = threads_api.whoami()
        log.info("Threads-аккаунт: %s (id %s)", me.get("username"), me.get("id"))
    except Exception as e:
        log.error("Не удалось проверить токен Threads: %s", e)

    if AUTO_SET_WEBHOOK:
        telegram.set_webhook()

    worker.start()
    yield
    worker.stop()


app = FastAPI(title="TG → Threads autopost", lifespan=lifespan)


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    if x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Неверный секрет вебхука")

    update = await request.json()
    post = update.get("channel_post")
    if not post:
        return {"ok": True}

    chat_id = post.get("chat", {}).get("id")
    if chat_id != ALLOWED_CHANNEL_ID:
        log.warning("Пост из чужого чата %s — игнорирую", chat_id)
        return {"ok": True}

    text = telegram.extract_text(post)
    raw_media = telegram.extract_media(post)

    if not text and not raw_media:
        return {"ok": True}
    if not text and not ALLOW_EMPTY_TEXT:
        return {"ok": True}

    # Регистрируем медиа, чтобы отдать Threads ссылку без токена бота внутри.
    media = [
        {"kind": m["kind"], "key": db.register_media(m["file_id"], m["kind"])}
        for m in raw_media
    ]

    media_group_id = post.get("media_group_id")
    # Альбом приходит несколькими апдейтами — ждём, пока долетят остальные части.
    publish_after = time.time() + (ALBUM_WAIT_SECONDS if media_group_id else 0)

    post_id = db.upsert_post(
        chat_id=chat_id,
        message_id=post["message_id"],
        media_group_id=media_group_id,
        text=text,
        media=media,
        publish_after=publish_after,
    )

    log.info("Принят пост msg=%s id=%s медиа=%d", post["message_id"], post_id, len(media))
    return {"ok": True}


@app.get("/media/{key}")
def media(key: str):
    """Публичная ссылка на файл — по ней Threads забирает медиа."""
    entry = db.get_media(key)
    if not entry:
        raise HTTPException(status_code=404, detail="Не найдено")

    try:
        stream, content_type = telegram.stream_file(entry["file_id"])
    except Exception as e:
        log.error("Не удалось отдать медиа %s: %s", key, e)
        raise HTTPException(status_code=502, detail="Файл недоступен")

    return StreamingResponse(stream, media_type=content_type)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status():
    return {"queue": db.stats(), "recent": db.recent_posts(20)}
