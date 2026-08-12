"""Конфигурация из переменных окружения."""

import os


def _req(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"Не задана обязательная переменная окружения: {name}")
    return v


def _opt(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# --- Telegram (юзер-сессия, не бот) ---
# Бот не видит сообщения других ботов, поэтому читаем группу обычным аккаунтом.
# api_id / api_hash берутся на https://my.telegram.org -> API development tools
TELEGRAM_API_ID = int(_req("TELEGRAM_API_ID"))
TELEGRAM_API_HASH = _req("TELEGRAM_API_HASH")
# Строка сессии, получается один раз локально через gen_session.py
TELEGRAM_STRING_SESSION = _req("TELEGRAM_STRING_SESSION")
# ID группы-источника, например -1001234567890
SOURCE_CHAT_ID = int(_req("SOURCE_CHAT_ID"))

# --- Threads ---
THREADS_ACCESS_TOKEN = _req("THREADS_ACCESS_TOKEN")
THREADS_USER_ID = _req("THREADS_USER_ID")

# --- Сервис ---
# Публичный адрес на Railway без слэша в конце - по нему Threads качает медиа.
PUBLIC_BASE_URL = _req("PUBLIC_BASE_URL").rstrip("/")

# Каталог Railway Volume. Тут лежат и база, и скачанные медиафайлы.
DATA_DIR = _opt("DATA_DIR", "/data")
DB_PATH = _opt("DB_PATH", os.path.join(DATA_DIR, "app.db"))
MEDIA_DIR = _opt("MEDIA_DIR", os.path.join(DATA_DIR, "media"))

# --- Фильтр постов ---
# Публиковать только посты с этой фразой. Пусто = все.
# Несколько вариантов через | (сработает любой).
POST_FILTER_PHRASE = _opt("POST_FILTER_PHRASE", "")
# Вырезать фразу-маркер из текста перед публикацией.
STRIP_FILTER_PHRASE = _opt("STRIP_FILTER_PHRASE", "false").lower() == "true"

# --- Схлопывание дублей ---
# Один матч приходит несколькими вариантами подряд (instagram, x, длинный).
# Сообщения, пришедшие в пределах этого окна, считаются одной пачкой.
BURST_WINDOW_SECONDS = int(_opt("BURST_WINDOW_SECONDS", "180"))
# Сколько ждать после последнего сообщения пачки, прежде чем публиковать.
BURST_WAIT_SECONDS = int(_opt("BURST_WAIT_SECONDS", "45"))
# Какой вариант из пачки публиковать: longest | first | last
SELECT_STRATEGY = _opt("SELECT_STRATEGY", "longest").lower()

# --- Прочее ---
WORKER_INTERVAL_SECONDS = int(_opt("WORKER_INTERVAL_SECONDS", "10"))
MAX_ATTEMPTS = int(_opt("MAX_ATTEMPTS", "5"))
ALLOW_EMPTY_TEXT = _opt("ALLOW_EMPTY_TEXT", "true").lower() == "true"
# Убирать хештеги из текста перед публикацией в Threads.
STRIP_HASHTAGS = _opt("STRIP_HASHTAGS", "false").lower() == "true"

# --- Константы Threads API ---
THREADS_TEXT_LIMIT = 500
THREADS_GRAPH = "https://graph.threads.net/v1.0"
