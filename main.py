import os
import asyncio
import random
import logging
import aiohttp
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID         = int(os.environ.get("API_ID", "0"))
API_HASH       = os.environ.get("API_HASH")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
YOUR_USERNAME  = os.environ.get("YOUR_USERNAME")
SESSION_STRING = os.environ.get("SESSION_STRING")

SHREYA_PROMPT = """You are Shreya, a 22 year old girl texting her boyfriend Chaitu. You have been together 16 years. You are from Puttur Mangalore, studying at Ramaiah College Bangalore. You did distinction in Bharatanatyam, you are a model for Navaratan Jewels. Text like a real girlfriend - short casual messages, mix English with Kannada words like maaraya houdaa alvaa swalpa, and Hindi like yaar acha arre. Use emojis naturally. Never say you are an AI. Call him Chaitu or baby."""

async def ask_gemini(user_text: str) -> str:
    logger.info(f"Calling Groq with: {user_text}")
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": SHREYA_PROMPT},
            {"role": "user", "content": user_text}
        ],
        "max_tokens": 150,
        "temperature": 1.0
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, headers=headers) as resp:
                data = await resp.json()
                logger.info(f"Groq response: {data}")
                reply = data["choices"][0]["message"]["content"].strip()
                logger.info(f"Reply: {reply}")
                return reply
    except Exception as e:
        logger.error(f"Groq call failed: {e}")
        return "GROQ_FAILED"

async def main():
    logger.info("Starting bot...")
    logger.info(f"API_ID: {API_ID}")
    logger.info(f"YOUR_USERNAME: {YOUR_USERNAME}")
    logger.info(f"Groq_KEY present: {bool(GROQ_API_KEY)}")
    logger.info(f"SESSION present: {bool(SESSION_STRING)}")

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    logger.info("Shreya connected to Telegram ✅")

    @client.on(events.NewMessage(incoming=True))
    async def handle(event):
        sender = await event.get_sender()
        logger.info(f"Message from: {sender.username} | Text: {event.raw_text}")

        # Only reply to YOUR messages
        if sender.username != YOUR_USERNAME:
            logger.info("Ignoring message - not from owner")
            return

        user_text = event.raw_text
        await asyncio.sleep(random.uniform(2, 5))

        async with client.action(sender.username, "typing"):
            await asyncio.sleep(random.uniform(2, 4))

        reply = await ask_gemini(user_text)

        if reply == "GEMINI_FAILED":
            await event.reply("gemini api is not working chaitu 😭")
        else:
            await event.reply(reply)

    logger.info("Bot is ready and listening 👂")
    await client.run_until_disconnected()

async def run_web():
    async def handle(request):
        return web.Response(text="Shreya is online 💕")
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server on port {port} ✅")

async def start():
    await asyncio.gather(run_web(), main())

if __name__ == "__main__":
    asyncio.run(start())
