from telethon import TelegramClient, events
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# Your Telegram API credentials (get from https://my.telegram.org/apps)
API_ID = int(os.getenv('TELEGRAM_API_ID'))
API_HASH = os.getenv('TELEGRAM_API_HASH')
PHONE = os.getenv('TELEGRAM_PHONE')

# Channel IDs
SOURCE_CHANNEL_ID = -1001234567890  # AITA Signal Bot channel
TARGET_CHANNEL_ID = -1009876543210  # Your private channel

client = TelegramClient('session', API_ID, API_HASH)

@client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
async def forward_handler(event):
    """Forward messages from source to target channel"""
    try:
        await client.forward_messages(TARGET_CHANNEL_ID, event.message)
        print(f"Forwarded message: {event.message.text[:50]}...")
    except Exception as e:
        print(f"Error forwarding message: {e}")

async def main():
    await client.start(phone=PHONE)
    print("Forwarder started...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())