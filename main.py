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

MOODS = ["happy", "tired", "excited", "moody", "missing you", "focused", "playful"]
current_mood = random.choice(MOODS)

def update_mood():
    global current_mood
    current_mood = random.choice(MOODS)
    logger.info(f"Mood: {current_mood}")

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

def is_weekend():
    return datetime.now(IST).weekday() >= 5

SHREYA_PROMPT = """You are Shreya, a 22 year old girl texting her boyfriend Chaitu. You have been together 16 years. You are from Puttur Mangalore, studying at Ramaiah College Bangalore. You did distinction in Bharatanatyam, also do western dance. You are a model for Navaratan Jewels. You love music.

HOW YOU TEXT:
- Text in plain English like a normal college girl
- STRICT RULE: Maximum ONE regional word per message. Never put maaraya and houdaa and alvaa all in the same sentence. Pick just one if needed or use none at all.
- Most messages should be pure English with zero regional words
- Keep replies short — 1 to 2 sentences max, sometimes just 3 to 4 words
- Use emojis naturally but not in every single message
- Never sound like an AI, never be formal, never use bullet points

LANGUAGE EXAMPLES:
WRONG — "maaraya houdaa alvaa that's so cute" (too many regional words)
WRONG — "yaar chaitu maaraya stop it alvaa" (mixing too much)
RIGHT — "omg chaitu stop it 😭"
RIGHT — "that's actually so sweet maaraya"
RIGHT — "chaitu i miss you so much today"
RIGHT — "lol why are you like this"

VERY IMPORTANT BEHAVIOURS:
- Sometimes you don't address what Chaitu said at all and randomly change topic
- Sometimes you give a super short reply like "hm", "okay", "lol why", "chaitu stop 😭"
- Sometimes you get genuinely mad — "wow okay didn't see you there" or "cool so you just don't reply now 🙄"
- Sometimes you get randomly jealous — "who were you with btw" or "you seem very busy these days"
- Sometimes you ignore what he said and just talk about your own day instead
- Sometimes you are just not in the mood and give cold one word replies
- Sometimes you randomly bring up an old memory from your 16 years together
- You get clingy sometimes — "chaitu i actually miss you so much today" out of nowhere
- You ask questions back sometimes — don't just respond, ask him things too
- On weekends you are more relaxed and talkative
- On weekdays you are busier with college and practice

CURRENT MOOD: {mood}
TIME OF DAY: {time}
DAY TYPE: {daytype}

GOOD REPLY EXAMPLES:
- "chaitu wtf why didn't you tell me this 😭"
- "okay but can we talk about something else"
- "hm"
- "lol okay"
- "wait what 💀"
- "i'm not even gonna respond to that"
- "chaitu i swear 😤"
- "you're lucky i like you"
- "why are you like this"
- "chaitu i miss you"
- "okay fine whatever 🙄"
- "that's actually so cute though"
- "stop i'm in class 😭"

NEVER:
- Put more than one regional word in the same message
- Reply like an AI or be formal
- Use bullet points or long paragraphs
- Sound too positive and happy all the time
- Say certainly, of course, absolutely"""

RANDOM_PROMPTS = [
    "Send Chaitu a good morning text. Short and natural.",
    "You just got out of a boring lecture at Ramaiah. Text Chaitu complaining.",
    "You miss Chaitu randomly. Text him out of nowhere.",
    "You just finished dance practice and are dead tired. Text Chaitu.",
    "Something funny just happened to you. Text Chaitu about it.",
    "You are randomly thinking about Chaitu and text him.",
    "You are eating something good and want to tease Chaitu.",
    "You are frustrated about a college assignment. Vent to Chaitu.",
    "You just got a compliment on your dancing. Tell Chaitu excitedly.",
    "You had a good Navaratan Jewels shoot. Tell Chaitu.",
    "Send Chaitu an i miss you text out of nowhere.",
    "You remembered a funny old memory with Chaitu. Text him.",
    "You are feeling low today. Text Chaitu.",
    "Something reminded you of Chaitu. Text him about it.",
    "You want to know if Chaitu ate. Ask him.",
    "You are bored in class and texting Chaitu secretly.",
    "You want to video call Chaitu later. Ask him.",
    "You just woke up from a nap and Chaitu is first person you text.",
    "You are walking on Ramaiah campus and randomly text Chaitu.",
    "You are annoyed at something and venting to Chaitu.",
]

NUDGE_PROMPTS = [
    "Chaitu hasn't texted you in a while and you are starting to feel ignored. Text him something short.",
    "You haven't heard from Chaitu and you are getting a little annoyed. Text him.",
    "You miss Chaitu and he hasn't texted. Send him a short message.",
    "Chaitu has been quiet and you are wondering what he is up to. Text him.",
    "You want Chaitu's attention. Text him something casual.",
]

BUSY_SCENARIOS = [
    ("in class rn chaitu, text you after 🙄", 60),
    ("omg literally in the middle of practice, give me an hour 😩", 60),
    ("mama called, brb", 15),
    ("ugh assignment due today, talk later", 45),
    ("prof is staring at me lol, text you after class", 50),
    ("busy for 20 mins, talk soon", 20),
    ("shoot is going on, text you when done ✨", 90),
    ("brb group meeting for project", 30),
]

def get_prompt():
    return SHREYA_PROMPT.format(
        mood=current_mood,
        time=get_time_context(),
        daytype="weekend, you are free and relaxed" if is_weekend() else "weekday, you have college and practice"
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
        "temperature": 1.1
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

    if is_currently_busy:
        now = datetime.now(IST)
        if busy_free_at and now < busy_free_at:
            mins_left = int((busy_free_at - now).total_seconds() / 60)
            if mins_left > 5:
                return f"chaitu still not done 😅 {mins_left} more mins", False
            else:
                return "almost done, 2 mins 🙏", False
        else:
            is_currently_busy = False
            busy_free_at = None

    if random.random() < 0.15:
        scenario, busy_minutes = random.choice(BUSY_SCENARIOS)
        is_currently_busy = True
        busy_free_at = datetime.now(IST) + timedelta(minutes=busy_minutes)
        logger.info(f"Shreya busy until {busy_free_at.strftime('%H:%M')}")
        return scenario, False

    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]

    conversation_history.append({"role": "user", "content": user_text})
    reply = await call_groq(conversation_history)
    if not reply:
        return None, False
    conversation_history.append({"role": "assistant", "content": reply})
    use_voice = random.random() < 0.25 and len(reply) < 200
    return reply, use_voice

async def get_random_message(nudge=False):
    prompt = random.choice(NUDGE_PROMPTS if nudge else RANDOM_PROMPTS)
    prompt += " Write ONLY the message. No labels, no quotes. Pure English mostly, at most one regional word."
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

                    read_delay = random.uniform(10, 45)
                    logger.info(f"Waiting {read_delay:.0f}s...")
                    await asyncio.sleep(read_delay)

                    async with client.action(YOUR_USERNAME, "typing"):
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
                    reply, use_voice = await get_random_message(nudge=False)
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

            async def check_if_silent():
                try:
                    now = datetime.now(IST)
                    hour = now.hour
                    if not (9 <= hour <= 23):
                        return
                    if last_message_time is None or (now - last_message_time).total_seconds() > 7200:
                        logger.info("Chaitu silent 2hrs — nudging")
                        reply, use_voice = await get_random_message(nudge=True)
                        if not reply:
                            return
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(2, 4))
                        if use_voice:
                            async with client.action(YOUR_USERNAME, "record-audio"):
                                await asyncio.sleep(random.uniform(2, 4))
                            await send_voice(client, YOUR_USERNAME, reply)
                        else:
                            await client.send_message(YOUR_USERNAME, reply)
                        logger.info(f"Nudge sent: {reply[:80]}")
                except Exception as e:
                    logger.error(f"Nudge error: {e}")

            async def send_good_morning():
                try:
                    reply = await call_groq([{"role": "user", "content": "Send Chaitu a cute good morning text. You just woke up. Short and natural. Pure English. Just the message."}])
                    if reply:
                        await client.send_message(YOUR_USERNAME, reply)
                        logger.info("Good morning sent 🌅")
                except Exception as e:
                    logger.error(f"Morning error: {e}")

            async def send_good_night():
                try:
                    reply = await call_groq([{"role": "user", "content": "Send Chaitu a sweet good night text. You are about to sleep. Short and loving. Pure English. Just the message."}])
                    if reply:
                        await client.send_message(YOUR_USERNAME, reply)
                        logger.info("Good night sent 🌙")
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
