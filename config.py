"""Конфигурация из переменных окружения."""

import os


def _req(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"Не задана обязательная переменная окружения: {name}")
    return v


def _opt(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# --- Telegram ---
TELEGRAM_BOT_TOKEN = _req("TELEGRAM_BOT_TOKEN")
# Секрет для проверки, что вебхук дёргает именно Telegram, а не посторонний.
# Произвольная строка, придумай сам (32+ символов).
TELEGRAM_WEBHOOK_SECRET = _req("TELEGRAM_WEBHOOK_SECRET")
# ID канала-источника (например -1001234567890). Посты из других чатов игнорируются.
ALLOWED_CHANNEL_ID = int(_req("ALLOWED_CHANNEL_ID"))

# --- Threads ---
THREADS_ACCESS_TOKEN = _req("THREADS_ACCESS_TOKEN")
THREADS_USER_ID = _req("THREADS_USER_ID")

# --- Сервис ---
# Публичный адрес сервиса на Railway, БЕЗ слэша в конце.
# Нужен и для регистрации вебхука, и для отдачи медиа в Threads.
PUBLIC_BASE_URL = _req("PUBLIC_BASE_URL").rstrip("/")

# Путь к SQLite. На Railway подключи Volume и укажи путь внутри него,
# иначе база будет теряться при каждом редеплое.
DB_PATH = _opt("DB_PATH", "/data/app.db")

# Сколько секунд ждать остальные части альбома перед публикацией.
ALBUM_WAIT_SECONDS = int(_opt("ALBUM_WAIT_SECONDS", "6"))

# Интервал фонового воркера.
WORKER_INTERVAL_SECONDS = int(_opt("WORKER_INTERVAL_SECONDS", "10"))

# Максимум попыток публикации одного поста.
MAX_ATTEMPTS = int(_opt("MAX_ATTEMPTS", "5"))

# Публиковать посты без текста (только медиа).
ALLOW_EMPTY_TEXT = _opt("ALLOW_EMPTY_TEXT", "true").lower() == "true"

# Автоматически регистрировать вебхук в Telegram при старте.
AUTO_SET_WEBHOOK = _opt("AUTO_SET_WEBHOOK", "true").lower() == "true"

# --- Константы Threads API ---
THREADS_TEXT_LIMIT = 500
THREADS_GRAPH = "https://graph.threads.net/v1.0"
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
TELEGRAM_FILE_API = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"
