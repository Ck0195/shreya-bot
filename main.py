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



# ─── Conversation Memory ─────────────────────────────────────────────────────
conversation_history = []

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

    if is_busy():
        return random.choice(BUSY_REPLIES), False

    full_prompt = (
        SHREYA_SYSTEM_PROMPT
        + f"\n\nHe just texted you: \"{user_message}\"\n\n"
        "Reply as Shreya. Keep it natural, real, short like a real text. "
        "No labels, no prefixes — just the raw message."
    )
    history = conversation_history.copy()
    history.append({"role": "user", "parts": [full_prompt]})

    response = model.generate_content(history)
    reply = response.text.strip()

    conversation_history.append({"role": "user", "parts": [user_message]})
    conversation_history.append({"role": "model", "parts": [reply]})

    use_voice = random.random() < 0.18 and len(reply) < 180
    return reply, use_voice


async def generate_random_message() -> tuple[str, bool]:
    prompt_seed = random.choice(RANDOM_MESSAGE_PROMPTS)
    full_prompt = (
        SHREYA_SYSTEM_PROMPT
        + f"\n\n{prompt_seed}\n\n"
        "Write ONLY the text message. No labels, no quotes, just the raw message."
    )
    response = model.generate_content(full_prompt)
    reply = response.text.strip()
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
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    logger.info("Shreya userbot connected 💕")

    # ─── Reply to incoming messages from YOUR account ────────────────────────
    @client.on(events.NewMessage(incoming=True, from_users=YOUR_USERNAME))
    async def handle_message(event):
        user_text = event.raw_text

        # Human-like delay before even starting to type
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
                await client.send_message(YOUR_USERNAME, reply)
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


if __name__ == "__main__":
    asyncio.run(main())
