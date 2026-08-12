# TG → Threads автопостинг

## Структура
- `telegram_webhook.py` — FastAPI-сервис, ловит посты канала, кладёт в Airtable
- `threads_worker.py` — воркер, публикует из Airtable в Threads (крутится в фоне)
- Деплоятся на Railway как **два отдельных сервиса** из одного репо (разные start command)

## Airtable — структура таблицы `ThreadsQueue`
| Поле | Тип |
|---|---|
| tg_message_id | Number |
| text | Long text |
| media | Attachment |
| status | Single select: new / posted / error |
| threads_post_ids | Single line text |
| error | Long text |
| created_at | Number |

## Переменные окружения

### webhook-сервис
- `TELEGRAM_BOT_TOKEN`
- `AIRTABLE_API_KEY`
- `AIRTABLE_BASE_ID`
- `AIRTABLE_TABLE_NAME` (по умолчанию `ThreadsQueue`)

### worker-сервис
- `AIRTABLE_API_KEY`
- `AIRTABLE_BASE_ID`
- `AIRTABLE_TABLE_NAME`
- `THREADS_ACCESS_TOKEN` — long-lived token из Meta app
- `THREADS_USER_ID` — Threads user id (Business-аккаунт)

## Запуск
```bash
# webhook
uvicorn telegram_webhook:app --host 0.0.0.0 --port $PORT

# worker
python threads_worker.py
```

## Регистрация вебхука у Telegram (один раз после деплоя)
```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<railway-app>.up.railway.app/telegram-webhook"
```

## Получение THREADS_ACCESS_TOKEN и THREADS_USER_ID
1. Создать app на developers.facebook.com, продукт "Threads API"
2. Заполнить URL политики конфиденциальности (Настройки приложения → Основное)
3. Роли в приложении → добавить свой Threads-аккаунт как **Тестировщик Threads**,
   подтвердить приглашение в приложении Threads (профиль → "Разрешения сайта")
4. Сценарии использования → "Доступ к Threads API" → **User Token Generator** →
   выбрать аккаунт → сгенерировать токен (права `threads_basic`, `threads_content_publish`)

⚠️ Токен из User Token Generator **уже long-lived (~60 дней)**.
Обменивать его через `grant_type=th_exchange_token` НЕ нужно — этот грант
предназначен только для short-lived токенов из полноценного OAuth-флоу
(redirect → code → token) и вернёт ошибку "Session key invalid".

Проверка токена и получение USER_ID:
```bash
curl "https://graph.threads.net/v1.0/me?fields=id,username&access_token=<TOKEN>"
```

Проверка срока жизни:
```bash
curl -G "https://graph.threads.net/v1.0/debug_token" \
  --data-urlencode "input_token=<TOKEN>" \
  --data-urlencode "access_token=<TOKEN>"
```

## Продление токена (раз в ~60 дней)
Работает только с long-lived токеном старше 24 часов:
```bash
curl -G "https://graph.threads.net/refresh_access_token" \
  --data-urlencode "grant_type=th_refresh_token" \
  --data-urlencode "access_token=<TOKEN>"
```

## Логика разбивки длинных постов
Если текст длиннее 500 символов — режется по границе абзаца/предложения (без LLM),
части нумеруются `(1/2)`, `(2/2)` и публикуются как связанный тред через `reply_to_id`.
Медиа прикрепляется только к первому посту треда.
