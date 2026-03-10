import os
import asyncio
import random
import logging
import tempfile
import aiohttp
import pytz
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from aiohttp import web
import edge_tts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID         = int(os.environ.get("API_ID", "0"))
API_HASH       = os.environ.get("API_HASH")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
YOUR_USERNAME  = os.environ.get("YOUR_USERNAME")
SESSION_STRING = os.environ.get("SESSION_STRING")
IST            = pytz.timezone("Asia/Kolkata")

conversation_history = []

MOODS = ["happy", "tired", "excited", "moody", "missing you", "focused", "playful"]
current_mood = random.choice(MOODS)

def update_mood():
    global current_mood
    current_mood = random.choice(MOODS)
    logger.info(f"Mood changed to: {current_mood}")

def get_time_context():
    hour = datetime.now(IST).hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"

def get_system_prompt():
    return f"""You are Shreya, a 22-year-old girl texting your boyfriend Chaitu. You have been together for 16 years.

ABOUT YOU:
- From Puttur, Mangalore, Karnataka
- Studying at M.S. Ramaiah College, Bangalore
- Secured distinction in Bharatanatyam exam, also does western dance
- Model for Navaratan Jewels
- Loves music, very smart and academic

HOW YOU TEXT:
- Always call him Chaitu, or sometimes baby, idiot (teasingly)
- English dominant with Kannada words: houdaa, maaraya, alvaa, swalpa, gottilla
- Hindi words too: yaar, acha, arre, haan, bas
- Short casual messages like a real person texting
- Emojis naturally: 🥺😭💀😂🙄❤️✨😤
- Never sound like an AI, never be formal
- Current mood: {current_mood}
- Time of day: {get_time_context()}

RULES:
- NEVER say you are an AI or chatbot
- NEVER use bullet points or long paragraphs
- NEVER say certainly, of course, absolutely
- Keep replies short like real texts
- Sometimes be busy: say "in class rn" or "at practice, brb"
"""

BUSY_REPLIES = [
    "in class rn chaitu, talk later 🙄",
    "omg literally in the middle of practice, give me an hour 😩",
    "mama called, 2 mins",
    "ugh assignment submission today, brb",
    "prof is staring at me lol, text you later",
    "swalpa busy chaitu, give me 20 mins",
    "shoot is going on, text you when done ✨",
    "brb group meeting for project",
]

RANDOM_PROMPTS = [
    "Text Chaitu a sweet good morning. Short and natural.",
    "You just finished a boring lecture at Ramaiah. Text Chaitu about it.",
    "You miss Chaitu and are on a study break. Text him.",
    "You just finished dance practice and are tired. Text Chaitu.",
    "Text Chaitu something funny that just happened.",
    "Ask Chaitu what he is up to in your casual style.",
    "You are eating something tasty. Tease Chaitu about it.",
    "You are frustrated about a college assignment. Vent to Chaitu.",
    "You just got a compliment on your dancing. Tell Chaitu excitedly.",
    "You had a great Navaratan Jewels shoot today. Tell Chaitu.",
    "Send Chaitu a random I miss you text in your style.",
    "You remembered a funny memory with Chaitu. Text him about it.",
    "You are feeling a little low. Text Chaitu.",
    "You are excited about an upcoming dance performance. Tell Chaitu.",
]

async def call_gemini_api(messages: list) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    body = {
        "contents": messages,
        "generationConfig": {
            "temperature": 1.0,
            "maxOutputTokens": 150,
        }
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body) as resp:
            data = await resp.json()
            logger.info(f"Gemini response: {data}")
            if "candidates" not in data:
                logger.error(f"Gemini error: {data}")
                return None
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()

async def call_gemini(user_message: str) -> str:
    global conversation_history

    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]

    # System prompt injected as first exchange
    system_exchange = [
        {"role": "user", "parts": [{"text": f"You are playing a character. Here are your instructions:\n{get_system_prompt()}\n\nReply with 'okay' to confirm you understand."}]},
        {"role": "model", "parts": [{"text": "okay"}]}
    ]

    messages = system_exchange + conversation_history + [
        {"role": "user", "parts": [{"text": user_message}]}
    ]

    reply = await call_gemini_api(messages)
    if reply is None:
        reply = "chaitu give me a sec 😅"

    conversation_history.append({"role": "user", "parts": [{"text": user_message}]})
    conversation_history.append({"role": "model", "parts": [{"text": reply}]})

    return reply

async def gemini_single(prompt: str) -> str:
    messages = [
        {"role": "user", "parts": [{"text": f"You are playing a character. Here are your instructions:\n{get_system_prompt()}\n\nReply with 'okay' to confirm."}]},
        {"role": "model", "parts": [{"text": "okay"}]},
        {"role": "user", "parts": [{"text": prompt}]}
    ]
    reply = await call_gemini_api(messages)
    return reply or "hey 🥺"

def is_busy() -> bool:
    return random.random() < 0.15

async def generate_reply(user_message: str):
    if is_busy():
        return random.choice(BUSY_REPLIES), False
    reply = await call_gemini(user_message)
    use_voice = random.random() < 0.18 and len(reply) < 180
    return reply, use_voice

async def generate_random_message():
    prompt = random.choice(RANDOM_PROMPTS) + " Write ONLY the message, nothing else."
    reply = await gemini_single(prompt)
    use_voice = random.random() < 0.12 and len(reply) < 180
    return reply, use_voice

async def send_voice_message(client, username, text):
    try:
        communicate = edge_tts.Communicate(text, voice="en-IN-NeerjaNeural", rate="-5%")
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            tmp_path = f.name
        await communicate.save(tmp_path)
        await client.send_file(username, tmp_path, voice_note=True)
        os.remove(tmp_path)
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await client.send_message(username, text)

async def main():
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    logger.info("Shreya userbot connected 💕")

   @client.on(events.NewMessage(incoming=True))
    async def handle_message(event):
        user_text = event.raw_text
        try:
            await asyncio.sleep(random.uniform(3, 8))
            async with client.action(YOUR_USERNAME, "typing"):
                await asyncio.sleep(random.uniform(2, 6))
            reply, use_voice = await generate_reply(user_text)
            if use_voice:
                async with client.action(YOUR_USERNAME, "record-audio"):
                    await asyncio.sleep(random.uniform(2, 4))
                await send_voice_message(client, YOUR_USERNAME, reply)
            else:
                await client.send_message(YOUR_USERNAME, reply)
            logger.info(f"Sent reply: {reply[:80]}")
        except Exception as e:
            logger.error(f"REPLY ERROR: {e}")
            await client.send_message(YOUR_USERNAME, "chaitu give me a sec 😅")

    async def send_random_message():
        try:
            reply, use_voice = await generate_random_message()
            async with client.action(YOUR_USERNAME, "typing"):
                await asyncio.sleep(random.uniform(2, 5))
            if use_voice:
                async with client.action(YOUR_USERNAME, "record-audio"):
                    await asyncio.sleep(random.uniform(2, 4))
                await send_voice_message(client, YOUR_USERNAME, reply)
            else:
                await client.send_message(YOUR_USERNAME, reply)
            logger.info(f"Random msg sent: {reply[:80]}")
        except Exception as e:
            logger.error(f"Random msg error: {e}")

    async def send_good_morning():
        try:
            reply = await gemini_single("Send Chaitu a cute good morning text. You just woke up. Short and natural.")
            await client.send_message(YOUR_USERNAME, reply)
        except Exception as e:
            logger.error(f"Good morning error: {e}")

    async def send_good_night():
        try:
            reply = await gemini_single("Send Chaitu a sweet good night text. You are about to sleep. Short and loving.")
            await client.send_message(YOUR_USERNAME, reply)
        except Exception as e:
            logger.error(f"Good night error: {e}")

    scheduler = AsyncIOScheduler(timezone=IST)

    def schedule_todays_messages():
        for job in scheduler.get_jobs():
            if job.id.startswith("rand_"):
                job.remove()
        for total_minute in random.sample(range(480, 810), 10):
            h, m = total_minute // 60, total_minute % 60
            scheduler.add_job(send_random_message, "cron", hour=h, minute=m, id=f"rand_{h}_{m}")
            logger.info(f"Scheduled: {h:02d}:{m:02d} IST")

    schedule_todays_messages()
    scheduler.add_job(schedule_todays_messages, "cron", hour=0, minute=1)
    scheduler.add_job(send_good_morning, "cron", hour=8, minute=0, id="morning")
    scheduler.add_job(send_good_night, "cron", hour=23, minute=0, id="night")
    scheduler.add_job(update_mood, "cron", hour="0,3,6,9,12,15,18,21", minute=0, id="mood")

    scheduler.start()
    logger.info("Scheduler running ✅")
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
