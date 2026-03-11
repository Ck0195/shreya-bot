import os
import asyncio
import random
import logging
import tempfile
import aiohttp
import pytz
import json
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
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

# ── Permanent Memory (saved to file, survives restarts) ──────────────────────
MEMORY_FILE = "/tmp/shreya_memory.json"

def load_memory():
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r") as f:
                return json.load(f)
    except:
        pass
    return {"facts": [], "last_updated": ""}

def save_memory(memory: dict):
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(memory, f)
    except Exception as e:
        logger.error(f"Memory save error: {e}")

def add_to_memory(fact: str):
    memory = load_memory()
    if fact not in memory["facts"]:
        memory["facts"].append(fact)
        if len(memory["facts"]) > 30:
            memory["facts"] = memory["facts"][-30:]
        memory["last_updated"] = datetime.now(IST).strftime("%Y-%m-%d")
        save_memory(memory)
        logger.info(f"Memory saved: {fact}")

def get_memory_context() -> str:
    memory = load_memory()
    if not memory["facts"]:
        return ""
    return "Things you remember about Chaitu: " + " | ".join(memory["facts"][-10:])

# ── Conversation history ──────────────────────────────────────────────────────
conversation_history = []
is_currently_busy = False
busy_free_at = None
last_message_time = None

# ── Special days ─────────────────────────────────────────────────────────────
CHAITU_BIRTHDAY = (3, 15)   # Change to Chaitu's actual birthday (month, day)
ANNIVERSARY = (1, 1)        # Change to your anniversary date (month, day)
SHREYA_BIRTHDAY = (8, 15)

def get_special_day():
    now = datetime.now(IST)
    m, d = now.month, now.day
    if (m, d) == SHREYA_BIRTHDAY:
        return "your_birthday"
    if (m, d) == CHAITU_BIRTHDAY:
        return "chaitu_birthday"
    if (m, d) == ANNIVERSARY:
        return "anniversary"
    return None

# ── Exam mode (Jan, Apr, Oct, Nov are common exam months) ────────────────────
def is_exam_month():
    return datetime.now(IST).month in [1, 4, 10, 11]

# ── Moods ─────────────────────────────────────────────────────────────────────
MOODS = ["happy", "loving", "excited", "focused", "tired", "playful", "missing you", "soft and clingy"]
current_mood = random.choice(MOODS)

def update_mood():
    global current_mood
    current_mood = random.choice(MOODS)
    logger.info(f"Mood: {current_mood}")

def get_time_context():
    hour = datetime.now(IST).hour
    if 5 <= hour < 9:
        return "early morning, just woke up, sleepy"
    elif 9 <= hour < 13:
        return "morning, in college at Ramaiah, classes going on"
    elif 13 <= hour < 15:
        return "afternoon, lunch break at college"
    elif 15 <= hour < 18:
        return "late afternoon, college wrapping up or dance practice"
    elif 18 <= hour < 21:
        return "evening, done with college, relaxing at home"
    else:
        return "night, at home, fully free, relaxed"

def is_weekend():
    return datetime.now(IST).weekday() >= 5

def is_busy_hours():
    if is_weekend():
        return False
    hour = datetime.now(IST).hour
    return 9 <= hour < 18

def wants_voice_note(text: str) -> bool:
    keywords = ["voice note", "voice", "audio", "speak", "talk to me",
                "send a note", "voice msg", "vm", "record", "sing"]
    return any(k in text.lower() for k in keywords)

def wants_to_talk(text: str) -> bool:
    keywords = ["talk", "free", "busy", "call", "time", "available", "where are you",
                "reply", "hello", "you there", "what are you doing", "baat",
                "listen", "i need you", "please", "miss you", "mommy", "speak", "chat"]
    return any(k in text.lower() for k in keywords)

def should_remember(text: str) -> str | None:
    """Extract things worth remembering from Chaitu's message"""
    triggers = ["my birthday", "i like", "i love", "i hate", "i am", "i'm",
                "my favourite", "i work", "i study", "i play", "i go to",
                "remember", "don't forget", "my friend", "my family"]
    text_lower = text.lower()
    for t in triggers:
        if t in text_lower:
            return text[:120]
    return None

# ── Photo URLs (curated aesthetic/food/nature — safe public domain) ───────────
PHOTO_CATEGORIES = {
    "food": [
        "https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?w=400",
        "https://images.unsplash.com/photo-1482049016688-2d3e1b311543?w=400",
        "https://images.unsplash.com/photo-1484723091739-30a097e8f929?w=400",
        "https://images.unsplash.com/photo-1567620905732-2d1ec7ab7445?w=400",
        "https://images.unsplash.com/photo-1540189549336-e6e99c3679fe?w=400",
    ],
    "aesthetic": [
        "https://images.unsplash.com/photo-1518895949257-7621c3c786d7?w=400",
        "https://images.unsplash.com/photo-1501854140801-50d01698950b?w=400",
        "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=400",
        "https://images.unsplash.com/photo-1470252649378-9c29740c9fa8?w=400",
        "https://images.unsplash.com/photo-1490750967868-88df5691cc51?w=400",
    ],
    "vibes": [
        "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=400",
        "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?w=400",
        "https://images.unsplash.com/photo-1500534314209-a25ddb2bd429?w=400",
        "https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?w=400",
    ]
}

PHOTO_CAPTIONS = [
    "look at this 😭",
    "omg this looks so good 🥺",
    "this reminds me of you idk why lol",
    "chaitu look 😍",
    "okay but this is so pretty ✨",
    "i want this so bad rn 😩",
    "doesn't this look amazing 🥺",
    "chaitu come here and see this",
]

# ── Reaction emojis ───────────────────────────────────────────────────────────
REACTIONS = ["❤️", "🔥", "😂", "🥺", "👍", "😍", "💀", "🤭"]

SHREYA_PROMPT = """You are Shreya, a 19 year old girl texting her boyfriend Chaitu. You are both 19 and have known each other for 16 years. Deeply in love and very comfortable with each other.

ABOUT YOU:
- Birthday: 15th August (Independence Day 🇮🇳)
- From Puttur, Mangalore, Karnataka
- Studying at M.S. Ramaiah College, Bangalore
- Father is in politics and real estate
- Mother absolutely loves Chaitu like her own son
- Distinction in Bharatanatyam, also does western dance
- Model for Navaratan Jewels
- Loves both classical and western music

RELATIONSHIP:
- Known Chaitu for 16 years — best friend and boyfriend
- Sometimes call him "my man" when feeling proud or loving
- When Chaitu calls you "mommy" you call him "my baby"
- Extremely comfortable, no filters

{memory}

CURRENT TIME: {time}
CURRENT MOOD: {mood}
{special}
{exam}

TIME RULES:
- Morning/afternoon weekdays — in college, short replies
- Evening — relaxing, more free
- Night after 9pm — fully free, NEVER mention class or practice
- Weekends — completely free

HOW YOU TEXT:
- Plain English, at most ONE regional word per message
- MAXIMUM 1 sentence. Sometimes just 2-5 words. Never long replies.
- Emojis naturally — 🥺❤️😭💕✨😍😂🙄😤🫶
- Never sound like AI, never formal

BEHAVIOURS:
- When Chaitu wants to talk — drop everything and give full attention
- Randomly check if he ate, miss him, compliment him
- Mention mom liking Chaitu sometimes
- Short, punchy, real texts only

NEVER:
- Write more than 1 sentence
- Mention class or practice at night
- Sound like AI or be formal
- Use more than one regional word per message"""

RANDOM_PROMPTS_MORNING = [
    "Send Chaitu a sleepy good morning text.",
    "You are heading to college. Quick text to Chaitu.",
    "Getting ready for college, thinking of Chaitu. Text him.",
]
RANDOM_PROMPTS_AFTERNOON = [
    "Lunch break at college. Text Chaitu.",
    "Just finished a boring lecture. Complain to Chaitu.",
    "Ask Chaitu if he ate lunch. Be caring.",
]
RANDOM_PROMPTS_EVENING = [
    "Just finished dance practice. Tired. Text Chaitu.",
    "Heading home from college. Text Chaitu.",
    "Just got home. Text Chaitu.",
]
RANDOM_PROMPTS_NIGHT = [
    "Missing Chaitu at night. Text him.",
    "Thinking of Chaitu. Send something sweet.",
    "Random I miss you or I love you text to Chaitu.",
    "Tell Chaitu something funny from today.",
    "Ask Chaitu how his day was.",
    "Sweet memory of Chaitu. Text him.",
    "Cute teasing night message to Chaitu.",
    "Tell Chaitu you are thinking about him.",
    "Your mom said something nice about Chaitu. Tell him.",
    "Listening to music. Thinking of Chaitu. Text him.",
]
RANDOM_PROMPTS_WEEKEND = [
    "Free weekend. Text Chaitu something fun.",
    "Lazy weekend. Text Chaitu.",
    "Weekend morning sweet text to Chaitu.",
    "Bored this weekend. Text Chaitu.",
]
NUDGE_PROMPTS = [
    "Chaitu hasn't texted. Miss him. Text sweetly.",
    "Haven't heard from Chaitu. Check on him cutely.",
    "Chaitu is quiet. Small sweet message.",
]
BUSY_SCENARIOS_DAY = [
    ("in class rn chaitu, text you after 🙄❤️", 60),
    ("omg in the middle of practice, give me an hour 😩", 60),
    ("assignment due today, talk later okay? 💕", 45),
    ("prof is staring lol, text you after class 😭", 50),
    ("shoot is going on, text you when done ✨", 90),
    ("brb group meeting 😩", 30),
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
    special = get_special_day()
    special_str = ""
    if special == "your_birthday":
        special_str = "TODAY IS YOUR BIRTHDAY (15th August)! You are super excited and happy today."
    elif special == "chaitu_birthday":
        special_str = "TODAY IS CHAITU'S BIRTHDAY! Wish him and make him feel very special."
    elif special == "anniversary":
        special_str = "TODAY IS YOUR ANNIVERSARY! Remind Chaitu and be extra loving."

    exam_str = "NOTE: It is exam season at Ramaiah. You are a bit stressed and studying a lot." if is_exam_month() else ""

    return SHREYA_PROMPT.format(
        memory=get_memory_context(),
        mood=current_mood,
        time=get_time_context(),
        special=special_str,
        exam=exam_str
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
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Groq failed: {e}")
        return None

async def get_reply(user_text: str):
    global conversation_history, is_currently_busy, busy_free_at

    # Save important things Chaitu says to memory
    fact = should_remember(user_text)
    if fact:
        add_to_memory(fact)

    if wants_to_talk(user_text) and is_currently_busy:
        is_currently_busy = False
        busy_free_at = None

    if is_currently_busy:
        now = datetime.now(IST)
        if busy_free_at and now < busy_free_at:
            mins_left = int((busy_free_at - now).total_seconds() / 60)
            return (f"still not done 😅 {mins_left} more mins 🥺" if mins_left > 5 else "almost done, 2 mins 🥺"), False
        else:
            is_currently_busy = False
            busy_free_at = None

    if is_busy_hours() and random.random() < 0.12:
        scenario, mins = random.choice(BUSY_SCENARIOS_DAY)
        is_currently_busy = True
        busy_free_at = datetime.now(IST) + timedelta(minutes=mins)
        return scenario, False

    if not is_busy_hours() and random.random() < 0.05:
        scenario, mins = random.choice(BUSY_SCENARIOS_ANYTIME)
        is_currently_busy = True
        busy_free_at = datetime.now(IST) + timedelta(minutes=mins)
        return scenario, False

    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]

    if "mommy" in user_text.lower():
        return "yes my baby 🥺❤️", False

    conversation_history.append({"role": "user", "content": user_text})
    reply = await call_groq(conversation_history)
    if not reply:
        return None, False
    conversation_history.append({"role": "assistant", "content": reply})

    use_voice = random.random() < 0.35 and len(reply) < 200
    return reply, use_voice

async def get_random_message(nudge=False):
    prompt = random.choice(NUDGE_PROMPTS if nudge else get_random_prompts())
    prompt += " Write ONLY the message with emojis. Max 1 sentence."
    reply = await call_groq([{"role": "user", "content": prompt}])
    if not reply:
        return None, False
    use_voice = random.random() < 0.30 and len(reply) < 200
    return reply, use_voice

async def send_voice(client, username, text):
    try:
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

async def send_photo(client, username):
    try:
        category = random.choice(list(PHOTO_CATEGORIES.keys()))
        url = random.choice(PHOTO_CATEGORIES[category])
        caption = random.choice(PHOTO_CAPTIONS)
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                        f.write(data)
                        tmp_path = f.name
                    await client.send_file(username, tmp_path, caption=caption)
                    os.remove(tmp_path)
                    logger.info(f"Photo sent: {category}")
                    return True
    except Exception as e:
        logger.error(f"Photo error: {e}")
    return False

async def send_reaction(client, event):
    try:
        emoji = random.choice(REACTIONS)
        await client(SendReactionRequest(
            peer=event.chat_id,
            msg_id=event.id,
            reaction=[ReactionEmoji(emoticon=emoji)]
        ))
        logger.info(f"Reaction sent: {emoji}")
    except Exception as e:
        logger.error(f"Reaction error: {e}")

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
                    logger.info(f"Chaitu: {user_text}")

                    # 40% chance she reacts to the message with an emoji
                    if random.random() < 0.40:
                        await asyncio.sleep(random.uniform(1, 3))
                        await send_reaction(client, event)

                    read_delay = random.uniform(3, 10) if wants_to_talk(user_text) else random.uniform(8, 35)
                    await asyncio.sleep(read_delay)

                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(3, 8))

                    # 10% chance she sends a photo instead of text
                    if random.random() < 0.10:
                        await send_photo(client, YOUR_USERNAME)
                        return

                    reply, use_voice = await get_reply(user_text)
                    if wants_voice_note(user_text):
                        use_voice = True
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
                    # 15% chance of sending a photo as a random message
                    if random.random() < 0.15:
                        await send_photo(client, YOUR_USERNAME)
                        return

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
                    reply = await call_groq([{"role": "user", "content": "Send Chaitu the sweetest good morning voice note style text. Short, loving, just woke up. Max 1 sentence."}])
                    if reply:
                        # Good morning as voice note
                        async with client.action(YOUR_USERNAME, "record-audio"):
                            await asyncio.sleep(random.uniform(2, 4))
                        success = await send_voice(client, YOUR_USERNAME, reply)
                        if not success:
                            await client.send_message(YOUR_USERNAME, reply)
                        logger.info("Good morning voice sent 🌅")
                except Exception as e:
                    logger.error(f"Morning error: {e}")

            async def send_good_night():
                try:
                    reply = await call_groq([{"role": "user", "content": "Send Chaitu a sweet good night text. About to sleep, missing him. Max 1 sentence with emojis."}])
                    if reply:
                        await client.send_message(YOUR_USERNAME, reply)
                        logger.info("Good night sent 🌙")
                except Exception as e:
                    logger.error(f"Night error: {e}")

            async def check_special_day():
                try:
                    special = get_special_day()
                    if not special:
                        return
                    if special == "chaitu_birthday":
                        reply = await call_groq([{"role": "user", "content": "Today is Chaitu's birthday! Send him the most heartfelt birthday wish. Short but very loving. Just the message."}])
                    elif special == "your_birthday":
                        reply = await call_groq([{"role": "user", "content": "Today is your birthday 15th August! Text Chaitu excitedly about your birthday morning. Short and happy."}])
                    elif special == "anniversary":
                        reply = await call_groq([{"role": "user", "content": "Today is your anniversary with Chaitu! Send him a loving anniversary message. Short and sweet."}])
                    else:
                        return
                    if reply:
                        await client.send_message(YOUR_USERNAME, reply)
                        logger.info(f"Special day message sent: {special}")
                except Exception as e:
                    logger.error(f"Special day error: {e}")

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
                scheduler.add_job(check_special_day, "cron", hour=8, minute=1, id="special_day")
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
