#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re

from telethon import TelegramClient

API_ID = "your_api_id"
API_HASH = "your_api_hash"
CHANNEL_USERNAME = "username_of_the_channel"
COC_LINK_PATTERN = r"https://link\.clashofclans\.com/[a-zA-Z0-9\?\=\&_]+"


async def main():
    async with TelegramClient("session_name", API_ID, API_HASH) as client:
        channel = await client.get_entity(CHANNEL_USERNAME)
        print(f"Searching for links in {channel.title}...")
        async for message in client.iter_messages(channel, limit=100):
            if message.text:
                links = re.findall(COC_LINK_PATTERN, message.text)
                if links:
                    for link in links:
                        print(f"Found link: {link}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
