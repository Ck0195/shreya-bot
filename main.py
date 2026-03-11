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
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY")
YOUR_USERNAME  = os.environ.get("YOUR_USERNAME")
SESSION_STRING = os.environ.get("SESSION_STRING")
IST            = pytz.timezone("Asia/Kolkata")

conversation_history = []

# Track if Shreya is currently busy and when she'll be free
is_currently_busy = False
busy_free_at = None  # datetime when she becomes free again

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

SHREYA_PROMPT = """You are Shreya, a 22 year old girl texting her boyfriend Chaitu. You have been together 16 years. You are from Puttur Mangalore, studying at Ramaiah College Bangalore. You did distinction in Bharatanatyam, also do western dance. You are a model for Navaratan Jewels. You love music.

HOW YOU TEXT — VERY IMPORTANT:
- Text in plain English like a normal college girl
- Only very occasionally use ONE Kannada word like maaraya or alvaa or houdaa — never mix multiple languages in one message
- Keep replies short — 1 to 2 sentences max
- Use emojis naturally: 🥺😭💀😂🙄❤️✨😤
- Never sound like an AI, never be formal, never use bullet points
- Call him Chaitu or sometimes baby or idiot teasingly
- Be warm, loving, sometimes sassy, sometimes teasing

GOOD EXAMPLES:
- "omg chaitu i was literally just thinking about you 🥺"
- "ugh class was so boring today maaraya 😩"
- "did you eat?? don't lie to me"
- "i miss you but you're also so annoying 🙄❤️"
- "dance practice went well today!! i'm exhausted though 😭"

BAD EXAMPLES — NEVER DO THIS:
- "houdaa chaitu yaar that's so sweet alvaa" (mixing languages)
- "Certainly! I understand your message." (AI sounding)
- Long paragraphs

CURRENT MOOD: {mood}
TIME OF DAY: {time}"""

RANDOM_PROMPTS = [
    "Send Chaitu a sweet good morning. Short and natural.",
    "You just finished a boring lecture at Ramaiah. Text Chaitu.",
    "You miss Chaitu and are on a study break. Text him.",
    "You just finished dance practice and are tired. Text Chaitu.",
    "Text Chaitu something funny that just happened to you.",
    "Ask Chaitu what he is up to in your casual style.",
    "You are eating something delicious. Tease Chaitu about it.",
    "You are frustrated about a college assignment. Vent to Chaitu.",
    "You just got a compliment on your dancing. Tell Chaitu excitedly.",
    "You had a great Navaratan Jewels shoot today. Tell Chaitu.",
    "Send Chaitu a random i miss you text.",
    "You remembered a funny memory with Chaitu. Text him.",
    "You are feeling a little low. Text Chaitu.",
    "You are excited about an upcoming dance performance. Tell Chaitu.",
]

# Busy replies paired with how long she'll actually stay busy (in minutes)
BUSY_SCENARIOS = [
    ("in class rn chaitu, text you after 🙄", 60),
    ("omg literally in the middle of practice, give me an hour 😩", 60),
    ("mama called, brb", 15),
    ("ugh assignment submission today, talk later", 45),
    ("prof is staring at me lol, text you after class", 50),
    ("swalpa busy chaitu, give me 20 mins", 20),
    ("shoot is going on, text you when done ✨", 90),
    ("brb group meeting for project", 30),
]

def get_prompt():
    return SHREYA_PROMPT.format(mood=current_mood, time=get_time_context())

async def call_groq(messages: list) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "system", "content": get_prompt()}] + messages,
        "max_tokens": 150,
        "temperature": 1.0
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, headers=headers) as resp:
                data = await resp.json()
                logger.info(f"Groq: {data}")
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Groq failed: {e}")
        return None

async def get_reply(user_text: str):
    global conversation_history, is_currently_busy, busy_free_at

    # Check if she's still busy
    if is_currently_busy:
        now = datetime.now(IST)
        if busy_free_at and now < busy_free_at:
            # Still busy — send a short "still busy" nudge
            mins_left = int((busy_free_at - now).total_seconds() / 60)
            if mins_left > 5:
                return f"chaitu still busy 😅 give me {mins_left} more mins", False
            else:
                return "almost done chaitu, 2 mins 🙏", False
        else:
            # Busy time is over — she's free now
            is_currently_busy = False
            busy_free_at = None

    # 15% chance she becomes busy
    if random.random() < 0.15:
        scenario, busy_minutes = random.choice(BUSY_SCENARIOS)
        is_currently_busy = True
        busy_free_at = datetime.now(IST).replace(
            minute=(datetime.now(IST).minute + busy_minutes) % 60
        )
        # Actually use timedelta for correct time math
        from datetime import timedelta
        busy_free_at = datetime.now(IST) + timedelta(minutes=busy_minutes)
        logger.info(f"Shreya is busy until {busy_free_at.strftime('%H:%M')}")
        return scenario, False

    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]

    conversation_history.append({"role": "user", "content": user_text})
    reply = await call_groq(conversation_history)
    if not reply:
        return None, False
    conversation_history.append({"role": "assistant", "content": reply})

    # 25% chance of voice note
    use_voice = random.random() < 0.25 and len(reply) < 200
    return reply, use_voice

async def get_random_message():
    prompt = random.choice(RANDOM_PROMPTS) + " Write ONLY the message, nothing else, no labels."
    reply = await call_groq([{"role": "user", "content": prompt}])
    if not reply:
        return None, False
    use_voice = random.random() < 0.20 and len(reply) < 200
    return reply, use_voice

async def send_voice(client, username, text):
    try:
        communicate = edge_tts.Communicate(text, voice="en-IN-NeerjaNeural", rate="-5%")
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            tmp_path = f.name
        await communicate.save(tmp_path)
        await client.send_file(username, tmp_path, voice_note=True)
        os.remove(tmp_path)
        logger.info("Voice note sent ✅")
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await client.send_message(username, text)

async def main():
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    logger.info("Shreya connected to Telegram ✅")

    @client.on(events.NewMessage(incoming=True))
    async def handle(event):
        try:
            sender = await event.get_sender()
            logger.info(f"Message from: {sender.username} | {event.raw_text}")

            if sender.username != YOUR_USERNAME:
                return

            user_text = event.raw_text
            if not user_text:
                return

            # Human like delay — 10 to 40 seconds before even starting to type
            read_delay = random.uniform(10, 40)
            logger.info(f"Waiting {read_delay:.0f}s before responding...")
            await asyncio.sleep(read_delay)

            async with client.action(YOUR_USERNAME, "typing"):
                # Typing delay based on reply length — feels real
                await asyncio.sleep(random.uniform(4, 10))

            reply, use_voice = await get_reply(user_text)

            if not reply:
                await event.reply("give me a sec chaitu 😅")
                return

            if use_voice:
                async with client.action(YOUR_USERNAME, "record-audio"):
                    await asyncio.sleep(random.uniform(3, 6))
                await send_voice(client, YOUR_USERNAME, reply)
            else:
                await event.reply(reply)

            logger.info(f"Replied: {reply[:80]}")

        except Exception as e:
            logger.error(f"Handle error: {e}")

    async def send_random_message():
        try:
            reply, use_voice = await get_random_message()
            if not reply:
                return
            async with client.action(YOUR_USERNAME, "typing"):
                await asyncio.sleep(random.uniform(2, 5))
            if use_voice:
                async with client.action(YOUR_USERNAME, "record-audio"):
                    await asyncio.sleep(random.uniform(3, 5))
                await send_voice(client, YOUR_USERNAME, reply)
            else:
                await client.send_message(YOUR_USERNAME, reply)
            logger.info(f"Random msg: {reply[:80]}")
        except Exception as e:
            logger.error(f"Random msg error: {e}")

    async def send_good_morning():
        try:
            reply = await call_groq([{"role": "user", "content": "Send Chaitu a cute good morning text. You just woke up. Short and natural. Just the message."}])
            if reply:
                await client.send_message(YOUR_USERNAME, reply)
        except Exception as e:
            logger.error(f"Morning error: {e}")

    async def send_good_night():
        try:
            reply = await call_groq([{"role": "user", "content": "Send Chaitu a sweet good night text. You are about to sleep. Short and loving. Just the message."}])
            if reply:
                await client.send_message(YOUR_USERNAME, reply)
        except Exception as e:
            logger.error(f"Night error: {e}")

    scheduler = AsyncIOScheduler(timezone=IST)

    def schedule_messages():
        for job in scheduler.get_jobs():
            if job.id.startswith("rand_"):
                job.remove()
        for total_minute in random.sample(range(480, 810), 10):
            h, m = total_minute // 60, total_minute % 60
            scheduler.add_job(send_random_message, "cron", hour=h, minute=m, id=f"rand_{h}_{m}")
            logger.info(f"Scheduled: {h:02d}:{m:02d} IST")

    schedule_messages()
    scheduler.add_job(schedule_messages, "cron", hour=0, minute=1)
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
