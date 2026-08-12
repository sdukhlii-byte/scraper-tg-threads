"""
Воркер публикации: забирает записи status=new из Airtable и постит их в Threads.
Длинные посты (>500 симв.) делятся на несколько частей по границам предложений/абзацев
(без LLM) и публикуются как связанный тред через reply_to_id.

Деплой: Railway, отдельный сервис (worker), без публичного порта, крутится в фоне.
"""

import os
import time
import requests

AIRTABLE_API_KEY = os.environ["AIRTABLE_API_KEY"]
AIRTABLE_BASE_ID = os.environ["AIRTABLE_BASE_ID"]
AIRTABLE_TABLE_NAME = os.environ.get("AIRTABLE_TABLE_NAME", "ThreadsQueue")

THREADS_ACCESS_TOKEN = os.environ["THREADS_ACCESS_TOKEN"]
THREADS_USER_ID = os.environ["THREADS_USER_ID"]

AIRTABLE_URL = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
AIRTABLE_HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    "Content-Type": "application/json",
}

THREADS_CONTAINER_API = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
THREADS_PUBLISH_API = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"

TEXT_LIMIT = 500
POLL_INTERVAL = 120  # секунд между проходами воркера


def fetch_new_records() -> list:
    params = {"filterByFormula": "{status}='new'"}
    r = requests.get(AIRTABLE_URL, headers=AIRTABLE_HEADERS, params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("records", [])


def update_status(record_id: str, status: str, extra_fields: dict = None):
    fields = {"status": status}
    if extra_fields:
        fields.update(extra_fields)
    r = requests.patch(
        f"{AIRTABLE_URL}/{record_id}",
        headers=AIRTABLE_HEADERS,
        json={"fields": fields},
        timeout=15,
    )
    r.raise_for_status()


def split_text(text: str, limit: int = TEXT_LIMIT) -> list:
    """Делит текст на части по границе абзацев/предложений, без LLM и без потери смысла."""
    text = text.strip()
    if len(text) <= limit:
        return [text]

    reserve = 8  # место под суффикс " (1/2)"
    hard_limit = limit - reserve

    parts = []
    remaining = text

    while len(remaining) > hard_limit:
        window = remaining[:hard_limit]
        split_at = max(
            window.rfind("\n\n"),
            window.rfind(". "),
            window.rfind("! "),
            window.rfind("? "),
            window.rfind(" "),
        )
        if split_at <= 0:
            split_at = hard_limit  # жёсткий разрыв, если разрывать нечем

        parts.append(remaining[: split_at + 1].strip())
        remaining = remaining[split_at + 1:].strip()

    if remaining:
        parts.append(remaining)

    total = len(parts)
    if total > 1:
        parts = [f"{p} ({i + 1}/{total})" for i, p in enumerate(parts)]

    return parts


def create_container(text: str, media_url: str = None, reply_to_id: str = None) -> str:
    payload = {
        "media_type": "IMAGE" if media_url else "TEXT",
        "text": text,
        "access_token": THREADS_ACCESS_TOKEN,
    }
    if media_url:
        payload["image_url"] = media_url
    if reply_to_id:
        payload["reply_to_id"] = reply_to_id

    r = requests.post(THREADS_CONTAINER_API, data=payload, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def publish_container(creation_id: str) -> str:
    payload = {"creation_id": creation_id, "access_token": THREADS_ACCESS_TOKEN}
    r = requests.post(THREADS_PUBLISH_API, data=payload, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def post_thread(text: str, media_urls: list) -> list:
    """Публикует пост, при необходимости разбивая на несколько связанных постов (тред)."""
    chunks = split_text(text)
    first_media = media_urls[0] if media_urls else None

    published_ids = []
    reply_to = None

    for i, chunk in enumerate(chunks):
        media = first_media if i == 0 else None  # медиа только в первом посте треда
        creation_id = create_container(chunk, media, reply_to)
        time.sleep(3)  # Threads требует паузу между созданием контейнера и публикацией
        post_id = publish_container(creation_id)
        published_ids.append(post_id)
        reply_to = post_id  # следующий пост — реплай к предыдущему
        time.sleep(2)

    return published_ids


def process_once():
    for record in fetch_new_records():
        record_id = record["id"]
        fields = record["fields"]
        text = fields.get("text", "")
        media_urls = [m["url"] for m in fields.get("media", [])]

        if not text and not media_urls:
            update_status(record_id, "error", {"error": "empty post"})
            continue

        try:
            post_ids = post_thread(text, media_urls)
            update_status(record_id, "posted", {"threads_post_ids": ",".join(post_ids)})
        except Exception as e:
            update_status(record_id, "error", {"error": str(e)[:500]})


if __name__ == "__main__":
    while True:
        process_once()
        time.sleep(POLL_INTERVAL)
