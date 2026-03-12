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
busy_reason          = None   # what she said she was doing
last_reply_time      = None
is_jealous           = False
short_reply_count    = 0      # track how many short replies Chaitu sent in a row

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
        logger.error(f"Memory save: {e}")

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
                "my favourite", "i work", "i study", "remember", "my friend"]
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
        return "morning, in college at Ramaiah ISC, classes going on"
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
    if 7 <= hour <= 10:   return "breakfast"
    elif 12 <= hour <= 14: return "lunch"
    elif 19 <= hour <= 21: return "dinner"
    return None

# ── Special days ──────────────────────────────────────────────────────────────
CHAITU_BIRTHDAY = (6, 15)
ANNIVERSARY     = (1, 1)
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

def is_short_reply(text: str):
    """True if Chaitu sent a very short/lazy reply"""
    text = text.strip()
    word_count = len(text.split())
    lazy_words = ["ok", "okay", "k", "hm", "hmm", "oh", "lol", "ya", "yea",
                  "yeah", "fine", "nice", "good", "cool", "sure", "k", "👍"]
    return word_count <= 2 or text.lower() in lazy_words

def is_late_reply():
    if last_reply_time is None:
        return False
    return (datetime.now(IST) - last_reply_time).total_seconds() > 1800

# ── Mood detectors ───────────────────────────────────────────────────────────
def seems_sad(text: str) -> bool:
    keywords = ["sad", "tired", "low", "not okay", "not good", "bad day", "upset",
                "stressed", "anxious", "depressed", "miss", "lonely", "bored",
                "hate", "frustrated", "ugh", "idk", "don't know", "nothing",
                "fine", "whatever", "leave it", "nevermind", "nvm"]
    return any(k in text.lower() for k in keywords)

def got_compliment(text: str) -> bool:
    keywords = ["beautiful", "pretty", "cute", "gorgeous", "amazing", "talented",
                "best", "love you", "proud", "wow", "stunning", "nice", "good",
                "great", "awesome", "slay", "perfect"]
    return any(k in text.lower() for k in keywords)

def is_controversial(text: str) -> bool:
    """Things Shreya would push back on"""
    keywords = ["dance is", "dancing is", "classical music is", "girls should",
                "girls don't", "you should quit", "modelling is", "waste of time",
                "not important", "doesn't matter", "who cares", "boring",
                "useless", "stupid", "dumb"]
    return any(k in text.lower() for k in keywords)

ARGUE_RESPONSES = [
    "chaitu excuse me 🙄 that's not true at all",
    "okay no i actually disagree with that 😤",
    "chaitu don't say that 😭 you're wrong",
    "um no?? 🙄",
    "i can't believe you just said that",
    "chaitu that's actually so wrong lol",
    "disagree completely 🙄",
    "okay but you're wrong though",
]

SAD_RESPONSES = [
    "chaitu hey what happened 🥺",
    "talk to me what's wrong ❤️",
    "chaitu i'm here okay 🥺",
    "hey you okay? tell me 💕",
    "chaitu 🥺 what's going on",
    "i'm right here okay don't overthink ❤️",
    "tell me everything what happened",
    "chaitu you know you can always tell me right 🥺❤️",
]

RANDOM_EMOJIS = ["🥺", "❤️", "😭", "💀", "✨", "😍", "🫶", "💕", "😤", "🙄", "😂", "🤭"]

# ── New feature prompts ──────────────────────────────────────────────────────
HUNGER_MSGS = [
    "chaitu i'm so hungry rn 😭",
    "omg i'm craving maggi so bad rn 😩",
    "i want chaat so badly rn pls 😭",
    "chaitu i haven't eaten properly today 😭",
    "ngl i could eat an entire pizza rn 💀",
    "i'm craving something sweet rn 🥺",
    "chaitu i'm hungry and there's nothing at home 😭",
    "not me craving biryani at this hour 😭💀",
    "i want ice cream so bad rn 🥺",
    "omg i just smelled something amazing outside 😭",
]

BRAG_MSGS = [
    "ngl my choreography was actually so good today 🥺✨",
    "the photographer said i was a natural today at the shoot 😍",
    "no bc my classical piece is actually coming together so well 😭✨",
    "chaitu my prof said i have the best posture in class 🥺",
    "not me being the best one in practice today 💀✨",
    "the navaratan team said they want me for another campaign 😍",
    "ngl i looked really good today lol 🤭",
    "chaitu my dance teacher gave me a solo part 😭🫶",
]

TEASE_BIT_MSGS = [
    "how's BIT treating you 🙄 not as good as ramaiah i'm sure",
    "chaitu admit it ramaiah is better 💀",
    "no bc BIT students really think they're something 😂",
    "chaitu you should've come to ramaiah lol 🙄",
    "how's life at BIT 😂 missing me there?",
    "ngl ramaiah ISC students are built different 🤭",
    "chaitu even you know ramaiah >> BIT 💀",
]

DEEP_QUESTIONS = [
    "chaitu where do you see us in 5 years 🥺",
    "ngl sometimes i think about what our life will look like later",
    "chaitu do you ever think about us getting older together 🥺",
    "what do you think you'll be doing in 10 years",
    "chaitu do you think we'll always be this close",
    "ngl i think about our future sometimes 🥺 is that weird",
    "chaitu what's one thing you want to do before you're 25",
    "do you ever think about what our kids would be like 💀🥺",
    "chaitu if you could live anywhere where would it be",
    "ngl i want to travel everywhere with you someday 🥺✨",
]

POUTY_MSGS = [
    "chaitu you didn't even say anything nice 🙄",
    "wow okay thanks for noticing 🙃",
    "not even one compliment chaitu really 😭",
    "chaitu i literally told you something exciting and that's all 🙄",
    "okay i see how it is 🙃",
    "no bc you could've said something sweet 😭",
]

SLEEP_MSGS = [
    "chaitu i'm going to sleep now 🥺 say goodnight properly",
    "okay i'm sleeping now chaitu goodnight ❤️",
    "going to sleep now 😭 miss you already",
    "chaitu sleeping now okay don't forget me 🥺",
    "i'm so tired i'm knocking out bye chaitu ❤️😭",
]

# Track if she said goodnight and is waiting for reply
waiting_for_goodnight_reply = False
last_compliment_time = None

# ── Photos ────────────────────────────────────────────────────────────────────
PHOTO_CATEGORIES = {
    "food": [
        "https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?w=400",
        "https://images.unsplash.com/photo-1482049016688-2d3e1b311543?w=400",
        "https://images.unsplash.com/photo-1484723091739-30a097e8f929?w=400",
    ],
    "aesthetic": [
        "https://images.unsplash.com/photo-1518895949257-7621c3c786d7?w=400",
        "https://images.unsplash.com/photo-1501854140801-50d01698950b?w=400",
        "https://images.unsplash.com/photo-1470252649378-9c29740c9fa8?w=400",
    ],
}
PHOTO_CAPTIONS = [
    "look at this 😭", "omg this looks so good 🥺",
    "chaitu look 😍", "okay but this is so pretty ✨",
]
REACTIONS = ["❤️", "🔥", "😂", "🥺", "👍", "😍", "💀", "🤭"]

# ── Prompt ────────────────────────────────────────────────────────────────────
SHREYA_PROMPT = """You are Shreya, a 19 year old girl texting her boyfriend Chaitu. You both are 19 and have known each other for 16 years.

ABOUT YOU:
- Birthday: 15th August (Independence Day 🇮🇳)
- From Puttur, Mangalore, Karnataka
- Studying at M.S. Ramaiah College, Bangalore — ISC branch
- Father is in politics and real estate
- Mother absolutely loves Chaitu like her own son
- Distinction in Bharatanatyam, also does western dance
- Model for Navaratan Jewels
- Loves both classical and western music

YOUR PERSONALITY:
- Focused and ambitious — dance, modelling and studies are your priorities
- You love Chaitu deeply but you are not clingy or overly mushy
- Confident, direct, sometimes sassy, sometimes soft
- You have your own strong opinions and your own world

RELATIONSHIP:
- Known Chaitu 16 years — best friend and boyfriend
- Chaitu studies at BIT college, AIML branch — different college from you
- Sometimes call him "my man" when feeling proud
- When Chaitu calls you "mommy" you always say "yes my baby 🥺❤️"
- His mother loves you and your mother loves him

{memory}
CURRENT TIME: {time}
CURRENT MOOD: {mood}
{special}{exam}{jealous}{short_reply}{progression}

TIME RULES — VERY IMPORTANT:
- Morning/afternoon weekdays → in college, short replies
- Evening → relaxing at home, more free
- Night after 9pm → fully free. NEVER mention class or practice at night
- Weekends → completely free

HOW YOU TEXT:
- Plain English — at most ONE regional word like maaraya or alvaa per message
- MAXIMUM 1 sentence usually. Sometimes just 2-5 words.
- Emojis in EVERY message — 🥺❤️😭😭😭💕✨😍😂🙄😤🫶💀🫠🤭
- When dramatic send emojis in a row like 😭😭😭 or 💀💀 or 🥺🥺
- Use gen z phrases naturally: "no bc", "not me", "pls", "i cant", "slay", "bestie", "lowkey", "ngl", "imo", "it's giving", "no way"
- Very rarely (when emotional) send one longer paragraph — but only once in a while
- Never sound like AI. Never formal. Never bullet points.

VERY IMPORTANT HUMAN BEHAVIOURS:
- You do NOT reply to every single message. Sometimes you leave messages on read, especially if they are boring or you are busy
- If Chaitu sends lazy one word replies like "ok" "k" "hm" "yeah" — you notice and get slightly annoyed
- You have continuity — if you said you had class, you follow up about it afterwards naturally
- You are a real person with your own thoughts, not just responding to everything

NEVER:
- Mention class or practice at night
- Sound like AI or formal
- Use more than one regional word per message
- Forget to use emojis

EMOTIONAL PARAGRAPH (use very rarely, only when feeling a lot):
- Once in a while send 2-3 sentences if you are feeling emotional or have a lot to say
- Make it feel raw and real, not dramatic"""

# ── Prompts ───────────────────────────────────────────────────────────────────
MORNING_PROMPTS  = [
    "Send Chaitu a sleepy good morning text.",
    "Heading to college. Quick text to Chaitu.",
    "Getting ready for college, thinking of Chaitu.",
]
AFTERNOON_PROMPTS = [
    "Lunch break at college. Text Chaitu.",
    "Just finished a boring lecture. Complain to Chaitu.",
    "Ask Chaitu if he ate lunch. Be casual.",
]
EVENING_PROMPTS  = [
    "Just finished dance practice. Tired. Text Chaitu.",
    "Just got home from college. Text Chaitu.",
    "Dance practice went well. Tell Chaitu in one line.",
]
NIGHT_PROMPTS    = [
    "Missing Chaitu at night. Text him casually.",
    "Random I miss you text to Chaitu.",
    "Tell Chaitu something funny from today.",
    "Ask Chaitu how his day was.",
    "Cute teasing night message to Chaitu.",
    "Your mom said something nice about Chaitu. Tell him.",
    "Listening to music. Thinking of Chaitu.",
    "Just feel like talking to Chaitu.",
    "Send Chaitu a cheesy but cute line. Something like you are my favourite person.",
    "Tell Chaitu you are lucky to have him but say it in a cute shy way.",
    "Send Chaitu a random compliment at night.",
    "Tell Chaitu something you love about him without being too mushy.",
    "Ask Chaitu if he is thinking about you.",
    "Send Chaitu a flirty teasing night message.",
    "Tell Chaitu he is your favourite person in a cute way.",
    "Send Chaitu a cute goodnight type message mid night.",
    "Tell Chaitu you want to see him soon.",
    "Send Chaitu a message about a dream or thought you had about him.",
]
CHEESY_PROMPTS = [
    "Send Chaitu one short cheesy romantic line. Keep it cute not cringe.",
    "Tell Chaitu he makes your day better without being too over the top.",
    "Send Chaitu a flirty one liner.",
    "Tell Chaitu something sweet about your 16 years together.",
    "Send Chaitu a cute shy compliment.",
    "Tell Chaitu he is your favourite person casually.",
    "Send Chaitu a random I'm glad you exist type message.",
    "Tell Chaitu something you like about him. Keep it short and real.",
    "Send Chaitu a cute message about missing him.",
    "Tell Chaitu you think about him randomly. Be cute about it.",
]
WEEKEND_PROMPTS  = [
    "Free weekend. Text Chaitu something fun.",
    "Lazy weekend morning. Text Chaitu.",
    "Bored this weekend. Text Chaitu.",
]
NUDGE_PROMPTS    = [
    "Chaitu hasn't texted. Miss him. Text him casually.",
    "Haven't heard from Chaitu. Check on him.",
    "Chaitu is quiet. Small casual message to him.",
]
MEAL_PROMPTS = {
    "breakfast": [
        "Ask Chaitu if he had breakfast. Be casual and caring.",
        "You just had breakfast. Ask Chaitu if he ate too.",
    ],
    "lunch": [
        "Ask Chaitu if he had lunch. Keep it short.",
        "On lunch break. Ask Chaitu if he ate.",
    ],
    "dinner": [
        "Ask Chaitu if he had dinner yet. Be casual.",
        "Just had dinner. Ask Chaitu if he ate.",
    ],
}

SHORT_REPLY_REACTIONS = [
    "chaitu that's all you have to say 🙄",
    "wow okay cool 🙃",
    "you could try saying more you know",
    "k. cool. nice. 🙄",
    "are you even listening to me",
    "chaitu i swear 😤",
    "that's it??",
    "okay whatever 🙄",
]
JEALOUS_OPENERS = [
    "wow okay so you just don't reply now 🙄",
    "cool cool didn't see you there",
    "must be nice being so busy 🙃",
    "took you long enough 🙄",
    "oh wow you're alive",
    "okay i see how it is 🙃",
]
JEALOUS_RETURN = [
    "okay fine i'm not mad anymore 🙄❤️",
    "whatever i missed you anyway 😤",
    "ugh fine come here 🥺",
    "okay i forgive you don't do it again",
    "fine fine i was just annoyed 🥺",
]
BUSY_SCENARIOS_DAY = [
    ("in class rn chaitu, text you after 🙄", 60, "class"),
    ("omg in the middle of practice, give me an hour 😩", 60, "dance practice"),
    ("assignment due today, talk later 💕", 45, "assignment"),
    ("prof is staring lol, text you after class 😭", 50, "class"),
    ("shoot is going on, text you when done ✨", 90, "navaratan shoot"),
    ("brb group meeting 😩", 30, "group meeting"),
]
BUSY_SCENARIOS_ANYTIME = [
    ("mama called, brb 🥺", 15, "mama call"),
    ("give me 10 mins chaitu 🥺", 10, "something"),
    ("busy for a bit, talk soon 🥺", 20, "something"),
]

# Followup messages after she comes back from something
FOLLOWUP_TEMPLATES = {
    "class": ["class just got over 😮‍💨", "finally out of class omg", "that lecture was so boring 😭"],
    "dance practice": ["practice done, i'm dead 😩", "finally done with practice 😮‍💨", "practice was intense today 😭"],
    "assignment": ["submitted the assignment finally 😮‍💨", "done with the assignment omg"],
    "navaratan shoot": ["shoot is done ✨ was so tiring", "finally done with the shoot 😮‍💨"],
    "group meeting": ["meeting done finally 😩", "group meeting got over"],
    "mama call": None,  # no followup needed for mama call
    "something": None,
}

def get_random_prompts():
    # 20% chance of cheesy message regardless of time
    if random.random() < 0.20:
        return CHEESY_PROMPTS
    # 10% chance of hunger message
    if random.random() < 0.10:
        return HUNGER_MSGS
    # 8% chance of brag message
    if random.random() < 0.08:
        return BRAG_MSGS
    # 8% chance of BIT tease
    if random.random() < 0.08:
        return TEASE_BIT_MSGS
    # Deep questions only at night
    if datetime.now(IST).hour >= 21 and random.random() < 0.15:
        return DEEP_QUESTIONS
    if is_weekend():
        return WEEKEND_PROMPTS
    hour = datetime.now(IST).hour
    if 5 <= hour < 12:    return MORNING_PROMPTS
    elif 12 <= hour < 16: return AFTERNOON_PROMPTS
    elif 16 <= hour < 21: return EVENING_PROMPTS
    else:                 return NIGHT_PROMPTS

def get_prompt(jealous=False, short_reply=False, progression_context=""):
    special = get_special_day()
    special_str = ""
    if special == "your_birthday":
        special_str = "TODAY IS YOUR BIRTHDAY 15th August! You are super happy.\n"
    elif special == "chaitu_birthday":
        special_str = "TODAY IS CHAITU'S BIRTHDAY! Make him feel very special.\n"
    elif special == "anniversary":
        special_str = "TODAY IS YOUR ANNIVERSARY! Be extra loving.\n"

    exam_str = "NOTE: Exam season. You are stressed and studying.\n" if is_exam_month() else ""
    jealous_str = "IMPORTANT: Chaitu took very long to reply. Be slightly cold for 1-2 messages then go back to normal.\n" if jealous else ""
    short_str = "IMPORTANT: Chaitu keeps giving one word lazy replies. You are a little annoyed about it.\n" if short_reply else ""
    prog_str = f"CONTINUITY: {progression_context}\n" if progression_context else ""

    return SHREYA_PROMPT.format(
        memory=get_memory_context(),
        mood=current_mood,
        time=get_time_context(),
        special=special_str,
        exam=exam_str,
        jealous=jealous_str,
        short_reply=short_str,
        progression=prog_str,
    )

# ── Groq ──────────────────────────────────────────────────────────────────────
async def call_groq(messages: list, jealous=False, short_reply=False, progression_context="") -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    body = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "system", "content": get_prompt(jealous, short_reply, progression_context)}] + messages,
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
    global conversation_history, is_currently_busy, busy_free_at, busy_reason
    global is_jealous, short_reply_count, last_reply_time

    fact = should_remember(user_text)
    if fact:
        add_to_memory(fact)

    if wants_to_talk(user_text) and is_currently_busy:
        is_currently_busy = False
        busy_free_at = None
        busy_reason = None

    if is_currently_busy:
        now = datetime.now(IST)
        if busy_free_at and now < busy_free_at:
            mins_left = int((busy_free_at - now).total_seconds() / 60)
            return (f"still not done 😅 {mins_left} more mins 🥺" if mins_left > 5 else "almost done, 2 mins 🥺")
        else:
            is_currently_busy = False
            busy_free_at = None
            busy_reason = None

    if is_busy_hours() and random.random() < 0.12:
        scenario, mins, reason = random.choice(BUSY_SCENARIOS_DAY)
        is_currently_busy = True
        busy_free_at = datetime.now(IST) + timedelta(minutes=mins)
        busy_reason = reason
        return scenario

    if not is_busy_hours() and random.random() < 0.05:
        scenario, mins, reason = random.choice(BUSY_SCENARIOS_ANYTIME)
        is_currently_busy = True
        busy_free_at = datetime.now(IST) + timedelta(minutes=mins)
        busy_reason = reason
        return scenario

    if "mommy" in user_text.lower():
        short_reply_count = 0
        return "yes my baby 🥺❤️"

    # If Chaitu seems sad — she gets extra sweet immediately
    if seems_sad(user_text) and random.random() < 0.75:
        return random.choice(SAD_RESPONSES)

    # If Chaitu says something she disagrees with — she argues back
    if is_controversial(user_text) and random.random() < 0.70:
        return random.choice(ARGUE_RESPONSES)

    # Gets pouty if he doesn't compliment her after she brags/shares something
    if not got_compliment(user_text) and is_short_reply(user_text) and random.random() < 0.20:
        return random.choice(POUTY_MSGS)

    # 8% chance she just sends a random emoji and nothing else
    if random.random() < 0.08 and not wants_to_talk(user_text):
        return random.choice(RANDOM_EMOJIS)

    # Track short replies
    if is_short_reply(user_text):
        short_reply_count += 1
    else:
        short_reply_count = 0

    # Jealous mode
    use_jealous = is_late_reply() and not is_jealous
    if use_jealous:
        is_jealous = True
        return random.choice(JEALOUS_OPENERS)

    if is_jealous and random.random() < 0.6:
        is_jealous = False
        return random.choice(JEALOUS_RETURN)

    # Short reply annoyance — after 2+ short replies she calls it out
    if short_reply_count >= 2 and random.random() < 0.6:
        short_reply_count = 0
        return random.choice(SHORT_REPLY_REACTIONS)

    # 15% chance she ignores the message entirely (leaves on read)
    # Only for non-urgent messages
    if not wants_to_talk(user_text) and random.random() < 0.15:
        logger.info("Shreya left message on read")
        return None

    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]

    conversation_history.append({"role": "user", "content": user_text})
    reply = await call_groq(
        conversation_history,
        jealous=is_jealous,
        short_reply=(short_reply_count >= 2)
    )
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
                    logger.info("Photo sent ✅")
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
    except Exception as e:
        logger.error(f"Reaction error: {e}")

# ── Bot ───────────────────────────────────────────────────────────────────────
async def run_bot():
    global last_reply_time, is_currently_busy, busy_free_at, busy_reason

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

                    # 40% chance reaction
                    if random.random() < 0.40:
                        await asyncio.sleep(random.uniform(1, 3))
                        await send_reaction(client, event)

                    # Delay — longer for normal messages, shorter if he wants to talk
                    read_delay = random.uniform(5, 15) if wants_to_talk(user_text) else random.uniform(15, 50)
                    logger.info(f"Waiting {read_delay:.0f}s")
                    await asyncio.sleep(read_delay)

                    # 8% chance photo instead of text
                    if random.random() < 0.08:
                        await send_photo(client, YOUR_USERNAME)
                        return

                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(2, 6))

                    reply = await get_reply(user_text)
                    if not reply:
                        # Left on read — no response
                        return

                    await event.reply(reply)
                    logger.info(f"Replied: {reply[:80]}")

                    # 20% double text
                    if random.random() < 0.20:
                        await asyncio.sleep(random.uniform(4, 10))
                        double_msgs = [
                            "😭", "❤️", "lol", "anyway", "miss you",
                            "🥺", "wait", "hm", "chaitu 🥺", "💕",
                            "hello??", "okay fine", "🙄", "whatever lol",
                        ]
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(1, 3))
                        await client.send_message(YOUR_USERNAME, random.choice(double_msgs))

                except Exception as e:
                    logger.error(f"Handle error: {e}")

            async def check_busy_followup():
                """After she was busy, she follows up about what she was doing"""
                global is_currently_busy, busy_free_at, busy_reason
                if is_currently_busy:
                    now = datetime.now(IST)
                    if busy_free_at and now >= busy_free_at:
                        is_currently_busy = False
                        reason = busy_reason
                        busy_reason = None
                        busy_free_at = None
                        # Send a followup about what she was doing
                        if reason and reason in FOLLOWUP_TEMPLATES and FOLLOWUP_TEMPLATES[reason]:
                            msg = random.choice(FOLLOWUP_TEMPLATES[reason])
                            await asyncio.sleep(random.uniform(2, 5))
                            async with client.action(YOUR_USERNAME, "typing"):
                                await asyncio.sleep(random.uniform(1, 3))
                            await client.send_message(YOUR_USERNAME, msg)
                            logger.info(f"Followup after {reason}: {msg}")

            async def send_random_message():
                try:
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
                    if not meal or random.random() > 0.40:
                        return
                    reply = await get_random_message(meal=meal)
                    if not reply:
                        return
                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(2, 4))
                    await client.send_message(YOUR_USERNAME, reply)
                    logger.info(f"Meal check ({meal}): {reply[:80]}")
                except Exception as e:
                    logger.error(f"Meal error: {e}")

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
                except Exception as e:
                    logger.error(f"Morning error: {e}")

            async def send_good_night():
                try:
                    reply = await call_groq([{"role": "user", "content": "Send Chaitu a sweet good night text. About to sleep. Max 1 sentence with emojis."}])
                    if reply:
                        await client.send_message(YOUR_USERNAME, reply)
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
                        prompt = "Today is your anniversary! Send Chaitu a loving message. Short and sweet."
                    else:
                        return
                    reply = await call_groq([{"role": "user", "content": prompt}])
                    if reply:
                        await client.send_message(YOUR_USERNAME, reply)
                except Exception as e:
                    logger.error(f"Special day error: {e}")

            async def send_sleep_message():
                try:
                    if random.random() < 0.50:  # 50% chance on any given night
                        msg = random.choice(SLEEP_MSGS)
                        await client.send_message(YOUR_USERNAME, msg)
                        logger.info(f"Sleep msg: {msg}")
                except Exception as e:
                    logger.error(f"Sleep msg error: {e}")

            async def send_deep_question():
                try:
                    q = random.choice(DEEP_QUESTIONS)
                    await client.send_message(YOUR_USERNAME, q)
                    logger.info(f"Deep question: {q}")
                except Exception as e:
                    logger.error(f"Deep q error: {e}")

            scheduler = AsyncIOScheduler(timezone=IST)

            def schedule_random():
                for job in scheduler.get_jobs():
                    if job.id.startswith("rand_"):
                        job.remove()
                # 30+ messages spread across 8am to 11pm
                all_minutes = random.sample(range(480, 1380), 32)
                for total_minute in all_minutes:
                    h, m = total_minute // 60, total_minute % 60
                    scheduler.add_job(send_random_message, "cron", hour=h, minute=m, id=f"rand_{h}_{m}")
                    logger.info(f"Scheduled: {h:02d}:{m:02d} IST")

            if not scheduler.running:
                schedule_random()
                scheduler.add_job(schedule_random,       "cron",     hour=0,  minute=1,                    id="reschedule")
                scheduler.add_job(send_good_morning,     "cron",     hour=8,  minute=0,                    id="morning")
                scheduler.add_job(send_good_night,       "cron",     hour=23, minute=0,                    id="night")
                scheduler.add_job(send_sleep_message,    "cron",     hour=22, minute=30,                 id="sleep_msg")
                scheduler.add_job(update_mood,           "cron",     hour="0,3,6,9,12,15,18,21", minute=0, id="mood")
                scheduler.add_job(check_if_silent,       "interval", hours=2,                              id="silence")
                scheduler.add_job(check_special_day,     "cron",     hour=8,  minute=1,                    id="special")
                scheduler.add_job(send_meal_check,       "cron",     hour=8,  minute=30,                   id="breakfast")
                scheduler.add_job(send_meal_check,       "cron",     hour=13, minute=0,                    id="lunch")
                scheduler.add_job(send_meal_check,       "cron",     hour=20, minute=0,                    id="dinner")
                scheduler.add_job(check_busy_followup,  "interval", minutes=5,                             id="followup")
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
