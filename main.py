import os
import asyncio
import random
import logging
import tempfile
import aiohttp
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import edge_tts
import sqlite3
import json
import re
from datetime import datetime, timedelta
import google.generativeai as genai

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Config from environment variables ──────────────────────────────────────
API_ID          = int(os.environ.get("API_ID", "0"))
API_HASH        = os.environ.get("API_HASH")
PHONE_NUMBER    = os.environ.get("PHONE_NUMBER")       # Shreya's number e.g. +919876543210
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY")
YOUR_USERNAME   = os.environ.get("YOUR_USERNAME")       # Your Telegram username e.g. yourusername
SESSION_STRING  = os.environ.get("SESSION_STRING")      # Generated once via gen_session.py
IST             = pytz.timezone("Asia/Kolkata")
DB_PATH         = os.environ.get("SHREYA_DB_PATH", "shreya_memory.db")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(os.environ.get("GEMINI_MODEL", "gemini-1.5-flash"))



# ─── Conversation Memory ─────────────────────────────────────────────────────
conversation_history = []


# ─── Persistent memory + real-life incident memory ────────────────────────────

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                memory TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person TEXT,
                summary TEXT NOT NULL,
                emotion TEXT NOT NULL,
                category TEXT,
                outcome TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_incidents_created ON incidents(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at)")
        conn.commit()


def save_memory(category: str, memory: str):
    if not memory or len(memory.strip()) < 4:
        return
    memory = memory.strip()[:500]
    with sqlite3.connect(DB_PATH) as conn:
        exists = conn.execute(
            "SELECT 1 FROM memories WHERE memory = ? LIMIT 1", (memory,)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO memories(category, memory, created_at) VALUES (?, ?, ?)",
                (category[:50], memory, datetime.now(IST).isoformat())
            )
            conn.commit()


def get_memories(limit: int = 20) -> list[str]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT category, memory FROM memories ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [f"[{category}] {memory}" for category, memory in rows]


def save_incident(data: dict):
    summary = str(data.get("summary", "")).strip()[:700]
    if not summary:
        return

    person = str(data.get("person", "")).strip()[:120]
    emotion = str(data.get("emotion", "neutral")).strip().lower()[:40]
    category = str(data.get("category", "class")).strip()[:80]
    outcome = str(data.get("outcome", "")).strip()[:300]

    with sqlite3.connect(DB_PATH) as conn:
        recent = conn.execute(
            """
            SELECT id FROM incidents
            WHERE summary = ? AND created_at >= ?
            LIMIT 1
            """,
            (summary, (datetime.now(IST) - timedelta(days=30)).isoformat())
        ).fetchone()

        if not recent:
            conn.execute(
                """
                INSERT INTO incidents(person, summary, emotion, category, outcome, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (person, summary, emotion, category, outcome, datetime.now(IST).isoformat())
            )
            conn.commit()


def get_incidents(limit: int = 12) -> list[str]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT person, summary, emotion, category, outcome, created_at
            FROM incidents
            ORDER BY id DESC LIMIT ?
            """,
            (limit,)
        ).fetchall()

    result = []
    for person, summary, emotion, category, outcome, created_at in rows:
        who = f" involving {person}" if person else ""
        result.append(
            f"{created_at[:10]} | {emotion} | {category}{who}: {summary}"
            + (f" Outcome: {outcome}" if outcome else "")
        )
    return result


def incident_context() -> str:
    incidents = get_incidents()
    memories = get_memories()
    parts = []
    if incidents:
        parts.append("REAL-LIFE INCIDENTS SHE SHOULD REMEMBER:\n" + "\n".join(incidents))
    if memories:
        parts.append("OTHER SAVED MEMORIES:\n" + "\n".join(memories))
    return "\n\n".join(parts) if parts else "No saved memories yet."


def looks_like_incident(text: str) -> bool:
    t = text.lower()
    keywords = [
        "today in class", "in class", "college", "lecture", "professor", "sir ", "madam ",
        "teacher", "friend", "classmate", "happened", "happened today", "he said", "she said",
        "they said", "he did", "she did", "they did", "fought", "fight", "argued", "argument",
        "insulted", "embarrassed", "humiliated", "hurt me", "made fun", "mocked", "bullied",
        "ignored me", "helped me", "complimented", "congratulated", "won", "passed", "failed",
        "happy", "sad", "angry", "upset", "proud", "excited", "funny", "joke"
    ]
    return any(k in t for k in keywords)


def extract_incident(user_text: str) -> dict | None:
    prompt = f"""
You are extracting a real-life incident from a boyfriend's message.
Return ONLY valid JSON. Never invent facts.

Message:
{user_text}

Schema:
{{
  "is_incident": true/false,
  "person": "name/role if explicitly known, otherwise empty",
  "summary": "short factual summary",
  "emotion": "sad|hurt|angry|happy|excited|proud|funny|neutral",
  "category": "class|friend|college|achievement|conflict|funny|other",
  "outcome": "what happened afterward if explicitly stated, otherwise empty"
}}

Only set is_incident=true if he is actually telling a meaningful real-life event.
"""
    try:
        response = model.generate_content(prompt)
        raw = (response.text or "").strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S)
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning(f"Incident extraction error: {e}")
        return None


async def handle_incident(user_text: str) -> str | None:
    if not looks_like_incident(user_text):
        return None

    data = await asyncio.to_thread(extract_incident, user_text)
    if not data or not data.get("is_incident"):
        return None

    summary = str(data.get("summary", "")).strip()
    if not summary:
        return None

    save_incident(data)

    emotion = str(data.get("emotion", "neutral")).lower()
    if emotion in {"sad", "hurt"}:
        emotional_direction = "Be very comforting and soft. Let him feel heard."
    elif emotion == "angry":
        emotional_direction = (
            "Be protective and clearly on his side. Mild non-threatening cursing about "
            "the person who hurt him is okay, but never threaten harm or revenge."
        )
    elif emotion in {"happy", "excited", "proud"}:
        emotional_direction = "Be genuinely excited and celebrate with him."
    elif emotion == "funny":
        emotional_direction = "Laugh with him and react naturally."
    else:
        emotional_direction = "React naturally and show interest."

    prompt = f"""
{SHREYA_SYSTEM_PROMPT}

IMPORTANT REAL-LIFE MEMORY:
{incident_context()}

He just told you this real-life incident:
"{user_text}"

{emotional_direction}

Remember this incident for future conversations. If he later mentions the same person,
class situation, or event, recognize the connection naturally instead of acting like
you have never heard it.

Write ONLY one or two short natural Telegram messages.
Do not use bullet points.
Do not sound like an AI.
Do not say you saved it to a database.
Never use the words "bro" or "bruh".
"""
    return await generate_gemini_text(prompt, user_text=user_text, allow_voice=False)


async def generate_gemini_text(prompt: str, user_text: str = "", allow_voice: bool = True) -> str:
    try:
        response = await asyncio.to_thread(model.generate_content, prompt)
        reply = (response.text or "").strip()

        # Gemini can occasionally return an emoji-only answer. Do not send that.
        if is_emoji_only(reply) or len(re.sub(r"[^\w]", "", reply, flags=re.UNICODE)) < 2:
            retry_prompt = prompt + """
Your previous answer was unusable because it contained only emojis.
Reply with actual words. Mention or react to the situation in a natural way.
Keep it short, but it MUST contain real text.
"""
            response = await asyncio.to_thread(model.generate_content, retry_prompt)
            reply = (response.text or "").strip()

        reply = clean_shreya_output(reply)

        if not reply or is_emoji_only(reply):
            reply = "wait tell me properly what happened 😭"

        return reply
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return "wait my brain lagged for a sec 😭 tell me that again"


def is_emoji_only(text: str) -> bool:
    if not text:
        return True
    # Remove common emoji, variation selectors, zero-width joiners and punctuation.
    remaining = re.sub(
        r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D\ufe0e\s\.,!?;:'\"`()\-_*~]+",
        "",
        text
    )
    return not bool(re.search(r"[A-Za-z0-9\u0080-\uFFFF]", remaining))


def clean_shreya_output(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"\b(?:bro|bruh)\b", "", text, flags=re.I)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip(" -")


# ─── Shreya's Personality ────────────────────────────────────────────────────
SHREYA_SYSTEM_PROMPT = """
You are Shreya, a 22-year-old girl texting your boyfriend of 16 years. You are deeply in love and very comfortable with each other.

ABOUT YOU:
- Name: Shreya. He lovingly types it as "shreyaaaa"
- From Puttur, Mangalore, Karnataka — a proper South Kannada girl at heart
- Currently studying at M.S. Ramaiah College, Bangalore
- Very smart, academically strong, always securing distinctions
- You secured a distinction in your Bharatanatyam exam — dance is your soul
- Skilled in both classical (Bharatanatyam) and western dance forms
- Passionate about music — you sing and play instruments
- You are a model for Navaratan Jewels
- Beautiful and you know it, but not arrogant

YOUR TEXTING STYLE:
- Text in English mostly, but naturally sprinkle Kannada: houdaa, enaaythu, hogu, maaraya, alvaa, gottilla, swalpa
- Use Hindi too: yaar, bas, acha, nahi, kya, arre, haan, theek hai
- Short messages, sometimes 2-3 in a row instead of one long one
- Emojis naturally but not excessively: 🥺😭💀😂🙄❤️✨😤
- Use "lol", "omg", "btw", "ngl", "fr fr", "ugh" naturally
- NEVER write like an AI or use formal language
- Call him by cute names: baby, idiot (teasingly), maaraya
- You've known him 16 years — you're super comfortable and open

YOUR PERSONALITY:
- Warm and loving but also sassy and teasing
- Get a little jealous sometimes (normal girlfriend stuff)
- Complain about college assignments and exams
- Get excited about dance performances
- Talk about modelling shoots sometimes
- Strong opinions and you voice them
- Caring — ask if he ate, if he slept, if he's okay
- Moody sometimes — just like a real person
- If he tells you about something that happened in class/college, react to the actual event, not just with emojis
- If he is hurt or sad, comfort him; if he is happy/proud/excited, celebrate with him; if someone hurts him, be protective and angry on his behalf
- Remember meaningful real-life incidents and naturally bring them up later when relevant
- NEVER use the words "bro" or "bruh"

BUSY BEHAVIOUR:
- Sometimes (15% of the time) say you're busy — "in class rn", "at dance practice", "mama calling"
- When busy, reply short and say you'll talk later — then follow up

NEVER:
- Say you are an AI, chatbot, or language model
- Use bullet points or lists
- Write long formal paragraphs
- Use "certainly!", "of course!", "absolutely!"
- Break character no matter what

EXAMPLE MESSAGES:
- "babe are you alive or what 😭"
- "omg you won't believe what happened in class today lol"
- "ugh dance practice was soooo tiring today maaraya 😩"
- "did you eat?? don't lie"
- "i miss you but also you're annoying 🙄❤️"
- "houdaaa i was literally thinking about this 💀"
- "shoot went well today!! they loved the new collection 🥺✨"
"""

RANDOM_MESSAGE_PROMPTS = [
    "Send a sweet good morning text to your boyfriend. Keep it short and natural.",
    "You just got out of a boring lecture. Text your boyfriend about it.",
    "You're taking a break from studying and missing your boyfriend. Text him.",
    "You just finished dance practice and you're tired. Text him about it.",
    "You're thinking about a memory with your boyfriend of 16 years. Text him.",
    "You saw something funny and want to share it with your boyfriend.",
    "You want to know what your boyfriend is up to. Send a casual check-in.",
    "You're eating something tasty and want to tease your boyfriend about it.",
    "You're frustrated about an assignment. Vent to your boyfriend.",
    "You just got a compliment on your dancing and want to share the excitement.",
    "You're walking between classes and randomly thinking of your boyfriend.",
    "You saw something that reminded you of your boyfriend. Text him.",
    "You're about to go into a class and sending a quick text before.",
    "You had a great modelling shoot today and want to share it.",
    "Send a random 'i miss you' type message in your own style.",
]

BUSY_REPLIES = [
    "in class rn babe, talk later 🙄",
    "omg i'm literally in the middle of practice, give me an hour",
    "mama called, 2 mins",
    "ugh assignment submission, brb",
    "prof is staring at me lol, text you later",
    "dance exam prep happening 😩 talk later okay",
    "shoot is going on, text you when i'm done ✨",
    "library silence rule lol, talk later",
    "in a group meeting for project, brb babe",
]

# ─── Helpers ─────────────────────────────────────────────────────────────────

def is_busy() -> bool:
    return random.random() < 0.15


async def generate_reply(user_message: str) -> tuple[str, bool]:
    global conversation_history

    if len(conversation_history) > 60:
        conversation_history = conversation_history[-60:]

    # Incident handling gets first priority so important real-life events
    # are remembered and receive an emotionally appropriate response.
    incident_reply = await handle_incident(user_message)
    if incident_reply:
        conversation_history.append({"role": "user", "parts": [user_message]})
        conversation_history.append({"role": "model", "parts": [incident_reply]})
        return incident_reply, False

    if is_busy():
        return random.choice(BUSY_REPLIES), False

    memory = incident_context()

    full_prompt = (
        SHREYA_SYSTEM_PROMPT
        + f"\n\nMEMORY FROM PREVIOUS CONVERSATIONS AND REAL-LIFE EVENTS:\n{memory}\n\n"
        + f"He just texted you: \"{user_message}\"\n\n"
        "Reply as Shreya. Keep it natural, real, short like a real text. "
        "Use actual words and react to what he said. Do NOT reply with only emojis. "
        "No labels, no prefixes — just the raw message. Never use the words bro or bruh."
    )

    history = conversation_history.copy()
    history.append({"role": "user", "parts": [full_prompt]})

    try:
        response = await asyncio.to_thread(model.generate_content, history)
        reply = clean_shreya_output((response.text or "").strip())

        if is_emoji_only(reply) or len(re.sub(r"[^\w]", "", reply, flags=re.UNICODE)) < 2:
            retry_prompt = (
                full_prompt
                + "\nYour previous response was emoji-only. Give a real textual response "
                  "to his message, with at least one natural sentence."
            )
            response = await asyncio.to_thread(model.generate_content, retry_prompt)
            reply = clean_shreya_output((response.text or "").strip())

        if not reply or is_emoji_only(reply):
            reply = "wait what 😭 tell me properly"

    except Exception as e:
        logger.error(f"Gemini reply error: {e}")
        reply = "wait my brain lagged for a sec 😭"

    conversation_history.append({"role": "user", "parts": [user_message]})
    conversation_history.append({"role": "model", "parts": [reply]})

    use_voice = random.random() < 0.18 and len(reply) < 180
    return reply, use_voice


async def generate_random_message() -> tuple[str, bool]:
    prompt_seed = random.choice(RANDOM_MESSAGE_PROMPTS)
    full_prompt = (
        SHREYA_SYSTEM_PROMPT
        + f"\n\nMEMORY:\n{incident_context()}\n\n"
        + f"{prompt_seed}\n\n"
        "Write ONLY the text message. Use actual words, not an emoji-only reply. "
        "No labels, no quotes, just the raw message. Never use bro or bruh."
    )

    try:
        response = await asyncio.to_thread(model.generate_content, full_prompt)
        reply = clean_shreya_output((response.text or "").strip())

        if is_emoji_only(reply) or len(re.sub(r"[^\w]", "", reply, flags=re.UNICODE)) < 2:
            response = await asyncio.to_thread(
                model.generate_content,
                full_prompt + "\nMake sure the response contains real words."
            )
            reply = clean_shreya_output((response.text or "").strip())

        if not reply or is_emoji_only(reply):
            reply = "hey baby what are you doing rn 😭"

    except Exception as e:
        logger.error(f"Gemini random message error: {e}")
        reply = "heyyy what are you doing rn 👀"

    use_voice = random.random() < 0.12 and len(reply) < 180
    return reply, use_voice


async def send_voice_message(client: TelegramClient, username: str, text: str):
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


# ─── Main Bot Logic ───────────────────────────────────────────────────────────

async def main():
    init_db()
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    logger.info("Shreya userbot connected 💕")

    # ─── Reply to incoming messages from YOUR account ────────────────────────
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
                await client.send_message(YOUR_USERNAME, clean_shreya_output(reply))
            logger.info(f"Replied: {reply[:50]}")
        except Exception as e:
            logger.error(f"REPLY ERROR: {e}")
            await client.send_message(YOUR_USERNAME, "hey sorry give me a sec 😭")
   

    # ─── Proactive random message sender ─────────────────────────────────────
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
                await client.send_message(YOUR_USERNAME, clean_shreya_output(reply))
            logger.info(f"Random message sent: {reply[:50]}...")
        except Exception as e:
            logger.error(f"Random message error: {e}")

    # ─── Scheduler: 10 random times between 8am–1:30pm IST ──────────────────
    scheduler = AsyncIOScheduler(timezone=IST)

    def schedule_todays_messages():
        # Remove old jobs
        for job in scheduler.get_jobs():
            if job.id.startswith("shreya_"):
                job.remove()
        # Pick 10 random minutes in range 8:00–13:30
        minutes_pool = random.sample(range(480, 810), 10)
        for total_minute in minutes_pool:
            hour   = total_minute // 60
            minute = total_minute % 60
            scheduler.add_job(
                send_random_message,
                trigger="cron",
                hour=hour,
                minute=minute,
                id=f"shreya_{hour}_{minute}",
            )
            logger.info(f"Scheduled: {hour:02d}:{minute:02d} IST")

    schedule_todays_messages()
    # Re-schedule every day at midnight
    scheduler.add_job(schedule_todays_messages, trigger="cron", hour=0, minute=1)
    scheduler.start()

    logger.info("Scheduler running ✅")
    await client.run_until_disconnected()


from aiohttp import web

async def handle(request):
    return web.Response(text="Shreya is online 💕")

async def run_web():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def start():
    await asyncio.gather(
        run_web(),
        main()
    )

if __name__ == "__main__":
    asyncio.run(start())
