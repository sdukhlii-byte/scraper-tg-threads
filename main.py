"""
Telegram-группа → Threads: автопостинг.

Источник читается юзер-сессией Telethon (бот не видит сообщения других ботов).
Варианты одного материала схлопываются в один пост.
Медиа раздаётся наружу, потому что Threads скачивает его по URL сам.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

import db
import post_filter
import telegram_source
import threads_api
import worker
from config import POST_FILTER_PHRASE, SELECT_STRATEGY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()

    try:
        me = threads_api.whoami()
        log.info("Threads-аккаунт: %s (id %s)", me.get("username"), me.get("id"))
    except Exception as e:
        log.error("Не удалось проверить токен Threads: %s", e)

    if post_filter.ENABLED:
        log.info("Фильтр: публикуются только посты с %r", POST_FILTER_PHRASE)
    else:
        log.info("Фильтр выключен: публикуются все посты")
    log.info("Стратегия выбора из пачки: %s", SELECT_STRATEGY)

    await telegram_source.start()
    worker.start()
    yield
    worker.stop()
    await telegram_source.stop()


app = FastAPI(title="TG → Threads autopost", lifespan=lifespan)


@app.get("/media/{key}")
def media(key: str):
    """Публичная ссылка на файл — по ней Threads забирает медиа."""
    entry = db.get_media(key)
    if not entry:
        raise HTTPException(status_code=404, detail="Не найдено")
    return FileResponse(entry["path"], media_type=entry["mime"])


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status():
    return {"queue": db.stats(), "recent": db.recent_bursts(20)}


@app.get("/dialogs")
async def dialogs():
    """Список доступных чатов с их id — чтобы найти SOURCE_CHAT_ID."""
    try:
        return {"dialogs": await telegram_source.list_dialogs()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
