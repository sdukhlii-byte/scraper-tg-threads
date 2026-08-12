# TG-канал → Threads: автопостинг

Один сервис на Railway. Пост появляется в канале → через несколько секунд он в Threads.

## Как работает

```
Telegram канал (бот-админ)
      │ webhook (push, мгновенно)
      ▼
FastAPI ──► SQLite (дедуп, склейка альбомов, очередь)
                │
        фоновый воркер (каждые 10 сек)
                │
        Threads API ──► качает медиа с /media/{key} этого же сервиса
```

Крон не нужен: посты прилетают вебхуком сразу. Воркер крутится внутри процесса и
занимается только ретраями, склейкой альбомов и продлением токена.

Внешняя база (Airtable и т.п.) не нужна: SQLite внутри сервиса закрывает
дедупликацию, очередь и историю.

## Что умеет

- Текст, фото, видео, GIF, изображения-документы
- **Альбомы** → карусель в Threads (Telegram шлёт их отдельными апдейтами, сервис склеивает)
- **Длинные посты** → связанный тред с нумерацией `(1/2)`, режется по границе предложения
- Дедупликация по `message_id` (Telegram умеет повторять доставку)
- Ретраи с экспоненциальной задержкой, до `MAX_ATTEMPTS`
- Автопродление токена Threads до истечения 60 дней
- Проверка секрета вебхука и фильтр по ID канала

## Переменные окружения

### Обязательные
| Переменная | Что это |
|---|---|
| `TELEGRAM_BOT_TOKEN` | токен бота от @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | произвольная строка, `openssl rand -hex 32` |
| `ALLOWED_CHANNEL_ID` | ID канала-источника, например `-1001234567890` |
| `THREADS_ACCESS_TOKEN` | токен из User Token Generator |
| `THREADS_USER_ID` | id аккаунта Threads |
| `PUBLIC_BASE_URL` | публичный домен Railway, без слэша в конце |

### Необязательные
| Переменная | По умолчанию | Что делает |
|---|---|---|
| `DB_PATH` | `/data/app.db` | путь к SQLite (см. Volume ниже) |
| `ALBUM_WAIT_SECONDS` | `6` | сколько ждать остальные части альбома |
| `WORKER_INTERVAL_SECONDS` | `10` | интервал фонового воркера |
| `MAX_ATTEMPTS` | `5` | попыток публикации до статуса `failed` |
| `ALLOW_EMPTY_TEXT` | `true` | публиковать посты без текста |
| `AUTO_SET_WEBHOOK` | `true` | регистрировать вебхук при старте |

## Деплой на Railway

1. Залить репозиторий, создать сервис из GitHub.
2. **Подключить Volume** и примонтировать в `/data`. Без него SQLite стирается
   при каждом редеплое — вернутся уже опубликованные посты.
3. Прописать переменные окружения.
4. Включить публичный домен (Settings → Networking → Generate Domain) и положить
   его в `PUBLIC_BASE_URL`.
5. Задеплоить. Вебхук зарегистрируется сам при старте.

Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Как узнать ALLOWED_CHANNEL_ID
Добавь бота админом в канал, опубликуй любой пост и посмотри логи сервиса —
там будет `Пост из чужого чата <id>`. Либо перешли пост в @userinfobot.

## Эндпоинты

| Путь | Назначение |
|---|---|
| `POST /telegram/webhook` | приём постов, требует заголовок с секретом |
| `GET /media/{key}` | отдача медиа для Threads |
| `GET /health` | healthcheck |
| `GET /status` | очередь и последние 20 постов с ошибками |

## Токен Threads

Токен из User Token Generator в Meta Developer **уже long-lived (~60 дней)**.
Обменивать его через `grant_type=th_exchange_token` не нужно — этот грант
работает только с short-lived токенами из полноценного OAuth-флоу
(redirect → code → token) и вернёт `Session key invalid`.

Проверить токен и узнать `THREADS_USER_ID`:
```bash
curl "https://graph.threads.net/v1.0/me?fields=id,username&access_token=<TOKEN>"
```

Сервис сам продлевает токен, когда до истечения остаётся меньше 10 дней.
Вручную это делается так:
```bash
curl -G "https://graph.threads.net/refresh_access_token" \
  --data-urlencode "grant_type=th_refresh_token" \
  --data-urlencode "access_token=<TOKEN>"
```

## Ограничения Threads API

- 500 символов на пост (длиннее — режется в тред)
- ~250 публикаций в сутки
- до 20 элементов в карусели
- медиа скачивается Threads по URL, поэтому сервис должен быть публично доступен

## Локальный запуск

```bash
pip install -r requirements.txt
cp .env.example .env   # заполнить
export $(grep -v '^#' .env | xargs)
uvicorn main:app --reload
```

Для локального теста вебхука нужен туннель (ngrok/cloudflared) и его адрес
в `PUBLIC_BASE_URL`.
