#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

env_path = Path.home() / ".env"
load_dotenv(env_path)
api_id = os.environ.get("API_ID")
api_hash = os.environ.get("API_HASH")
phone_number = "+989051708322"
channel_handle = "https://t.me/pycode_hubb"
search_query = "pdf"


async def main():
    client = TelegramClient("session_name", api_id, api_hash)
    await client.start(phone=phone_number)
    entity = await client.get_entity(channel_handle)
    url_pattern = r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
    print(f"Searching for '{search_query}' in {channel_handle}...")
    async for message in client.iter_messages(entity, search=search_query):
        if message.text:
            urls = re.findall(url_pattern, message.text)
            if urls:
                print(f"Found link in message ID {message.id}: {urls}")
                with open("links.txt", "a") as f:
                    f.writelines(url + "\n" for url in urls)
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
