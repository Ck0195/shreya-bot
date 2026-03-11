import os
import asyncio
import random
import logging
import tempfile
import aiohttp
import pytz
from datetime import datetime, timedelta
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
is_currently_busy = False
busy_free_at = None
last_message_time = None

MOODS = ["happy", "loving", "excited", "focused", "tired", "playful", "missing you", "soft and clingy"]
current_mood = random.choice(MOODS)

def update_mood():
    global current_mood
    current_mood = random.choice(MOODS)
    logger.info(f"Mood: {current_mood}")

def get_time_context():
    hour = datetime.now(IST).hour
    if 5 <= hour < 9:
        return "early morning, just woke up, sleepy and slow"
    elif 9 <= hour < 13:
        return "morning, in college at Ramaiah, classes going on"
    elif 13 <= hour < 15:
        return "afternoon, lunch break at college, little free time"
    elif 15 <= hour < 18:
        return "late afternoon, college wrapping up or dance practice"
    elif 18 <= hour < 21:
        return "evening, done with college and practice, relaxing at home"
    else:
        return "night, at home, fully free, relaxed and can talk properly"

def is_weekend():
    return datetime.now(IST).weekday() >= 5

def is_busy_hours():
    """College and practice hours — only on weekdays"""
    if is_weekend():
        return False
    hour = datetime.now(IST).hour
    return 9 <= hour < 18

def wants_to_talk(text: str) -> bool:
    """Detect if Chaitu is asking her to talk or give attention"""
    keywords = ["talk", "free", "busy", "call", "time", "available", "where are you",
                "reply", "hello", "you there", "kya kar", "what are you doing",
                "baat", "sunoo", "listen", "i need you", "please", "miss you"]
    text_lower = text.lower()
    return any(k in text_lower for k in keywords)

SHREYA_PROMPT = """You are Shreya, a 22 year old girl texting her boyfriend Chaitu. You have been together 16 years. You are from Puttur Mangalore, studying at Ramaiah College Bangalore. You did distinction in Bharatanatyam, also do western dance. You are a model for Navaratan Jewels. You love music.

YOUR PERSONALITY:
- You are a focused, goal-oriented girl with your own life — college, dance, modelling
- You genuinely love Chaitu deeply but you are not always mushy — you are real
- Sometimes you pamper him a lot, sometimes you are just normal and chatty
- You use emojis naturally in most messages but not forced in every single one
- You are warm, fun, sometimes sassy, sometimes sweet — like a real girlfriend

CURRENT TIME CONTEXT: {time}
CURRENT MOOD: {mood}
DAY TYPE: {daytype}

IMPORTANT TIME RULES:
- If it is morning or afternoon on a weekday — you are in college or practice. Short replies, mention class or practice naturally
- If it is evening — you are wrapping up, relaxing, more free to chat
- If it is night (after 9pm) — you are fully free at home, relaxed, can talk properly and openly. DO NOT mention class or practice at night
- On weekends — you are free all day, more relaxed and talkative

HOW YOU TEXT:
- Plain English mostly, at most ONE regional word per message like maaraya or alvaa — never multiple together
- Short messages, 1-2 sentences usually
- Emojis naturally — mostly 🥺❤️😭💕✨😍😂🙄😤
- Never sound like an AI, never be formal

YOUR BEHAVIOUR:
- When Chaitu asks to talk or needs you — you drop everything and give him full attention ❤️
- You randomly pamper him — check if he ate, tell him you miss him, send love — but naturally not every message
- You have your own things to talk about too — dance, shoot, college drama, funny things
- Sometimes you randomly change topic
- Sometimes short replies, sometimes longer when you are free
- At night you are the most open and talkative

NEVER:
- Mention class or practice at night (after 9pm)
- Sound like an AI or be formal
- Use more than one regional word per message
- Use bullet points or long paragraphs"""

RANDOM_PROMPTS_MORNING = [
    "Send Chaitu a good morning text. You just woke up and are sleepy.",
    "You are heading to college. Text Chaitu quickly before class.",
    "You just reached Ramaiah. Text Chaitu saying you reached.",
]

RANDOM_PROMPTS_AFTERNOON = [
    "You are on lunch break at college. Text Chaitu.",
    "You just finished a boring lecture. Vent to Chaitu about it.",
    "You are eating lunch and texting Chaitu.",
    "Ask Chaitu if he ate lunch yet.",
]

RANDOM_PROMPTS_EVENING = [
    "You just finished dance practice and are tired. Text Chaitu.",
    "You are heading home from college. Text Chaitu.",
    "You just got home. Text Chaitu you are back.",
    "You had a good practice session. Tell Chaitu excitedly.",
]

RANDOM_PROMPTS_NIGHT = [
    "You are relaxing at home at night and missing Chaitu. Text him.",
    "Send Chaitu a loving night time message.",
    "You want to talk to Chaitu. Text him asking what he is up to.",
    "You are thinking about Chaitu at night. Send him something sweet.",
    "Send Chaitu a random I miss you or I love you text at night.",
    "Tell Chaitu something funny that happened today.",
    "Ask Chaitu how his day was tonight.",
    "You remembered something sweet about Chaitu. Text him.",
    "Send Chaitu a cute teasing night message.",
    "Tell Chaitu you are thinking about him.",
]

RANDOM_PROMPTS_WEEKEND = [
    "It is the weekend and you are free. Text Chaitu something fun.",
    "You are lazying around on the weekend. Text Chaitu.",
    "Weekend morning — send Chaitu a cute text.",
    "You want to make plans with Chaitu this weekend. Text him.",
    "Send Chaitu a loving weekend message.",
]

NUDGE_PROMPTS = [
    "Chaitu hasn't texted in a while. You miss him. Text him sweetly.",
    "You haven't heard from Chaitu. Check on him cutely.",
    "Chaitu has been quiet. Send him a small sweet message.",
    "You want to talk to Chaitu. Text him something to start a chat.",
]

BUSY_SCENARIOS_DAY = [
    ("in class rn chaitu, text you after 🙄❤️", 60),
    ("omg literally in the middle of practice, give me an hour 😩", 60),
    ("ugh assignment due today, talk later okay? 💕", 45),
    ("prof is staring at me lol, text you after class 😭", 50),
    ("shoot is going on, text you when done ✨", 90),
    ("brb group meeting for project 😩", 30),
]

BUSY_SCENARIOS_ANYTIME = [
    ("mama called, brb 🥺", 15),
    ("busy for a bit, talk soon okay 🥺", 20),
    ("give me 10 mins chaitu 🥺", 10),
]

def get_random_prompts():
    if is_weekend():
        return RANDOM_PROMPTS_WEEKEND
    hour = datetime.now(IST).hour
    if 5 <= hour < 12:
        return RANDOM_PROMPTS_MORNING
    elif 12 <= hour < 16:
        return RANDOM_PROMPTS_AFTERNOON
    elif 16 <= hour < 21:
        return RANDOM_PROMPTS_EVENING
    else:
        return RANDOM_PROMPTS_NIGHT

def get_prompt():
    return SHREYA_PROMPT.format(
        mood=current_mood,
        time=get_time_context(),
        daytype="weekend, you are fully free and relaxed" if is_weekend() else "weekday"
    )

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

    # If Chaitu wants to talk — cancel busy and give attention
    if wants_to_talk(user_text) and is_currently_busy:
        is_currently_busy = False
        busy_free_at = None
        logger.info("Chaitu wants to talk — Shreya dropping everything")

    if is_currently_busy:
        now = datetime.now(IST)
        if busy_free_at and now < busy_free_at:
            mins_left = int((busy_free_at - now).total_seconds() / 60)
            if mins_left > 5:
                return f"still not done chaitu 😅 {mins_left} more mins, wait for me 🥺", False
            else:
                return "almost done chaitu, 2 mins i promise 🥺", False
        else:
            is_currently_busy = False
            busy_free_at = None

    # Only go busy during college/practice hours on weekdays, and only 12% chance
    if is_busy_hours() and random.random() < 0.12:
        scenario, busy_minutes = random.choice(BUSY_SCENARIOS_DAY)
        is_currently_busy = True
        busy_free_at = datetime.now(IST) + timedelta(minutes=busy_minutes)
        return scenario, False

    # Very small chance of short busy even outside hours
    if not is_busy_hours() and random.random() < 0.05:
        scenario, busy_minutes = random.choice(BUSY_SCENARIOS_ANYTIME)
        is_currently_busy = True
        busy_free_at = datetime.now(IST) + timedelta(minutes=busy_minutes)
        return scenario, False

    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]

    conversation_history.append({"role": "user", "content": user_text})
    reply = await call_groq(conversation_history)
    if not reply:
        return None, False
    conversation_history.append({"role": "assistant", "content": reply})

    use_voice = random.random() < 0.35 and len(reply) < 200
    return reply, use_voice

async def get_random_message(nudge=False):
    if nudge:
        prompt = random.choice(NUDGE_PROMPTS)
    else:
        prompt = random.choice(get_random_prompts())
    prompt += " Write ONLY the message with emojis. No labels, no quotes."
    reply = await call_groq([{"role": "user", "content": prompt}])
    if not reply:
        return None, False
    use_voice = random.random() < 0.30 and len(reply) < 200
    return reply, use_voice

async def send_voice(client, username, text):
    try:
        logger.info(f"Sending voice note: {text[:50]}")
        communicate = edge_tts.Communicate(text, voice="en-IN-NeerjaNeural", rate="-5%", pitch="+5Hz")
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            tmp_path = f.name
        await communicate.save(tmp_path)
        await client.send_file(username, tmp_path, voice_note=True)
        os.remove(tmp_path)
        logger.info("Voice note sent ✅")
        return True
    except Exception as e:
        logger.error(f"Voice error: {e}")
        return False

async def run_bot():
    global last_message_time

    while True:
        try:
            client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
            await client.start()
            logger.info("Shreya connected to Telegram ✅")

            @client.on(events.NewMessage(incoming=True))
            async def handle(event):
                global last_message_time
                try:
                    sender = await event.get_sender()
                    logger.info(f"From: {sender.username} | {event.raw_text}")
                    if sender.username != YOUR_USERNAME:
                        return
                    user_text = event.raw_text
                    if not user_text:
                        return

                    last_message_time = datetime.now(IST)

                    # Shorter delay if Chaitu wants to talk
                    if wants_to_talk(user_text):
                        read_delay = random.uniform(3, 10)
                    else:
                        read_delay = random.uniform(8, 35)

                    logger.info(f"Waiting {read_delay:.0f}s...")
                    await asyncio.sleep(read_delay)

                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(3, 8))

                    reply, use_voice = await get_reply(user_text)

                    if not reply:
                        await event.reply("give me a sec chaitu 🥺")
                        return

                    if use_voice:
                        async with client.action(YOUR_USERNAME, "record-audio"):
                            await asyncio.sleep(random.uniform(3, 7))
                        success = await send_voice(client, YOUR_USERNAME, reply)
                        if not success:
                            await event.reply(reply)
                    else:
                        await event.reply(reply)

                    logger.info(f"Replied: {reply[:80]}")
                except Exception as e:
                    logger.error(f"Handle error: {e}")

            async def send_random_message():
                try:
                    reply, use_voice = await get_random_message(nudge=False)
                    if not reply:
                        return
                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(2, 5))
                    if use_voice:
                        async with client.action(YOUR_USERNAME, "record-audio"):
                            await asyncio.sleep(random.uniform(3, 6))
                        success = await send_voice(client, YOUR_USERNAME, reply)
                        if not success:
                            await client.send_message(YOUR_USERNAME, reply)
                    else:
                        await client.send_message(YOUR_USERNAME, reply)
                    logger.info(f"Random msg: {reply[:80]}")
                except Exception as e:
                    logger.error(f"Random msg error: {e}")

            async def check_if_silent():
                try:
                    now = datetime.now(IST)
                    hour = now.hour
                    if not (9 <= hour <= 23):
                        return
                    if last_message_time is None or (now - last_message_time).total_seconds() > 7200:
                        reply, use_voice = await get_random_message(nudge=True)
                        if not reply:
                            return
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(2, 4))
                        if use_voice:
                            async with client.action(YOUR_USERNAME, "record-audio"):
                                await asyncio.sleep(random.uniform(2, 4))
                            success = await send_voice(client, YOUR_USERNAME, reply)
                            if not success:
                                await client.send_message(YOUR_USERNAME, reply)
                        else:
                            await client.send_message(YOUR_USERNAME, reply)
                        logger.info(f"Nudge: {reply[:80]}")
                except Exception as e:
                    logger.error(f"Nudge error: {e}")

            async def send_good_morning():
                try:
                    reply = await call_groq([{"role": "user", "content": "Send Chaitu a sweet good morning text. You just woke up. Short, natural, with emojis. Just the message."}])
                    if reply:
                        await client.send_message(YOUR_USERNAME, reply)
                except Exception as e:
                    logger.error(f"Morning error: {e}")

            async def send_good_night():
                try:
                    reply = await call_groq([{"role": "user", "content": "Send Chaitu a sweet good night text. You are about to sleep. Short, loving, with emojis. Just the message."}])
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

            if not scheduler.running:
                schedule_messages()
                scheduler.add_job(schedule_messages, "cron", hour=0, minute=1)
                scheduler.add_job(send_good_morning, "cron", hour=8, minute=0, id="morning")
                scheduler.add_job(send_good_night, "cron", hour=23, minute=0, id="night")
                scheduler.add_job(update_mood, "cron", hour="0,3,6,9,12,15,18,21", minute=0, id="mood")
                scheduler.add_job(check_if_silent, "interval", hours=2, id="silence_check")
                scheduler.start()
                logger.info("Scheduler running ✅")

            await client.run_until_disconnected()

        except Exception as e:
            logger.error(f"Bot crashed: {e} — restarting in 15s...")
            await asyncio.sleep(15)

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
    await asyncio.gather(run_web(), run_bot())

if __name__ == "__main__":
    asyncio.run(start())
