"""
Одноразовый скрипт: получить TELEGRAM_STRING_SESSION.

Запускается ЛОКАЛЬНО, не на Railway — нужен ввод кода из Telegram.

    pip install telethon
    python gen_session.py

Спросит api_id, api_hash, номер телефона и код подтверждения.
Полученную строку положить в переменную TELEGRAM_STRING_SESSION на Railway.

Строка сессии = полный доступ к аккаунту. Хранить как пароль,
в репозиторий не коммитить.
"""

import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    api_id = int(input("api_id: ").strip())
    api_hash = input("api_hash: ").strip()

    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        me = await client.get_me()
        print(f"\nВошли как: {me.first_name} (@{me.username})")

        print("\n--- TELEGRAM_STRING_SESSION ---")
        print(client.session.save())
        print("--- конец ---\n")

        print("Доступные чаты (ищи здесь SOURCE_CHAT_ID):\n")
        async for dialog in client.iter_dialogs():
            print(f"{dialog.id:>16}  {dialog.name}")


if __name__ == "__main__":
    asyncio.run(main())
