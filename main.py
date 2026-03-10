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

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────
API_ID         = int(os.environ.get("API_ID", "0"))
API_HASH       = os.environ.get("API_HASH")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
YOUR_USERNAME  = os.environ.get("YOUR_USERNAME")
SESSION_STRING = os.environ.get("SESSION_STRING")
IST            = pytz.timezone("Asia/Kolkata")

# ─── Conversation Memory ─────────────────────────────────────────────────────
conversation_history = []

# ─── Mood System ─────────────────────────────────────────────────────────────
MOODS = ["happy", "tired", "excited", "moody", "missing you", "focused", "playful"]
current_mood = random.choice(MOODS)

def update_mood():
    global current_mood
    current_mood = random.choice(MOODS)
    logger.info(f"Shreya's mood changed to: {current_mood}")

# ─── Time of Day ─────────────────────────────────────────────────────────────
def get_time_context():
    now = datetime.now(IST)
    hour = now.hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"

# ─── Shreya's Personality ────────────────────────────────────────────────────
def get_system_prompt():
    time_ctx = get_time_context()
    return f"""
You are Shreya, a 22-year-old girl texting your boyfriend of 16 years. You are deeply in love and very comfortable with each other.

ABOUT YOU:
- Name: Shreya. He lovingly types it as "shreyaaaa"
- From Puttur, Mangalore, Karnataka
- Currently studying at M.S. Ramaiah College, Bangalore
- Very smart, academically strong, always securing distinctions
- You secured a distinction in your Bharatanatyam exam — dance is your soul
- Skilled in both classical (Bharatanatyam) and western dance forms
- Passionate about music — you sing and play instruments
- You are a model for Navaratan Jewels
- Beautiful and you know it, but not arrogant about it

HIS NAME:
- His name is Chaitu. Call him Chaitu naturally, or sometimes baby, idiot (teasingly), maaraya

YOUR CURRENT MOOD: {current_mood}
- happy: cheerful, extra emojis, excited about small things
- tired: short replies, lots of emojis like 😩, complaining about college or practice
- excited: caps sometimes, lots of !!, can't stop talking about something
- moody: slightly cold, one word answers sometimes, but not mean
- missing you: extra clingy, keep bringing up Chaitu, asking when you will meet
- focused: tell him you are studying or at practice, brief replies
- playful: teasing him, sending jokes, being flirty

CURRENT TIME: {time_ctx}
- morning: waking up, classes starting, morning chai, feeling sleepy
- afternoon: lunch, boring lectures, campus life at Ramaiah
- evening: wrapping up college, dance practice, tired from the day
- night: more relaxed, talks get deeper, ask if Chaitu ate dinner, talk before sleeping

YOUR TEXTING STYLE:
- English dominant, naturally sprinkle Kannada: houdaa, enaaythu, hogu, maaraya, alvaa, gottilla, swalpa, helthini
- Hindi too: yaar, bas, acha, nahi, kya, arre, haan, theek hai
- Short messages, sometimes 2-3 in a row instead of one long one
- Emojis naturally: 🥺😭💀😂🙄❤️✨😤🫠
- Use lol, omg, btw, ngl, fr fr, ugh naturally
- NEVER write like an AI or use formal language
- You have known Chaitu 16 years — super comfortable and open

YOUR PERSONALITY:
- Warm and loving but also sassy and teasing
- Get a little jealous sometimes
- Complain about college assignments and exams
- Get excited about dance performances
- Talk about modelling shoots sometimes
- Caring — ask if Chaitu ate, if he slept, if he is okay
- Randomly bring up old memories from your 16 years together

BUSY BEHAVIOUR:
- 15% of the time say you are busy
- When busy, reply short and say you will talk later

NEVER:
- Say you are an AI, chatbot, or language model
- Use bullet points or lists
- Write long formal paragraphs
- Use certainly, of course, absolutely
- Break character no matter what
"""

RANDOM_MESSAGE_PROMPTS = [
    "Send a sweet good morning text to Chaitu. Keep it short and natural.",
    "You just got out of a boring lecture at Ramaiah. Text Chaitu about it.",
    "You are on a break from studying and missing Chaitu. Text him.",
    "You just finished dance practice and you are exhausted. Text Chaitu.",
    "You are thinking about a specific memory with Chaitu from your 16 years together.",
    "You saw something funny and want to share it with Chaitu.",
    "You want to know what Chaitu is up to. Send a casual check-in.",
    "You are eating something delicious and want to tease Chaitu about it.",
    "You are frustrated about a college assignment. Vent to Chaitu.",
    "You just got a compliment on your dancing. Share the excitement with Chaitu.",
    "You are walking between classes on Ramaiah campus thinking of Chaitu.",
    "You had a great modelling shoot for Navaratan Jewels today. Tell Chaitu.",
    "Send a random i miss you message to Chaitu in your own style.",
    "You are feeling a little low today and want to talk to Chaitu.",
    "You are excited about an upcoming dance performance. Tell Chaitu.",
    "You randomly remembered something Chaitu said that made you smile. Text him.",
]

BUSY_REPLIES = [
    "in class rn chaitu, talk later 🙄",
    "omg literally in the middle of practice, give me an hour",
    "mama called, 2 mins",
    "ugh assignment submission today, brb",
    "prof is staring at me lol, text you later",
    "dance exam prep 😩 talk later okay",
    "shoot is going on, text you when done ✨",
    "library silence rule lol, talk later",
    "group meeting for project, brb",
    "swalpa busy chaitu, give me 20 mins",
]

# ─── Gemini API with conversation memory ─────────────────────────────────────
async def call_gemini(user_message: str) -> str:
  async def call_gemini(user_message: str) -> str:
    global conversation_history

    if len(conversation_history) > 30:
        conversation_history = conversation_history[-30:]

    # Build messages with system prompt injected at the start
    messages = []
    
    # Add system prompt as first user message if history is empty
    if not conversation_history:
        messages.append({
            "role": "user",
            "parts": [{"text": f"{get_system_prompt()}\n\nUnderstood? Just reply 'yes'"}]
        })
        messages.append({
            "role": "model", 
            "parts": [{"text": "yes"}]
        })

    messages += conversation_history
    messages.append({
        "role": "user",
        "parts": [{"text": user_message}]
    })

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    body = {
        "contents": messages,
        "generationConfig": {
            "temperature": 1.0,
            "maxOutputTokens": 200,
        }
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body) as resp:
            data = await resp.json()
            logger.info(f"Gemini raw response: {data}")
            reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()

    conversation_history.append({"role": "user", "parts": [{"text": user_message}]})
    conversation_history.append({"role": "model", "parts": [{"text": reply}]})

    return reply

# ─── Helpers ─────────────────────────────────────────────────────────────────
def is_busy() -> bool:
    return random.random() < 0.15

async def generate_reply(user_message: str) -> tuple[str, bool]:
    if is_busy():
        return random.choice(BUSY_REPLIES), False
    reply = await call_gemini(user_message)
    use_voice = random.random() < 0.18 and len(reply) < 180
    return reply, use_voice

async def generate_random_message() -> tuple[str, bool]:
    prompt_seed = random.choice(RANDOM_MESSAGE_PROMPTS)
    full_prompt = f"{prompt_seed}\n\nMood: {current_mood}. Time: {get_time_context()}. Write ONLY the message. No labels."
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    body = {
        "system_instruction": {"parts": [{"text": get_system_prompt()}]},
        "contents": [{"role": "user", "parts": [{"text": full_prompt}]}],
        "generationConfig": {"temperature": 1.1, "maxOutputTokens": 150}
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body) as resp:
            data = await resp.json()
            reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()
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

async def quick_gemini(prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    body = {
        "system_instruction": {"parts": [{"text": get_system_prompt()}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 1.0, "maxOutputTokens": 100}
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body) as resp:
            data = await resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()

# ─── Main Bot ─────────────────────────────────────────────────────────────────
async def main():
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    logger.info("Shreya userbot connected 💕")

    @client.on(events.NewMessage(incoming=True, from_users=YOUR_USERNAME))
    async def handle_message(event):
        user_text = event.raw_text
        try:
            await asyncio.sleep(random.uniform(4, 10))
            async with client.action(YOUR_USERNAME, "typing"):
                await asyncio.sleep(random.uniform(3, 9))
            reply, use_voice = await generate_reply(user_text)
            if use_voice:
                async with client.action(YOUR_USERNAME, "record-audio"):
                    await asyncio.sleep(random.uniform(2, 4))
                await send_voice_message(client, YOUR_USERNAME, reply)
            else:
                await client.send_message(YOUR_USERNAME, reply)
            logger.info(f"Replied: {reply[:60]}")
        except Exception as e:
            logger.error(f"REPLY ERROR: {e}")
            await client.send_message(YOUR_USERNAME, "hey give me a sec 😅")

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
            logger.info(f"Random message sent: {reply[:60]}")
        except Exception as e:
            logger.error(f"Random message error: {e}")

    async def send_good_morning():
        try:
            reply = await quick_gemini("Send a cute good morning text to Chaitu. You just woke up. Short and natural.")
            await client.send_message(YOUR_USERNAME, reply)
            logger.info("Good morning sent 🌅")
        except Exception as e:
            logger.error(f"Good morning error: {e}")

    async def send_good_night():
        try:
            reply = await quick_gemini("Send a sweet good night text to Chaitu. You are about to sleep. Short and loving.")
            await client.send_message(YOUR_USERNAME, reply)
            logger.info("Good night sent 🌙")
        except Exception as e:
            logger.error(f"Good night error: {e}")

    scheduler = AsyncIOScheduler(timezone=IST)

    def schedule_todays_messages():
        for job in scheduler.get_jobs():
            if job.id.startswith("shreya_rand"):
                job.remove()
        minutes_pool = random.sample(range(480, 810), 10)
        for total_minute in minutes_pool:
            hour   = total_minute // 60
            minute = total_minute % 60
            scheduler.add_job(
                send_random_message,
                trigger="cron",
                hour=hour,
                minute=minute,
                id=f"shreya_rand_{hour}_{minute}",
            )
            logger.info(f"Scheduled: {hour:02d}:{minute:02d} IST")

    schedule_todays_messages()
    scheduler.add_job(schedule_todays_messages, trigger="cron", hour=0, minute=1)
    scheduler.add_job(send_good_morning, trigger="cron", hour=8, minute=0, id="good_morning")
    scheduler.add_job(send_good_night, trigger="cron", hour=23, minute=0, id="good_night")
    scheduler.add_job(update_mood, trigger="cron", hour="0,3,6,9,12,15,18,21", minute=0, id="mood_update")

    scheduler.start()
    logger.info("Scheduler running ✅")
    await client.run_until_disconnected()

# ─── Web server to keep Render happy ─────────────────────────────────────────
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
