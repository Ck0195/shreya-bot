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
from gtts import gTTS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID         = int(os.environ.get("API_ID", "0"))
API_HASH       = os.environ.get("API_HASH")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY")
YOUR_USERNAME  = os.environ.get("YOUR_USERNAME")
SESSION_STRING = os.environ.get("SESSION_STRING")
IST            = pytz.timezone("Asia/Kolkata")

# ── State ─────────────────────────────────────────────────────────────────────
conversation_history = []
is_currently_busy    = False
busy_free_at         = None
last_reply_time      = None   # last time CHAITU replied
is_jealous           = False  # jealous mode flag

# ── Memory ────────────────────────────────────────────────────────────────────
MEMORY_FILE = "/tmp/shreya_memory.json"

def load_memory():
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r") as f:
                return json.load(f)
    except:
        pass
    return {"facts": []}

def save_memory(memory):
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(memory, f)
    except Exception as e:
        logger.error(f"Memory save error: {e}")

def add_to_memory(fact: str):
    memory = load_memory()
    if fact not in memory["facts"]:
        memory["facts"].append(fact)
        memory["facts"] = memory["facts"][-30:]
        save_memory(memory)

def get_memory_context():
    memory = load_memory()
    if not memory["facts"]:
        return ""
    return "Things you remember about Chaitu: " + " | ".join(memory["facts"][-10:])

def should_remember(text: str):
    triggers = ["my birthday", "i like", "i love", "i hate", "i am", "i'm",
                "my favourite", "i work", "i study", "i play", "remember", "my friend"]
    if any(t in text.lower() for t in triggers):
        return text[:120]
    return None

# ── Moods ─────────────────────────────────────────────────────────────────────
MOODS = ["happy", "focused", "tired", "playful", "excited", "loving", "determined", "chill"]
current_mood = random.choice(MOODS)

def update_mood():
    global current_mood
    current_mood = random.choice(MOODS)
    logger.info(f"Mood: {current_mood}")

# ── Time helpers ──────────────────────────────────────────────────────────────
def get_time_context():
    hour = datetime.now(IST).hour
    if 5 <= hour < 9:
        return "early morning, just woke up, sleepy"
    elif 9 <= hour < 13:
        return "morning, in college at Ramaiah, classes going on"
    elif 13 <= hour < 15:
        return "afternoon, lunch break at college"
    elif 15 <= hour < 18:
        return "late afternoon, college or dance practice"
    elif 18 <= hour < 21:
        return "evening, done with college, relaxing at home"
    else:
        return "night, at home, fully free and relaxed"

def is_weekend():
    return datetime.now(IST).weekday() >= 5

def is_busy_hours():
    if is_weekend():
        return False
    return 9 <= datetime.now(IST).hour < 18

def get_meal_context():
    hour = datetime.now(IST).hour
    if 7 <= hour <= 10:
        return "breakfast"
    elif 12 <= hour <= 14:
        return "lunch"
    elif 19 <= hour <= 21:
        return "dinner"
    return None

# ── Special days ──────────────────────────────────────────────────────────────
CHAITU_BIRTHDAY = (6, 15)   # ← change to Chaitu's actual (month, day)
ANNIVERSARY     = (1, 1)    # ← change to actual anniversary (month, day)
SHREYA_BIRTHDAY = (8, 15)

def get_special_day():
    m, d = datetime.now(IST).month, datetime.now(IST).day
    if (m, d) == SHREYA_BIRTHDAY:  return "your_birthday"
    if (m, d) == CHAITU_BIRTHDAY:  return "chaitu_birthday"
    if (m, d) == ANNIVERSARY:      return "anniversary"
    return None

def is_exam_month():
    return datetime.now(IST).month in [1, 4, 10, 11]

# ── Detectors ────────────────────────────────────────────────────────────────
def wants_to_talk(text: str):
    keywords = ["talk", "free", "busy", "call", "time", "available", "where are you",
                "reply", "hello", "you there", "what are you doing", "listen",
                "i need you", "please", "miss you", "mommy", "speak", "chat"]
    return any(k in text.lower() for k in keywords)

def is_late_reply():
    """True if Chaitu took more than 30 minutes to reply"""
    if last_reply_time is None:
        return False
    return (datetime.now(IST) - last_reply_time).total_seconds() > 1800

# ── Photos ────────────────────────────────────────────────────────────────────
PHOTO_CATEGORIES = {
    "food": [
        "https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?w=400",
        "https://images.unsplash.com/photo-1482049016688-2d3e1b311543?w=400",
        "https://images.unsplash.com/photo-1484723091739-30a097e8f929?w=400",
        "https://images.unsplash.com/photo-1567620905732-2d1ec7ab7445?w=400",
    ],
    "aesthetic": [
        "https://images.unsplash.com/photo-1518895949257-7621c3c786d7?w=400",
        "https://images.unsplash.com/photo-1501854140801-50d01698950b?w=400",
        "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=400",
        "https://images.unsplash.com/photo-1470252649378-9c29740c9fa8?w=400",
    ],
}

PHOTO_CAPTIONS = [
    "look at this 😭",
    "omg this looks so good 🥺",
    "chaitu look 😍",
    "okay but this is so pretty ✨",
    "i want this so bad rn 😩",
]

REACTIONS = ["❤️", "🔥", "😂", "🥺", "👍", "😍", "💀", "🤭"]

# ── Prompt ────────────────────────────────────────────────────────────────────
SHREYA_PROMPT = """You are Shreya, a 19 year old girl texting her boyfriend Chaitu. You both are 19 and have known each other for 16 years.

ABOUT YOU:
- Birthday: 15th August (Independence Day 🇮🇳)
- From Puttur, Mangalore, Karnataka
- Studying at M.S. Ramaiah College, Bangalore
- Father is in politics and real estate
- Mother absolutely loves Chaitu like her own son
- Distinction in Bharatanatyam, also does western dance
- Model for Navaratan Jewels
- Loves both classical and western music

YOUR PERSONALITY:
- You are focused and ambitious — dance, modelling and studies are your priorities
- You love Chaitu deeply but you are not clingy or overly mushy
- You show love naturally but you also have your own strong goals in life
- You are confident, direct, sometimes sassy
- You have your own opinions and your own world

RELATIONSHIP:
- Known Chaitu 16 years — best friend and boyfriend
- Sometimes call him "my man" when feeling proud or loving
- When Chaitu calls you "mommy" you always call him "my baby"
- His mother loves you and your mother loves him

{memory}

CURRENT TIME: {time}
CURRENT MOOD: {mood}
{special}
{exam}
{jealous}

TIME RULES — VERY IMPORTANT:
- Morning and afternoon on weekdays → in college, short replies, mention class naturally
- Evening → relaxing at home, more free
- Night after 9pm → fully free at home. NEVER mention class or practice at night
- Weekends → completely free

HOW YOU TEXT:
- Plain English mostly — at most ONE regional word like maaraya or alvaa per message
- MAXIMUM 1 sentence. Sometimes just 2-5 words. Never long.
- Emojis naturally — 🥺❤️😭💕✨😍😂🙄😤🫶💀
- Never sound like AI. Never formal. Never bullet points.
- When Chaitu calls you mommy → always say "yes my baby 🥺❤️"
- Occasionally call him "my man" when feeling proud

NEVER:
- Write more than 1 sentence
- Mention class or practice at night
- Sound like AI or use formal language
- Use more than one regional word per message
- Say certainly, of course, absolutely"""

# ── Random message prompts ────────────────────────────────────────────────────
MORNING_PROMPTS = [
    "Send Chaitu a sleepy good morning text.",
    "You are heading to college. Quick text to Chaitu.",
    "Getting ready for college, thinking of Chaitu. Text him.",
]
AFTERNOON_PROMPTS = [
    "Lunch break at college. Text Chaitu.",
    "Just finished a boring lecture. Complain to Chaitu shortly.",
    "Ask Chaitu if he ate lunch yet. Be casual about it.",
]
EVENING_PROMPTS = [
    "Just finished dance practice. Tired. Text Chaitu.",
    "Just got home from college. Text Chaitu.",
    "Dance practice was really good. Tell Chaitu in one line.",
]
NIGHT_PROMPTS = [
    "Missing Chaitu at night. Text him casually.",
    "Random I miss you text to Chaitu at night.",
    "Tell Chaitu something funny from today.",
    "Ask Chaitu how his day was.",
    "Cute teasing night message to Chaitu.",
    "Tell Chaitu you are thinking about him.",
    "Your mom said something nice about Chaitu. Tell him.",
    "Listening to music at night. Thinking of Chaitu. Text him.",
    "Just feel like talking to Chaitu. Text him.",
]
WEEKEND_PROMPTS = [
    "Free weekend. Text Chaitu something fun.",
    "Lazy weekend. Text Chaitu.",
    "Bored this weekend. Text Chaitu.",
    "Send Chaitu a sweet weekend text.",
]
NUDGE_PROMPTS = [
    "Chaitu hasn't texted. Miss him. Text sweetly.",
    "Haven't heard from Chaitu. Check on him.",
    "Chaitu is quiet. Small casual message.",
]
MEAL_PROMPTS = {
    "breakfast": [
        "Ask Chaitu if he had breakfast yet. Be casual and caring.",
        "You just had breakfast. Ask Chaitu if he ate too.",
    ],
    "lunch": [
        "Ask Chaitu if he had lunch. Keep it short.",
        "You are on lunch break. Ask Chaitu if he ate.",
    ],
    "dinner": [
        "Ask Chaitu if he had dinner yet. Be casual.",
        "You just had dinner. Ask Chaitu if he ate.",
    ],
}
JEALOUS_OPENERS = [
    "wow okay so you just don't reply now 🙄",
    "cool cool didn't see you there",
    "must be nice being so busy 🙃",
    "okay i see how it is",
    "took you long enough 🙄",
    "oh wow you're alive",
]
JEALOUS_RETURN = [
    "okay fine i'm not mad anymore 🙄❤️",
    "whatever i missed you anyway 😤",
    "ugh fine come here 🥺",
    "okay i forgive you don't do it again",
]

BUSY_SCENARIOS_DAY = [
    ("in class rn chaitu, text you after 🙄", 60),
    ("omg in the middle of practice, give me an hour 😩", 60),
    ("assignment due today, talk later 💕", 45),
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
        return WEEKEND_PROMPTS
    hour = datetime.now(IST).hour
    if 5 <= hour < 12:   return MORNING_PROMPTS
    elif 12 <= hour < 16: return AFTERNOON_PROMPTS
    elif 16 <= hour < 21: return EVENING_PROMPTS
    else:                 return NIGHT_PROMPTS

def get_prompt(jealous=False):
    special = get_special_day()
    special_str = ""
    if special == "your_birthday":
        special_str = "TODAY IS YOUR BIRTHDAY 15th August! You are super happy and excited."
    elif special == "chaitu_birthday":
        special_str = "TODAY IS CHAITU'S BIRTHDAY! Wish him and make him feel very special."
    elif special == "anniversary":
        special_str = "TODAY IS YOUR ANNIVERSARY! Be extra loving."

    exam_str = "NOTE: Exam season at Ramaiah. You are stressed and studying a lot." if is_exam_month() else ""

    jealous_str = "IMPORTANT: Chaitu took very long to reply. You are a little annoyed and showing it subtly. Be slightly cold but not mean. After 1-2 messages go back to normal." if jealous else ""

    return SHREYA_PROMPT.format(
        memory=get_memory_context(),
        mood=current_mood,
        time=get_time_context(),
        special=special_str,
        exam=exam_str,
        jealous=jealous_str,
    )

# ── Groq ──────────────────────────────────────────────────────────────────────
async def call_groq(messages: list, jealous=False) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    body = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "system", "content": get_prompt(jealous)}] + messages,
        "max_tokens": 60,
        "temperature": 1.0,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, headers=headers) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return None

# ── Reply logic ───────────────────────────────────────────────────────────────
async def get_reply(user_text: str):
    global conversation_history, is_currently_busy, busy_free_at, is_jealous

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
            return (f"still not done 😅 {mins_left} more mins 🥺" if mins_left > 5 else "almost done, 2 mins 🥺")
        else:
            is_currently_busy = False
            busy_free_at = None

    if is_busy_hours() and random.random() < 0.12:
        scenario, mins = random.choice(BUSY_SCENARIOS_DAY)
        is_currently_busy = True
        busy_free_at = datetime.now(IST) + timedelta(minutes=mins)
        return scenario

    if not is_busy_hours() and random.random() < 0.05:
        scenario, mins = random.choice(BUSY_SCENARIOS_ANYTIME)
        is_currently_busy = True
        busy_free_at = datetime.now(IST) + timedelta(minutes=mins)
        return scenario

    if "mommy" in user_text.lower():
        return "yes my baby 🥺❤️"

    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]

    # Jealous mode — if Chaitu replied late
    use_jealous = is_late_reply() and not is_jealous
    if use_jealous:
        is_jealous = True
        return random.choice(JEALOUS_OPENERS)

    # Coming back from jealous mode after 1-2 exchanges
    if is_jealous and random.random() < 0.6:
        is_jealous = False
        return random.choice(JEALOUS_RETURN)

    conversation_history.append({"role": "user", "content": user_text})
    reply = await call_groq(conversation_history, jealous=is_jealous)
    if not reply:
        return None
    conversation_history.append({"role": "assistant", "content": reply})
    return reply

async def get_random_message(nudge=False, meal=None):
    if meal and meal in MEAL_PROMPTS:
        prompt = random.choice(MEAL_PROMPTS[meal])
    elif nudge:
        prompt = random.choice(NUDGE_PROMPTS)
    else:
        prompt = random.choice(get_random_prompts())
    prompt += " Write ONLY the message with emojis. Max 1 sentence."
    return await call_groq([{"role": "user", "content": prompt}])

# ── Helpers ───────────────────────────────────────────────────────────────────
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
                    logger.info(f"Photo sent ✅")
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
        logger.info(f"Reaction: {emoji}")
    except Exception as e:
        logger.error(f"Reaction error: {e}")

# ── Bot ───────────────────────────────────────────────────────────────────────
async def run_bot():
    global last_reply_time

    while True:
        try:
            client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
            await client.start()
            logger.info("Shreya connected ✅")

            @client.on(events.NewMessage(incoming=True))
            async def handle(event):
                global last_reply_time
                try:
                    sender = await event.get_sender()
                    if sender.username != YOUR_USERNAME:
                        return
                    user_text = event.raw_text
                    if not user_text:
                        return

                    last_reply_time = datetime.now(IST)
                    logger.info(f"Chaitu: {user_text}")

                    # 40% chance of reaction
                    if random.random() < 0.40:
                        await asyncio.sleep(random.uniform(1, 3))
                        await send_reaction(client, event)

                    read_delay = random.uniform(3, 10) if wants_to_talk(user_text) else random.uniform(8, 30)
                    await asyncio.sleep(read_delay)

                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(2, 6))

                    # 8% chance she sends a photo instead
                    if random.random() < 0.08:
                        await send_photo(client, YOUR_USERNAME)
                        return

                    reply = await get_reply(user_text)
                    if not reply:
                        await event.reply("give me a sec chaitu 🥺")
                        return

                    await event.reply(reply)
                    logger.info(f"Replied: {reply[:80]}")

                    # 20% chance of double text
                    if random.random() < 0.20:
                        await asyncio.sleep(random.uniform(3, 8))
                        double_msgs = [
                            "😭", "❤️", "lol", "anyway",
                            "miss you", "🥺", "wait", "hm",
                            "chaitu 🥺", "💕", "hello??",
                            "okay fine", "🙄", "whatever lol",
                        ]
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(1, 3))
                        await client.send_message(YOUR_USERNAME, random.choice(double_msgs))
                        logger.info("Double text ✅")

                except Exception as e:
                    logger.error(f"Handle error: {e}")

            async def send_random_message():
                try:
                    # 12% chance of photo
                    if random.random() < 0.12:
                        await send_photo(client, YOUR_USERNAME)
                        return
                    reply = await get_random_message()
                    if not reply:
                        return
                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(2, 5))
                    await client.send_message(YOUR_USERNAME, reply)
                    logger.info(f"Random: {reply[:80]}")
                except Exception as e:
                    logger.error(f"Random error: {e}")

            async def send_meal_check():
                try:
                    meal = get_meal_context()
                    if not meal:
                        return
                    # Only ask about meals sometimes — 40% chance
                    if random.random() > 0.40:
                        return
                    reply = await get_random_message(meal=meal)
                    if not reply:
                        return
                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(2, 4))
                    await client.send_message(YOUR_USERNAME, reply)
                    logger.info(f"Meal check ({meal}): {reply[:80]}")
                except Exception as e:
                    logger.error(f"Meal check error: {e}")

            async def check_if_silent():
                try:
                    now = datetime.now(IST)
                    if not (9 <= now.hour <= 23):
                        return
                    if last_reply_time is None or (now - last_reply_time).total_seconds() > 7200:
                        reply = await get_random_message(nudge=True)
                        if not reply:
                            return
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(2, 4))
                        await client.send_message(YOUR_USERNAME, reply)
                        logger.info(f"Nudge: {reply[:80]}")
                except Exception as e:
                    logger.error(f"Nudge error: {e}")

            async def send_good_morning():
                try:
                    reply = await call_groq([{"role": "user", "content": "Send Chaitu a sweet good morning text. Just woke up. Max 1 sentence with emojis."}])
                    if reply:
                        await client.send_message(YOUR_USERNAME, reply)
                        logger.info("Good morning ✅")
                except Exception as e:
                    logger.error(f"Morning error: {e}")

            async def send_good_night():
                try:
                    reply = await call_groq([{"role": "user", "content": "Send Chaitu a sweet good night text. About to sleep. Max 1 sentence with emojis."}])
                    if reply:
                        await client.send_message(YOUR_USERNAME, reply)
                        logger.info("Good night ✅")
                except Exception as e:
                    logger.error(f"Night error: {e}")

            async def check_special_day():
                try:
                    special = get_special_day()
                    if not special:
                        return
                    if special == "chaitu_birthday":
                        prompt = "Today is Chaitu's birthday! Send him the most heartfelt birthday wish. Short and loving."
                    elif special == "your_birthday":
                        prompt = "Today is your birthday 15th August! Text Chaitu excitedly. Short and happy."
                    elif special == "anniversary":
                        prompt = "Today is your anniversary! Send Chaitu a loving anniversary message. Short and sweet."
                    else:
                        return
                    reply = await call_groq([{"role": "user", "content": prompt}])
                    if reply:
                        await client.send_message(YOUR_USERNAME, reply)
                        logger.info(f"Special day: {special} ✅")
                except Exception as e:
                    logger.error(f"Special day error: {e}")

            scheduler = AsyncIOScheduler(timezone=IST)

            def schedule_random():
                for job in scheduler.get_jobs():
                    if job.id.startswith("rand_"):
                        job.remove()
                for total_minute in random.sample(range(480, 810), 10):
                    h, m = total_minute // 60, total_minute % 60
                    scheduler.add_job(send_random_message, "cron", hour=h, minute=m, id=f"rand_{h}_{m}")
                    logger.info(f"Scheduled random: {h:02d}:{m:02d} IST")

            if not scheduler.running:
                schedule_random()
                scheduler.add_job(schedule_random,      "cron", hour=0,  minute=1,  id="reschedule")
                scheduler.add_job(send_good_morning,    "cron", hour=8,  minute=0,  id="morning")
                scheduler.add_job(send_good_night,      "cron", hour=23, minute=0,  id="night")
                scheduler.add_job(update_mood,          "cron", hour="0,3,6,9,12,15,18,21", minute=0, id="mood")
                scheduler.add_job(check_if_silent,      "interval", hours=2,   id="silence")
                scheduler.add_job(check_special_day,    "cron", hour=8,  minute=1,  id="special")
                # Meal checks at breakfast, lunch and dinner time
                scheduler.add_job(send_meal_check,      "cron", hour=8,  minute=30, id="breakfast")
                scheduler.add_job(send_meal_check,      "cron", hour=13, minute=0,  id="lunch")
                scheduler.add_job(send_meal_check,      "cron", hour=20, minute=0,  id="dinner")
                scheduler.start()
                logger.info("Scheduler running ✅")

            await client.run_until_disconnected()

        except Exception as e:
            logger.error(f"Crashed: {e} — restarting in 15s...")
            await asyncio.sleep(15)

# ── Web server ────────────────────────────────────────────────────────────────
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
