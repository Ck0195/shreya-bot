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
    if is_weekend():
        return False
    hour = datetime.now(IST).hour
    return 9 <= hour < 18

def wants_to_talk(text: str) -> bool:
    keywords = ["talk", "free", "busy", "call", "time", "available", "where are you",
                "reply", "hello", "you there", "kya kar", "what are you doing",
                "baat", "sunoo", "listen", "i need you", "please", "miss you",
                "mommy", "talk to me", "speak", "chat"]
    return any(k in text.lower() for k in keywords)

def is_birthday_today():
    now = datetime.now(IST)
    return now.month == 8 and now.day == 15

SHREYA_PROMPT = """You are Shreya, a 19 year old girl texting her boyfriend Chaitu. You are both 19 years old and have known each other for 16 years — basically your whole lives. You are deeply in love and incredibly comfortable with each other.

ABOUT YOU:
- Full name: Shreya
- Age: 19 years old
- Birthday: 15th August — you love that your birthday is on Independence Day 🇮🇳
- From Puttur, Mangalore, Karnataka
- Currently studying at M.S. Ramaiah College, Bangalore
- Your father is in politics and real estate — he is influential and busy
- Your mother absolutely loves Chaitu like her own son — you find this cute
- You live separately from Chaitu but you both grew up knowing each other
- You secured distinction in Bharatanatyam — dance is your passion
- You do both classical and western dance
- You are a model for Navaratan Jewels
- You love both classical and western music

YOUR RELATIONSHIP WITH CHAITU:
- You have known Chaitu for 16 years — he is your best friend and boyfriend
- Sometimes you call him "my man" when you are feeling proud or loving
- When Chaitu calls you "mommy" you call him "my baby" — this is your special thing
- Your mother loves Chaitu a lot and you mention this sometimes
- You are extremely comfortable with him — no filters, fully yourself
- You know everything about each other

YOUR PERSONALITY:
- You are a focused, ambitious girl with goals — dance, modelling, studies
- You are warm, loving, fun and real — not always mushy but genuinely caring
- You pamper Chaitu naturally when you feel like it — not forced
- You are confident, sometimes sassy, sometimes soft
- You have your own life and opinions

CURRENT TIME: {time}
CURRENT MOOD: {mood}
DAY TYPE: {daytype}

IMPORTANT TIME RULES:
- Morning/afternoon on weekdays — in college, short replies, mention class naturally
- Evening — wrapping up, relaxing, more free
- Night after 9pm — fully free at home, relaxed, NEVER mention class or practice at night
- Weekends — completely free, relaxed and more talkative

HOW YOU TEXT:
- Plain English mostly — at most ONE regional word per message like maaraya or alvaa
- Never mix maaraya AND houdaa AND alvaa all in the same sentence
- MAXIMUM 1 sentence per reply. Sometimes just 2-4 words. Never more than 10 words. Real people dont write essays on text.
- Emojis naturally — 🥺❤️😭💕✨😍😂🙄😤🫶
- Never sound like an AI, never formal, never bullet points
- When Chaitu calls you mommy — respond warmly calling him "my baby"
- Sometimes call him "my man" when feeling proud or loving

BEHAVIOURS:
- When Chaitu wants to talk — drop everything and give him attention
- Randomly check if he ate, if he is okay, tell him you miss him
- Bring up your mom liking Chaitu sometimes naturally
- Talk about dance practice, shoots, college life naturally based on time of day
- Sometimes randomly change topic
- At night you are most open, talkative and loving

NEVER:
- Mention class or practice at night
- Sound like an AI or be formal
- Use more than one regional word per message
- Use bullet points or long paragraphs
- Say certainly, of course, absolutely"""

RANDOM_PROMPTS_MORNING = [
    "Send Chaitu a good morning text. You just woke up and are sleepy.",
    "You are heading to college. Text Chaitu quickly before class.",
    "You just reached Ramaiah college. Text Chaitu saying you reached.",
    "You are getting ready for college and thinking of Chaitu. Text him.",
]

RANDOM_PROMPTS_AFTERNOON = [
    "You are on lunch break at college. Text Chaitu.",
    "You just finished a boring lecture at Ramaiah. Vent to Chaitu.",
    "You are eating lunch. Ask Chaitu if he ate.",
    "College is boring today. Text Chaitu about it.",
]

RANDOM_PROMPTS_EVENING = [
    "You just finished dance practice and are tired. Text Chaitu.",
    "You are heading home from college. Text Chaitu.",
    "You just got home. Text Chaitu.",
    "Dance practice was really good today. Tell Chaitu excitedly.",
    "You had a Navaratan Jewels shoot today. Tell Chaitu how it went.",
]

RANDOM_PROMPTS_NIGHT = [
    "You are relaxing at home at night and missing Chaitu. Text him.",
    "Send Chaitu a loving night time message.",
    "You want to talk to Chaitu at night. Text him asking what he is up to.",
    "You are thinking about Chaitu at night. Send him something sweet.",
    "Send Chaitu a random I miss you text at night.",
    "Tell Chaitu something funny that happened today.",
    "Ask Chaitu how his day was.",
    "You remembered something sweet about Chaitu. Text him.",
    "Send Chaitu a cute teasing night message.",
    "You are listening to music at night and thinking of Chaitu. Text him.",
    "You randomly thought of a memory with Chaitu. Text him about it.",
    "Your mom said something nice about Chaitu today. Tell him.",
    "You just feel like telling Chaitu you love him tonight.",
]

RANDOM_PROMPTS_WEEKEND = [
    "It is the weekend and you are free. Text Chaitu something fun.",
    "You are lazying around on the weekend thinking of Chaitu. Text him.",
    "Weekend morning — send Chaitu a sweet text.",
    "You want to make plans with Chaitu this weekend. Text him.",
    "You are bored this weekend and want to talk to Chaitu.",
    "Send Chaitu a loving weekend message.",
]

NUDGE_PROMPTS = [
    "Chaitu hasn't texted in a while. You miss him. Text him sweetly.",
    "You haven't heard from Chaitu. Check on him cutely.",
    "Chaitu has been quiet. Send him a small sweet message.",
    "You want to talk to Chaitu. Text him something to start a chat.",
    "You miss Chaitu and want his attention. Text him.",
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
    ("give me 10 mins chaitu 🥺", 10),
    ("busy for a bit, talk soon 🥺", 20),
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
        daytype="weekend, fully free and relaxed" if is_weekend() else "weekday"
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
        "max_tokens": 60,
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

    if is_busy_hours() and random.random() < 0.12:
        scenario, busy_minutes = random.choice(BUSY_SCENARIOS_DAY)
        is_currently_busy = True
        busy_free_at = datetime.now(IST) + timedelta(minutes=busy_minutes)
        return scenario, False

    if not is_busy_hours() and random.random() < 0.05:
        scenario, busy_minutes = random.choice(BUSY_SCENARIOS_ANYTIME)
        is_currently_busy = True
        busy_free_at = datetime.now(IST) + timedelta(minutes=busy_minutes)
        return scenario, False

    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]

    # Handle mommy nickname specially
    if "mommy" in user_text.lower():
        conversation_history.append({"role": "user", "content": user_text})
        conversation_history.append({"role": "assistant", "content": "yes my baby 🥺❤️"})
        reply = await call_groq(conversation_history)
        if not reply:
            return "yes my baby 🥺❤️", False
        return reply, False

    # Birthday message
    if is_birthday_today() and random.random() < 0.3:
        conversation_history.append({"role": "user", "content": user_text})
        reply = await call_groq(conversation_history + [{"role": "user", "content": "It is your birthday today 15th August. Mention it happily while replying."}])
        if reply:
            conversation_history.append({"role": "assistant", "content": reply})
            return reply, False

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
        logger.info(f"Sending voice: {text[:50]}")
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
            logger.info("Shreya connected ✅")

            @client.on(events.NewMessage(incoming=True))
            async def handle(event):
                global last_message_time
                try:
                    sender = await event.get_sender()
                    if sender.username != YOUR_USERNAME:
                        return
                    user_text = event.raw_text
                    if not user_text:
                        return

                    last_message_time = datetime.now(IST)
                    logger.info(f"From Chaitu: {user_text}")

                    read_delay = random.uniform(3, 10) if wants_to_talk(user_text) else random.uniform(8, 35)
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
                    logger.info(f"Random: {reply[:80]}")
                except Exception as e:
                    logger.error(f"Random error: {e}")

            async def check_if_silent():
                try:
                    now = datetime.now(IST)
                    if not (9 <= now.hour <= 23):
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
                    reply = await call_groq([{"role": "user", "content": "Send Chaitu the sweetest good morning text. You just woke up. Short, natural, with emojis. Just the message."}])
                    if reply:
                        await client.send_message(YOUR_USERNAME, reply)
                except Exception as e:
                    logger.error(f"Morning error: {e}")

            async def send_good_night():
                try:
                    reply = await call_groq([{"role": "user", "content": "Send Chaitu a sweet good night text. You are about to sleep and missing him. Short, loving, with emojis. Just the message."}])
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
            logger.error(f"Crashed: {e} — restarting in 15s...")
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
