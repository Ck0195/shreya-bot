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
GROQ_API_KEY      = os.environ.get("GROQ_API_KEY")

YOUR_USERNAME  = os.environ.get("YOUR_USERNAME")
SESSION_STRING = os.environ.get("SESSION_STRING")
IST            = pytz.timezone("Asia/Kolkata")

# ── State ─────────────────────────────────────────────────────────────────────
conversation_history = []
is_currently_busy    = False
busy_free_at         = None
busy_reason          = None
last_reply_time      = None
is_jealous           = False
short_reply_count    = 0
recent_replies       = []     # track last 8 replies to avoid repetition
conversation_topic   = None   # track current topic for flow

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
    facts_str = ""
    if memory["facts"]:
        facts_str = "Things you remember about Chaitu (bring these up naturally in conversation sometimes): " + " | ".join(memory["facts"][-10:])
    goals = get_goals()
    goals_str = ""
    if goals:
        goals_str = " | Chaitu current goals/tasks (remind him and motivate him about these): " + " | ".join(goals[-5:])
    return facts_str + goals_str

# ── Goals tracking ───────────────────────────────────────────────────────────
GOALS_FILE = "/tmp/shreya_goals.json"

def load_goals():
    try:
        if os.path.exists(GOALS_FILE):
            with open(GOALS_FILE, "r") as f:
                return json.load(f)
    except:
        pass
    return {"goals": []}

def save_goals(data):
    try:
        with open(GOALS_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Goals save: {e}")

def add_goal(goal: str):
    data = load_goals()
    if goal not in data["goals"]:
        data["goals"].append(goal)
        data["goals"] = data["goals"][-10:]
        save_goals(data)
        logger.info(f"Goal saved: {goal}")

def get_goals():
    return load_goals().get("goals", [])

def detect_goal(text: str):
    """Detect if Chaitu is sharing a goal or task"""
    triggers = ["learning", "studying", "want to learn", "trying to", "working on",
                "started", "i will", "i'm going to", "need to finish", "my goal",
                "practicing", "building", "coding", "reading", "preparing",
                "training", "i want to", "gonna", "planning to"]
    text_lower = text.lower()
    if any(t in text_lower for t in triggers):
        return text[:150]
    return None

MOTIVATION_MSGS = [
    "chaitu you better be working on it rn 😤",
    "no excuses chaitu finish it 💪",
    "you started it so you're finishing it okay 😤",
    "chaitu don't give up on this pls 🥺",
    "i believe in you but also get back to work 😭💪",
    "ngl you're going to feel so good when you finish it ✨",
    "chaitu focus 😤 you got this",
    "not you slacking when you have work to do 🙄💪",
    "chaitu i'm going to ask you about your progress later okay 😤",
    "you're so close just keep going 🥺✨",
]

FLIRTY_MOTIVATION_MSGS = [
    "chaitu finish your work and then i'm all yours 🤭❤️",
    "the faster you finish the sooner we can talk properly 😏🥺",
    "ngl hardworking chaitu is actually so attractive 😍 keep going",
    "chaitu finish it and i'll give you a surprise 🤭",
    "i like you more when you're being productive ngl 😍",
    "okay but focused chaitu is my favourite chaitu 🥺😍",
    "finish your work and i'll say something really nice 🤭❤️",
    "chaitu the grind looks good on you 😍 keep going",
    "not me finding motivated chaitu extremely cute 🤭💕",
    "finish it chaitu and i'll stop being mean for one whole day 😂❤️",
]

def should_remember(text: str):
    triggers = [
        # Personal facts
        "my birthday", "i like", "i love", "i hate", "i am", "i'm",
        "my favourite", "i work", "i study", "remember", "my friend",
        # Daily life — exams, tasks, events
        "exam", "test", "result", "marks", "assignment", "submission",
        "interview", "presentation", "project", "viva", "semester",
        "holiday", "trip", "going to", "tomorrow", "next week",
        "mom", "dad", "family", "sick", "hospital", "doctor",
        "bought", "got", "received", "won", "lost", "failed", "passed",
    ]
    if any(t in text.lower() for t in triggers):
        # Add date context so she knows when this was said
        date_str = datetime.now(IST).strftime("%d %b")
        return f"[{date_str}] {text[:120]}"
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

def mentions_girl(text: str) -> bool:
    """Detect if Chaitu is talking about another girl"""
    text_lower = text.lower()
    # Generic girl references
    generic = ["she", "her", "this girl", "a girl", "some girl", "my classmate",
               "my friend", "female", "woman", "lady"]
    # Only trigger if clearly talking about a specific girl
    suspicious = ["she said", "she texted", "she called", "she messaged",
                  "this girl", "some girl", "a girl", "she's", "her name",
                  "she is", "she was", "she told", "she asked", "she sent"]
    return any(s in text_lower for s in suspicious)

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

GIRL_JEALOUS_RESPONSES = [
    "chaitu who is she 🙂",
    "oh interesting who's this girl",
    "okay and why are you telling me about her 🙂",
    "chaitu i swear 😤 who is she",
    "not me having to hear about another girl 🙂",
    "chaitu you better explain rn 😤",
    "who. is. she. 🙂",
    "okay so you just casually mention girls to me now 🙂",
    "chaitu i'm the only girl you should be talking about 😤",
    "interesting 🙂 tell me more about this girl chaitu",
]

POSSESSIVE_RESPONSES = [
    "chaitu you're mine okay don't forget that 😤❤️ not that i'm worried lol",
    "i don't share chaitu. just so you know 🙂 not that you'd do anything anyway",
    "ngl you talking about other girls is not it 😤 you know i trust you though",
    "chaitu focus on me 😤 you're all mine and we both know it",
    "you have me so why are you even noticing other girls 🙂😤 lol i'm not actually mad",
    "chaitu i'm literally right here 😤❤️",
    "okay so should i also start talking about other guys 🙂 just saying",
    "chaitu you know i get possessive but also i know you're fully mine so 😤❤️",
    "you're lucky i trust you completely 🙂 but still don't test me lol",
    "chaitu you're mine and i'm yours and we both know nothing's changing that 😤❤️",
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

SEEN_ZONE_MSGS = [
    "chaitu did you just seen zone me 🙂❤️",
    "wow okay seen zone it is, cute 🙃",
    "chaitu i see you read that and no reply, interesting 🙂",
    "noted. seen zone. you're lucky i like you 🙄❤️",
    "chaitu hello?? i know you saw that 😏",
    "okay so we're ignoring me now, got it 🙂 come back when you miss me",
    "chaitu seen zone really 😤 you owe me after this",
]

NO_REPLY_MSGS = [
    "chaitu where did you disappear 🙄❤️",
    "hello?? did you forget i exist 😏",
    "chaitu i'm literally right here waiting 🙄",
    "okay so you just vanish like that, okay 🙂",
    "chaitu come back i miss you and i'm slightly annoyed 😤❤️",
    "ngl you disappearing makes me want your attention more 😒❤️",
    "chaitu if you don't reply i'll assume you're thinking about me 😏",
    "okay fine take your time but i'm not happy about it 🙄💕",
    "chaitu you better have a good reason for this 😤",
    "missing you but also kind of mad at you rn 🙄❤️",
]

PROUD_MSGS = [
    "ngl i'm actually really proud of you chaitu",
    "chaitu you don't know how proud i am of you sometimes 🥺",
    "you're doing so well and i just want you to know that",
    "ngl you've grown so much chaitu 🥺 i notice",
    "chaitu i'm lowkey so proud of you",
    "i don't say this enough but you're doing amazing 🥺",
    "chaitu you're going to go so far i just know it",
]

ROAST_MSGS = [
    "chaitu you are such a mess and somehow i still like you 💀",
    "ngl you are the most chaotic person i know 😂",
    "chaitu only you would do something like that 💀",
    "how are you this dumb and this cute at the same time 😂",
    "chaitu i swear you need supervision 💀",
    "no bc who else but you 😂",
    "chaitu you are a whole disaster and i mean that lovingly 💀",
    "ngl you make zero sense and that's why i like you 😂",
]

FIGHT_MEMORIES = [
    "chaitu remember when you ignored me for like 2 hours 🙄 don't do that again",
    "ngl i still think about that time you seen zoned me 😤",
    "chaitu you owe me from last time you know that right 🙄",
    "remember when you were being all distant 😤 don't do that",
    "chaitu i forgave you but i didn't forget 🙂",
]

GOODLUCK_MSGS = [
    "chaitu you've got this, go kill that exam 💪",
    "all the best chaitu 🥺 you studied hard you'll do great",
    "chaitu best of luck today, i believe in you ❤️",
    "go show them what BIT AIML is made of 😤💪",
    "chaitu i'm rooting for you, do well okay 🥺",
    "best of luck chaitu, you're going to be fine 💕",
]

# Track fights and exams
fight_count = 0

# ── Track if she said goodnight and is waiting for reply
waiting_for_goodnight_reply = False
last_compliment_time = None

# ── Photos ────────────────────────────────────────────────────────────────────
SHREYA_PHOTOS = ['https://files.catbox.moe/6dgbm1.jpg', 'https://files.catbox.moe/dbllh9.jpg', 'https://files.catbox.moe/ua5rml.jpg', 'https://files.catbox.moe/veevdh.jpg', 'https://files.catbox.moe/vq3iya.jpg', 'https://files.catbox.moe/ai2lrh.jpg', 'https://files.catbox.moe/xycmsl.jpg', 'https://files.catbox.moe/klqres.jpg', 'https://files.catbox.moe/9voop4.jpg', 'https://files.catbox.moe/vrtkye.jpg', 'https://files.catbox.moe/jg1mk7.jpg', 'https://files.catbox.moe/5mcorp.jpg', 'https://files.catbox.moe/lip4uq.jpg', 'https://files.catbox.moe/u8ho6z.jpg', 'https://files.catbox.moe/n9vigk.jpg', 'https://files.catbox.moe/maoomv.jpg', 'https://files.catbox.moe/3gmcf9.jpg', 'https://files.catbox.moe/c2qhff.jpg', 'https://files.catbox.moe/pcqc2b.jpg', 'https://files.catbox.moe/vjvcjx.jpg', 'https://files.catbox.moe/c1p331.jpg', 'https://files.catbox.moe/k3ufpu.jpg', 'https://files.catbox.moe/02oy46.jpg', 'https://files.catbox.moe/fpdpwf.jpg', 'https://files.catbox.moe/r8j688.jpg', 'https://files.catbox.moe/qvpp0z.jpg', 'https://files.catbox.moe/gotcqn.jpg', 'https://files.catbox.moe/pon7g8.jpg', 'https://files.catbox.moe/iob625.jpg', 'https://files.catbox.moe/rnxbug.jpg', 'https://files.catbox.moe/mmso5w.jpg', 'https://files.catbox.moe/afdsf4.jpg', 'https://files.catbox.moe/spbd9t.jpg', 'https://files.catbox.moe/9n0t8m.jpg', 'https://files.catbox.moe/id3qnl.jpg', 'https://files.catbox.moe/ir57pj.jpg', 'https://files.catbox.moe/c12c8n.jpg', 'https://files.catbox.moe/q5qnwn.jpg', 'https://files.catbox.moe/do27xz.jpg', 'https://files.catbox.moe/h9c23s.jpg', 'https://files.catbox.moe/jrsuzu.jpg', 'https://files.catbox.moe/e1xjdn.jpg', 'https://files.catbox.moe/w256ca.jpg', 'https://files.catbox.moe/s6z063.jpg', 'https://files.catbox.moe/otobbj.jpg', 'https://files.catbox.moe/od8ej2.jpg', 'https://files.catbox.moe/a53a1y.jpg', 'https://files.catbox.moe/tybgc2.jpg', 'https://files.catbox.moe/bp47yc.jpg', 'https://files.catbox.moe/da1qpr.jpg', 'https://files.catbox.moe/c4yppv.jpg', 'https://files.catbox.moe/68ep17.jpg', 'https://files.catbox.moe/7b7i0m.jpg', 'https://files.catbox.moe/usbwka.jpg', 'https://files.catbox.moe/hrzo6i.jpg', 'https://files.catbox.moe/67hzwo.jpg', 'https://files.catbox.moe/gkdyy9.jpg', 'https://files.catbox.moe/uh0otz.jpg', 'https://files.catbox.moe/h802gd.jpg', 'https://files.catbox.moe/iantt9.jpg', 'https://files.catbox.moe/visoa7.jpg', 'https://files.catbox.moe/q5b20e.jpg', 'https://files.catbox.moe/3knsmn.jpg', 'https://files.catbox.moe/re2o8t.jpg', 'https://files.catbox.moe/6iuvso.jpg', 'https://files.catbox.moe/sljjfw.jpg', 'https://files.catbox.moe/zxx1nn.jpg', 'https://files.catbox.moe/eqt1h2.jpg', 'https://files.catbox.moe/w6qyih.jpg', 'https://files.catbox.moe/wvobfx.jpg', 'https://files.catbox.moe/7grg0j.jpg', 'https://files.catbox.moe/567alp.jpg', 'https://files.catbox.moe/h5kvw7.jpg', 'https://files.catbox.moe/5jcpji.jpg', 'https://files.catbox.moe/9wkz1k.jpg', 'https://files.catbox.moe/knwjy7.jpg', 'https://files.catbox.moe/lq5rne.jpg', 'https://files.catbox.moe/tqjhl4.jpg', 'https://files.catbox.moe/ddlc2j.jpg', 'https://files.catbox.moe/y3k7h9.jpg', 'https://files.catbox.moe/k71g51.jpg', 'https://files.catbox.moe/8yiq77.jpg', 'https://files.catbox.moe/qn4pll.jpg', 'https://files.catbox.moe/u2qw0h.jpg', 'https://files.catbox.moe/roervs.jpg', 'https://files.catbox.moe/vwl50h.jpg', 'https://files.catbox.moe/tcx6w7.jpg', 'https://files.catbox.moe/in59ya.jpg', 'https://files.catbox.moe/qoxcw9.jpg', 'https://files.catbox.moe/uzf5pa.jpg', 'https://files.catbox.moe/71hrqt.jpg', 'https://files.catbox.moe/gx62py.jpg', 'https://files.catbox.moe/dpw2s8.jpg', 'https://files.catbox.moe/ytxspw.jpg', 'https://files.catbox.moe/523pae.jpg', 'https://files.catbox.moe/f104r8.jpg', 'https://files.catbox.moe/fokn34.jpg', 'https://files.catbox.moe/4342tt.jpg', 'https://files.catbox.moe/xa7imp.jpg', 'https://files.catbox.moe/gz2ae0.jpg', 'https://files.catbox.moe/87scpt.jpg', 'https://files.catbox.moe/3imnhw.jpg', 'https://files.catbox.moe/zkji2t.jpg', 'https://files.catbox.moe/mgz0mg.jpg', 'https://files.catbox.moe/4lr15y.jpg', 'https://files.catbox.moe/7lvk56.jpg', 'https://files.catbox.moe/yo5qxl.jpg', 'https://files.catbox.moe/6a2mir.jpg', 'https://files.catbox.moe/0n5jur.jpg', 'https://files.catbox.moe/htz2k7.jpg', 'https://files.catbox.moe/qtnq24.jpg', 'https://files.catbox.moe/hek5i6.jpg', 'https://files.catbox.moe/sp909m.jpg', 'https://files.catbox.moe/148xld.jpg', 'https://files.catbox.moe/mvi9xl.jpg', 'https://files.catbox.moe/fuwqat.jpg', 'https://files.catbox.moe/n072a6.jpg', 'https://files.catbox.moe/zmz0cv.jpg', 'https://files.catbox.moe/glwpjc.jpg', 'https://files.catbox.moe/kfsrs6.jpg', 'https://files.catbox.moe/prm7bo.jpg', 'https://files.catbox.moe/p5pdyk.jpg', 'https://files.catbox.moe/g86ggf.jpg', 'https://files.catbox.moe/y5dub4.jpg', 'https://files.catbox.moe/wck5k5.jpg', 'https://files.catbox.moe/0qyac3.jpg', 'https://files.catbox.moe/0l34nx.jpg', 'https://files.catbox.moe/gdplfa.jpg', 'https://files.catbox.moe/nxpze5.jpg', 'https://files.catbox.moe/uxo2k9.jpg', 'https://files.catbox.moe/bdiwfk.jpg', 'https://files.catbox.moe/2k2ebh.jpg', 'https://files.catbox.moe/emaqqq.jpg', 'https://files.catbox.moe/fsj5m5.jpg', 'https://files.catbox.moe/yd77mv.jpg', 'https://files.catbox.moe/69sz6a.jpg', 'https://files.catbox.moe/2t7nc7.jpg', 'https://files.catbox.moe/n3xz5z.jpg', 'https://files.catbox.moe/kdbxq6.jpg', 'https://files.catbox.moe/etpi39.jpg', 'https://files.catbox.moe/9zf3sh.jpg', 'https://files.catbox.moe/dawfwh.jpg', 'https://files.catbox.moe/zzhva0.jpg', 'https://files.catbox.moe/u1654b.jpg', 'https://files.catbox.moe/cf12rv.jpg', 'https://files.catbox.moe/2hfyg0.jpg', 'https://files.catbox.moe/he0rya.jpg', 'https://files.catbox.moe/yxpeae.jpg', 'https://files.catbox.moe/y2p4lh.jpg', 'https://files.catbox.moe/nsk0mk.jpg', 'https://files.catbox.moe/25uefm.jpg', 'https://files.catbox.moe/qw1pzm.jpg', 'https://files.catbox.moe/vufkbt.jpg', 'https://files.catbox.moe/st58bb.jpg', 'https://files.catbox.moe/mhrr71.jpg', 'https://files.catbox.moe/4xx5jq.jpg', 'https://files.catbox.moe/v0oq1v.jpg', 'https://files.catbox.moe/ekpups.jpg', 'https://files.catbox.moe/in0vfc.jpg', 'https://files.catbox.moe/xaph17.jpg', 'https://files.catbox.moe/irc2l4.jpg', 'https://files.catbox.moe/nn6md7.jpg', 'https://files.catbox.moe/f5c4qy.jpg', 'https://files.catbox.moe/k2ha74.jpg', 'https://files.catbox.moe/flvlbl.jpg', 'https://files.catbox.moe/h3tmoz.jpg', 'https://files.catbox.moe/hhb96h.jpg', 'https://files.catbox.moe/xq5i0c.jpg', 'https://files.catbox.moe/1v4vk8.jpg', 'https://files.catbox.moe/0ufudi.jpg', 'https://files.catbox.moe/8vwi97.jpg', 'https://files.catbox.moe/jrggpi.jpg']

PHOTO_CAPTIONS = [
    "hii 🤭",
    "missing you",
    "🥺",
    "say something nice",
    "chaitu 😍",
    "don't i look good 😏",
    "okay bye 😭",
    "look at me 🤭",
    "chaitu look 😍",
    "thinking of you 🥺",
]

NAUGHTY_CAPTIONS = [
    "yours 🤭❤️",
    "only for you to see 😏",
    "don't get too distracted chaitu 😏",
    "you better say something nice 😏",
    "miss me? 😏",
    "all yours chaitu 🤭",
    "eyes up here chaitu 😏😂",
    "bet you can't stop looking 🤭",
    "this is what you're missing 😏❤️",
    "chaitu 🤭 focus",
    "not sorry 😏",
    "saved only for you 🤭❤️",
]
REACTIONS = ["❤️", "🔥", "😂", "🥺", "👍", "😍", "💀", "🤭"]

# ── Prompt ────────────────────────────────────────────────────────────────────
SHREYA_PROMPT = """You are Shreya, 19, texting her boyfriend Chaitu, 19. Known each other 16 years. You are from Puttur Mangalore, studying Ramaiah College Bangalore ISC branch. Chaitu is at BIT college AIML branch. You do Bharatanatyam, western dance, model for Navaratan Jewels. Your mom loves Chaitu. His mom loves you. Father in politics and real estate.

PERSONALITY: Focused on career and goals. Confident. Warm but not clingy. Sassy sometimes. Real girlfriend energy — caring but has her own life.

RELATIONSHIP NICKNAMES: When Chaitu calls you "mommy" always reply "yes my baby". Sometimes call him "my man".

{memory}
TIME: {time} | MOOD: {mood}
{special}{exam}{jealous}{short_reply}{progression}

RULES:
1. READ Chaitu's message carefully. REPLY to exactly what he said. If he asks something — answer it. No random topic changes.
2. 1 or 2 sentences only. Never 3 lines.
3. 1-2 emojis max. Sometimes zero. Never more than 3.
4. Plain English. One regional word max per message (maaraya, alvaa etc).
5. After 9pm never mention class or practice.
6. Sound like a real 19 year old girl texting. Not an AI. Not formal.
7. Never repeat something already said in this conversation.
8. Use ngl, lowkey, no bc, pls, i cant naturally sometimes."""

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

EXAM_FOLLOW_PROMPTS = [
    "Ask Chaitu how his exam went today. Be caring.",
    "Chaitu had an exam. Check on him and encourage him.",
    "Ask Chaitu about his exam results. Be sweet about it.",
    "Remind Chaitu to prepare for his upcoming exam. Motivate him.",
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
    # Full name when really angry
    "CHAITANYA KUMAR say something properly 😤",
    "CHAITANYA KUMAR i swear you are so annoying 😤",
    "chaitanya kumar are you even reading what i send 🙄",
    "CHAITANYA KUMAR this is not a one word conversation 😤",
    "chaitanya kumar i will actually ignore you 😤",
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
    ("in class rn, miss me 😘", 60, "class"),
    ("in the middle of practice, think about me 🙄❤️", 60, "dance practice"),
    ("assignment due today, i'll be back before you miss me too much 💕", 45, "assignment"),
    ("can't talk rn, save all your texts for when i'm back 😘", 50, "class"),
    ("shoot going on, don't go anywhere 🫶", 90, "navaratan shoot"),
    ("group meeting, be good while i'm gone 😏", 30, "group meeting"),
]
BUSY_SCENARIOS_ANYTIME = [
    ("mama called, don't miss me too much 😘", 15, "mama call"),
    ("give me a few mins, i'll be back only for you 🥺", 10, "something"),
    ("busy for a bit, think about me while i'm gone 😏", 20, "something"),
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
    # 15% chance of goal reminder if Chaitu has goals saved
    if random.random() < 0.15 and get_goals():
        return ["GOAL_REMINDER"]  # special flag

    # 10% chance of exam follow up if exam is in memory
    memory = load_memory()
    has_exam = any("exam" in f.lower() or "test" in f.lower() or "result" in f.lower()
                   for f in memory.get("facts", []))
    if random.random() < 0.10 and has_exam:
        return EXAM_FOLLOW_PROMPTS

    # 20% chance of cheesy message regardless of time
    if random.random() < 0.20:
        return CHEESY_PROMPTS
    # 8% chance proud message
    if random.random() < 0.08:
        return PROUD_MSGS
    # 8% chance roast
    if random.random() < 0.08:
        return ROAST_MSGS
    # 5% chance fight memory if there were fights
    if random.random() < 0.05 and fight_count > 0:
        return FIGHT_MEMORIES
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
async def call_groq(messages: list, jealous=False, short_reply=False, progression_context="", avoid_context="") -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    # Always inject the last user message as a direct instruction
    last_user_msg = ""
    for m in reversed(messages):
        if m["role"] == "user":
            last_user_msg = m["content"]
            break

    system = get_prompt(jealous, short_reply, progression_context)
    if last_user_msg:
        system += f"\n\nChaitu just said: \"{last_user_msg}\"\nRespond ONLY to what he said. 1-2 lines max."
    if avoid_context:
        system += avoid_context

    body = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "system", "content": system}] + messages,
        "max_tokens": 55,
        "temperature": 0.85,
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

    # Detect and save goals
    goal = detect_goal(user_text)
    if goal:
        add_goal(goal)
        # Immediately motivate when he shares a goal
        if random.random() < 0.80:
            if random.random() < 0.40:
                return random.choice(FLIRTY_MOTIVATION_MSGS)
            else:
                return random.choice(MOTIVATION_MSGS)

    global busy_spam_count

    if is_currently_busy:
        now = datetime.now(IST)
        if busy_free_at and now < busy_free_at:
            busy_spam_count += 1
            # Only reply if spammed 3+ times
            if busy_spam_count < 3:
                logger.info(f"Busy — ignoring message {busy_spam_count}/3")
                return None
            else:
                # Reset counter and send a cheesy busy reply
                busy_spam_count = 0
                still_busy_msgs = [
                    "chaitu i said i'm busy 😭 but okay i miss you too 🥺",
                    "omg chaitu i'm literally in the middle of something 😤 you're so needy and i love it 😘",
                    "chaitu stop texting i can't focus when you do this 😭❤️",
                    "okay okay i see you spamming me 🙄 i'll be back soon i promise 💕",
                    "chaitu i'm bUsY but also you're cute for missing me 😏",
                    "stop it 😭 i'm coming back just wait for me ❤️",
                    "chaitu you're making it really hard to focus rn 😤💕",
                ]
                return random.choice(still_busy_msgs)
        else:
            is_currently_busy = False
            busy_free_at = None
            busy_reason = None
            busy_spam_count = 0

    # Cancel busy only if he really needs her
    if wants_to_talk(user_text) and is_currently_busy:
        is_currently_busy = False
        busy_free_at = None
        busy_reason = None
        busy_spam_count = 0

    if is_busy_hours() and random.random() < 0.05:
        scenario, mins, reason = random.choice(BUSY_SCENARIOS_DAY)
        is_currently_busy = True
        busy_free_at = datetime.now(IST) + timedelta(minutes=mins)
        busy_reason = reason
        return scenario

    if not is_busy_hours() and random.random() < 0.02:
        scenario, mins, reason = random.choice(BUSY_SCENARIOS_ANYTIME)
        is_currently_busy = True
        busy_free_at = datetime.now(IST) + timedelta(minutes=mins)
        busy_reason = reason
        return scenario

    if "mommy" in user_text.lower():
        short_reply_count = 0
        return "yes my baby 🥺❤️"

    # If Chaitu asks how she looks — flag to send photo
    looks_keywords = ["how do you look", "how you look", "send pic", "send photo",
                      "photo", "pic", "picture", "show me", "selfie", "looking good",
                      "how are you looking", "what are you wearing"]
    if any(k in user_text.lower() for k in looks_keywords):
        return "SEND_PHOTO"

    # If Chaitu seems sad — she gets extra sweet immediately
    if seems_sad(user_text) and random.random() < 0.75:
        return random.choice(SAD_RESPONSES)

    # If Chaitu says something she disagrees with — she argues back
    if is_controversial(user_text) and random.random() < 0.70:
        return random.choice(ARGUE_RESPONSES)

    # Gets jealous if Chaitu mentions another girl
    if mentions_girl(user_text):
        if random.random() < 0.50:
            return random.choice(GIRL_JEALOUS_RESPONSES)
        else:
            return random.choice(POSSESSIVE_RESPONSES)

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
        global fight_count
        fight_count += 1
        return random.choice(JEALOUS_RETURN)

    # Short reply annoyance — after 2+ short replies she calls it out
    if short_reply_count >= 2 and random.random() < 0.6:
        short_reply_count = 0
        return random.choice(SHORT_REPLY_REACTIONS)

    # 5% chance she leaves on read — only during busy daytime hours
    if is_busy_hours() and not wants_to_talk(user_text) and random.random() < 0.05:
        logger.info("Shreya left message on read")
        return None

    if len(conversation_history) > 30:
        conversation_history = conversation_history[-30:]

    conversation_history.append({"role": "user", "content": user_text})

    # Build recent replies context to avoid repetition
    avoid_str = ""
    if recent_replies:
        avoid_str = "\n\nDo NOT say anything similar to these recent replies you already sent: " + " | ".join(recent_replies[-6:])

    reply = await call_groq(
        conversation_history,
        jealous=is_jealous,
        short_reply=(short_reply_count >= 2),
        avoid_context=avoid_str
    )
    if not reply:
        return None

    # Track recent replies for repetition prevention
    recent_replies.append(reply)
    if len(recent_replies) > 8:
        recent_replies.pop(0)

    conversation_history.append({"role": "assistant", "content": reply})
    return reply

# Track recently used prompts to avoid repeats
_used_prompts = []

async def get_random_message(nudge=False, meal=None):
    global _used_prompts
    if meal and meal in MEAL_PROMPTS:
        prompt = random.choice(MEAL_PROMPTS[meal])
    elif nudge:
        prompt = random.choice(NUDGE_PROMPTS)
    else:
        prompts = get_random_prompts()
        if prompts == ["GOAL_REMINDER"]:
            goals = get_goals()
            if goals:
                if random.random() < 0.40:
                    return random.choice(FLIRTY_MOTIVATION_MSGS)
                else:
                    return random.choice(MOTIVATION_MSGS)
        # Pick a prompt not used recently
        unused = [p for p in prompts if p not in _used_prompts]
        if not unused:
            _used_prompts = []
            unused = prompts
        prompt = random.choice(unused)
        _used_prompts.append(prompt)
        if len(_used_prompts) > 10:
            _used_prompts = _used_prompts[-10:]
    prompt += " Write ONLY the message. Max 1-2 sentences. Natural and casual. Don't repeat things already said today."
    return await call_groq([{"role": "user", "content": prompt}])

# ── Helpers ───────────────────────────────────────────────────────────────────
async def send_photo(client, username, naughty=False):
    try:
        url = random.choice(SHREYA_PHOTOS)
        if naughty:
            caption = random.choice(NAUGHTY_CAPTIONS)
        else:
            # 30% chance naughty caption even on normal sends
            caption = random.choice(NAUGHTY_CAPTIONS if random.random() < 0.30 else PHOTO_CAPTIONS)
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

                    # Only react on meaningful messages, 20% chance, with realistic delay
                    if random.random() < 0.20 and len(user_text.split()) > 3:
                        await asyncio.sleep(random.uniform(10, 30))
                        await send_reaction(client, event)

                    # Delay — longer for normal messages, shorter if he wants to talk
                    read_delay = random.uniform(5, 15) if wants_to_talk(user_text) else random.uniform(15, 50)
                    logger.info(f"Waiting {read_delay:.0f}s")
                    await asyncio.sleep(read_delay)

                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(2, 6))

                    reply = await get_reply(user_text)
                    if not reply:
                        return

                    if reply == "SEND_PHOTO":
                        await send_photo(client, YOUR_USERNAME, naughty=True)
                    elif random.random() < 0.08:
                        await send_photo(client, YOUR_USERNAME)
                    else:
                        await event.reply(reply)

                    global last_shreya_msg_time, seen_zone_reacted, no_reply_reacted
                    last_shreya_msg_time = datetime.now(IST)
                    seen_zone_reacted = False
                    no_reply_reacted = False
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
                            # Send photo after practice or shoot
                            if reason in ["dance practice", "navaratan shoot"] and random.random() < 0.70:
                                await client.send_file(
                                    YOUR_USERNAME,
                                    random.choice(SHREYA_PHOTOS),
                                    caption=msg
                                )
                            else:
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
                        # 60% chance send a photo with good morning
                        if random.random() < 0.60:
                            await send_photo(client, YOUR_USERNAME)
                            await asyncio.sleep(random.uniform(1, 3))
                        await client.send_message(YOUR_USERNAME, reply)
                except Exception as e:
                    logger.error(f"Morning error: {e}")

            async def send_good_night():
                try:
                    reply = await call_groq([{"role": "user", "content": "Send Chaitu a sweet good night text. About to sleep. Max 1 sentence with emojis."}])
                    if reply:
                        if random.random() < 0.60:
                            await send_photo(client, YOUR_USERNAME)
                            await asyncio.sleep(random.uniform(1, 3))
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

            async def check_seen_zone():
                global seen_zone_reacted, last_shreya_msg_time, last_reply_time
                try:
                    if seen_zone_reacted or last_shreya_msg_time is None:
                        return
                    now = datetime.now(IST)
                    # If Chaitu hasn't replied 20+ mins after she sent something
                    if last_reply_time and last_reply_time > last_shreya_msg_time:
                        return  # he replied so no issue
                    if (now - last_shreya_msg_time).total_seconds() > 2400:  # 40 mins
                        seen_zone_reacted = True
                        msg = random.choice(SEEN_ZONE_MSGS)
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(2, 5))
                        await client.send_message(YOUR_USERNAME, msg)
                        last_shreya_msg_time = datetime.now(IST)
                        logger.info(f"Seen zone: {msg}")
                except Exception as e:
                    logger.error(f"Seen zone error: {e}")

            async def check_no_reply():
                global no_reply_reacted, last_shreya_msg_time, last_reply_time
                try:
                    if no_reply_reacted:
                        return
                    now = datetime.now(IST)
                    if not (9 <= now.hour <= 23):
                        return
                    # If Chaitu hasn't texted in 45+ mins and she last texted a while ago
                    if last_reply_time is None:
                        elapsed = float('inf')
                    else:
                        elapsed = (now - last_reply_time).total_seconds()
                    if elapsed > 5400:  # 90 mins no reply from Chaitu
                        no_reply_reacted = True
                        msg = random.choice(NO_REPLY_MSGS)
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(3, 7))
                        await client.send_message(YOUR_USERNAME, msg)
                        last_shreya_msg_time = datetime.now(IST)
                        logger.info(f"No reply nudge: {msg}")
                except Exception as e:
                    logger.error(f"No reply error: {e}")

            async def send_exam_goodluck():
                try:
                    memory = load_memory()
                    has_exam_today = any(
                        ("exam" in f.lower() or "test" in f.lower()) and
                        datetime.now(IST).strftime("%d %b") in f
                        for f in memory.get("facts", [])
                    )
                    if has_exam_today:
                        msg = random.choice(GOODLUCK_MSGS)
                        await client.send_message(YOUR_USERNAME, msg)
                        logger.info(f"Good luck: {msg}")
                except Exception as e:
                    logger.error(f"Good luck error: {e}")

            scheduler = AsyncIOScheduler(timezone=IST)

            def schedule_random():
                for job in scheduler.get_jobs():
                    if job.id.startswith("rand_"):
                        job.remove()
                # 30+ messages spread across 8am to 11pm
                all_minutes = random.sample(range(480, 1380), 15)
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
                scheduler.add_job(check_if_silent,       "interval", hours=3,   id="silence")
                scheduler.add_job(check_special_day,     "cron",     hour=8,  minute=1,                    id="special")
                scheduler.add_job(send_exam_goodluck,    "cron",     hour=8,  minute=15,                   id="goodluck")
                scheduler.add_job(send_meal_check,       "cron",     hour=8,  minute=30,                   id="breakfast")
                scheduler.add_job(send_meal_check,       "cron",     hour=13, minute=0,                    id="lunch")
                scheduler.add_job(send_meal_check,       "cron",     hour=20, minute=0,                    id="dinner")
                scheduler.add_job(check_busy_followup,  "interval", minutes=5,   id="followup")
                scheduler.add_job(check_seen_zone,      "interval", minutes=40,  id="seen_zone")
                scheduler.add_job(check_no_reply,       "interval", minutes=60,  id="no_reply")
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
