"""
Webhook-приёмник постов из Telegram-канала.
Бот должен быть добавлен в канал админом.

Деплой: Railway, порт из $PORT.
Регистрация вебхука (один раз, после деплоя):
    curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<your-app>.up.railway.app/telegram-webhook"
"""

import os
import time
import requests
from fastapi import FastAPI, Request

app = FastAPI()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
AIRTABLE_API_KEY = os.environ["AIRTABLE_API_KEY"]
AIRTABLE_BASE_ID = os.environ["AIRTABLE_BASE_ID"]
AIRTABLE_TABLE_NAME = os.environ.get("AIRTABLE_TABLE_NAME", "ThreadsQueue")

TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
AIRTABLE_URL = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
AIRTABLE_HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    "Content-Type": "application/json",
}


def get_file_url(file_id: str) -> str:
    """Получает публичную ссылку на файл через Telegram Bot API."""
    r = requests.get(f"{TG_API}/getFile", params={"file_id": file_id}, timeout=15)
    r.raise_for_status()
    file_path = r.json()["result"]["file_path"]
    return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"


def extract_media_urls(post: dict) -> list:
    """Достаёт ссылки на медиа из поста. Airtable сам скачает их по URL и сохранит постоянно."""
    urls = []
    if "photo" in post:
        largest = post["photo"][-1]  # последний элемент = самое большое разрешение
        urls.append(get_file_url(largest["file_id"]))
    if "video" in post:
        urls.append(get_file_url(post["video"]["file_id"]))
    if "document" in post:
        urls.append(get_file_url(post["document"]["file_id"]))
    return urls


@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    update = await request.json()
    post = update.get("channel_post")

    if not post:
        return {"ok": True}  # игнорируем всё кроме постов канала (edited_channel_post и т.п.)

    text = post.get("text") or post.get("caption") or ""
    media_urls = extract_media_urls(post)

    record = {
        "fields": {
            "tg_message_id": post["message_id"],
            "text": text,
            "status": "new",
            "created_at": int(time.time()),
        }
    }
    if media_urls:
        record["fields"]["media"] = [{"url": u} for u in media_urls]

    r = requests.post(AIRTABLE_URL, headers=AIRTABLE_HEADERS, json=record, timeout=15)
    r.raise_for_status()

    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "ok"}
