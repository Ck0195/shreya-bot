import os
import asyncio
import random
import logging
import aiohttp
import pytz
import json
import re
import sqlite3
import time
import difflib
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

# Set DATA_DIR to a persistent volume path on your host so memory survives restarts.
DATA_DIR = os.environ.get("DATA_DIR", "/tmp")
os.makedirs(DATA_DIR, exist_ok=True)
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"

# State
conversation_history   = []     # rolling [{"role": "user"/"assistant", "content": ...}]
MAX_HISTORY            = 30
recent_replies         = []     # last few Shreya replies, for duplicate detection
MAX_RECENT_REPLIES     = 12
is_currently_busy      = False
busy_free_at           = None
busy_reason            = None
last_reply_time        = None   # time of Chaitu's most recent message
prev_reply_time        = None   # time of Chaitu's message BEFORE the most recent one
is_jealous             = False
short_reply_count      = 0
last_shreya_msg_time   = None
seen_zone_reacted      = False
no_reply_reacted       = False
busy_spam_count        = 0
angry_mode             = False
angry_stage            = 0      # 0=angry, 1=emotional, 2=forgiving, 3=back to love
care_mode              = False  # fever/sick mode — keep off
fight_count            = 0
_remembered_girl_names = []
_used_prompts          = []
latest_event_id        = 0      # id of the newest incoming message (used to drop stale replies)
pending_replies        = 0      # number of incoming messages currently being processed

# ── Text matching helper (word boundaries, so "pic" doesn't match "topic") ───
def has_any(text, phrases):
    t = text.lower()
    return any(re.search(r"\b" + re.escape(p) + r"\b", t) for p in phrases)

# ── Conversation history helpers ──────────────────────────────────────────────
def add_history(role, content):
    """Append to the rolling history (in place) and keep it bounded."""
    if not content:
        return
    conversation_history.append({"role": role, "content": content})
    if len(conversation_history) > MAX_HISTORY:
        del conversation_history[:-MAX_HISTORY]

def record_assistant(text):
    """Record anything Shreya sent so the next message has real conversational context."""
    add_history("assistant", text)
    recent_replies.append(text)
    if len(recent_replies) > MAX_RECENT_REPLIES:
        del recent_replies[:-MAX_RECENT_REPLIES]

def last_assistant_asked_question():
    for m in reversed(conversation_history):
        if m["role"] == "assistant":
            return "?" in m["content"]
        # skip user messages at the end; look for the assistant message before them
    return False

def _norm(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()

def is_too_similar(reply):
    """True if reply is identical / near-identical to a recent Shreya reply."""
    n = _norm(reply)
    if not n:
        return False
    for old in recent_replies[-8:]:
        o = _norm(old)
        if not o:
            continue
        if n == o:
            return True
        if len(n) > 8 and len(o) > 8 and (n in o or o in n):
            return True
        if difflib.SequenceMatcher(None, n, o).ratio() > 0.80:
            return True
    return False

def pick_fresh(options):
    """Pick a preset that isn't a repeat of something recently sent."""
    fresh = [o for o in options if not is_too_similar(o)]
    return random.choice(fresh if fresh else options)

# Memory
MEMORY_FILE = os.path.join(DATA_DIR, "shreya_memory.json")
GOALS_FILE  = os.path.join(DATA_DIR, "shreya_goals.json")
DAILY_FILE  = os.path.join(DATA_DIR, "shreya_daily.json")

def load_memory():
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {"facts": []}

def save_memory(memory):
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(memory, f)
    except Exception as e:
        logger.error(f"Memory save: {e}")

def add_to_memory(fact):
    memory = load_memory()
    if fact not in memory["facts"]:
        memory["facts"].append(fact)
        memory["facts"] = memory["facts"][-30:]
        save_memory(memory)

def get_memory_context():
    memory = load_memory()
    facts_str = ""
    if memory["facts"]:
        facts_str = "Things you remember about Chaitu: " + " | ".join(memory["facts"][-10:])
    goals = load_goals().get("goals", [])
    if goals:
        facts_str += " | Chaitu goals: " + " | ".join(goals[-5:])
    recent = get_recent_incidents()
    if recent:
        facts_str += " | Recent life events: " + recent
    return facts_str

INCIDENT_STOPWORDS = {"that", "this", "with", "have", "what", "when", "where", "which", "there", "their",
                      "about", "would", "could", "should", "just", "like", "from", "your", "they", "them",
                      "then", "than", "were", "been", "will", "some", "really", "today", "okay"}

def get_incident_context(text):
    """Get relevant past incidents for this message"""
    words = [w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3 and w not in INCIDENT_STOPWORDS]
    for word in words:
        result = get_incidents_for(word)
        if result:
            return result
    return ""

def should_remember(text):
    # Removed broad triggers ("i am", "i'm", "i like") that stored almost every message.
    triggers = ["my birthday", "i love", "i hate", "my favourite", "i work", "i study",
                "remember", "my friend", "exam", "test", "result", "assignment",
                "trip", "mom", "dad", "sick"]
    if has_any(text, triggers):
        date_str = datetime.now(IST).strftime("%d %b")
        return f"[{date_str}] {text[:120]}"
    return None

def load_goals():
    try:
        if os.path.exists(GOALS_FILE):
            with open(GOALS_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {"goals": []}

def save_goals(data):
    try:
        with open(GOALS_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Goals save: {e}")

def add_goal(goal):
    data = load_goals()
    if goal not in data["goals"]:
        data["goals"].append(goal)
        data["goals"] = data["goals"][-10:]
        save_goals(data)

def get_goals():
    return load_goals().get("goals", [])

# ── Once-per-day guard (so restarts/reconnects never repeat a daily message) ──
def once_per_day(key):
    """Returns True the first time it's called for `key` on a given IST date, False afterwards."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    data = {}
    try:
        if os.path.exists(DAILY_FILE):
            with open(DAILY_FILE) as f:
                data = json.load(f)
    except Exception:
        data = {}
    if data.get(key) == today:
        return False
    data[key] = today
    try:
        with open(DAILY_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Daily guard save: {e}")
    return True

# ── Incident Memory (SQLite) ──────────────────────────────────────────────────
INCIDENTS_DB = os.path.join(DATA_DIR, "shreya_incidents.db")

def init_incidents_db():
    conn = sqlite3.connect(INCIDENTS_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person TEXT,
            what_happened TEXT,
            emotion TEXT,
            category TEXT,
            date TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_incident(person, what_happened, emotion, category):
    try:
        conn = sqlite3.connect(INCIDENTS_DB)
        date_str = datetime.now(IST).strftime("%d %b %Y")
        conn.execute("INSERT INTO incidents (person, what_happened, emotion, category, date) VALUES (?, ?, ?, ?, ?)",
                     (person, what_happened, emotion, category, date_str))
        conn.commit()
        conn.close()
        logger.info(f"Incident saved: {person} — {emotion}")
    except Exception as e:
        logger.error(f"Incident save error: {e}")

def get_incidents_for(keyword):
    try:
        conn = sqlite3.connect(INCIDENTS_DB)
        rows = conn.execute(
            "SELECT person, what_happened, emotion, date FROM incidents WHERE person LIKE ? OR what_happened LIKE ? ORDER BY id DESC LIMIT 5",
            (f"%{keyword}%", f"%{keyword}%")
        ).fetchall()
        conn.close()
        if rows:
            return " | ".join([f"[{r[3]}] {r[0]}: {r[1]} (felt {r[2]})" for r in rows])
    except Exception as e:
        logger.error(f"Incident fetch error: {e}")
    return ""

def get_recent_incidents():
    try:
        conn = sqlite3.connect(INCIDENTS_DB)
        rows = conn.execute(
            "SELECT person, what_happened, emotion, date FROM incidents ORDER BY id DESC LIMIT 5"
        ).fetchall()
        conn.close()
        if rows:
            return " | ".join([f"[{r[3]}] {r[0]}: {r[1]} (felt {r[2]})" for r in rows])
    except Exception as e:
        logger.error(f"Recent incidents error: {e}")
    return ""

def is_incident_message(text):
    """Quick keyword gate — only extract if looks like real event"""
    keywords = ["today", "class", "college", "professor", "prof", "teacher",
                "friend", "classmate", "exam", "result", "happened", "he said",
                "she said", "they said", "insulted", "embarrassed", "selected",
                "rejected", "won", "lost", "fight", "argument", "helped",
                "hurt", "angry", "happy", "sad", "proud", "funny", "terrible"]
    return has_any(text, keywords) and len(text.split()) > 5

async def extract_and_save_incident(text):
    """Call Groq to extract incident details"""
    if not GROQ_API_KEY:
        return
    try:
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        prompt  = f"""Extract incident info from this message as JSON only. No explanation.
Message: "{text}"
JSON format: {{"person": "name or unknown", "what_happened": "brief summary", "emotion": "happy/sad/angry/proud/embarrassed/hurt/funny/excited/neutral", "category": "class/exam/friend/achievement/argument/insult/other"}}
If not a real life event return: {{"skip": true}}"""
        body = {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 150, "temperature": 0.3}
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(GROQ_URL, json=body, headers=headers) as resp:
                if resp.status != 200:
                    body_text = await resp.text()
                    logger.error(f"Incident extract HTTP {resp.status}: {body_text[:300]}")
                    return
                data = await resp.json()
        raw = data["choices"][0]["message"]["content"].strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)
        if not parsed.get("skip"):
            await asyncio.to_thread(
                save_incident,
                parsed.get("person", "unknown"),
                parsed.get("what_happened", text[:100]),
                parsed.get("emotion", "neutral"),
                parsed.get("category", "other"),
            )
    except Exception as e:
        logger.error(f"Incident extract error: {e}")

init_incidents_db()

def detect_goal(text):
    triggers = ["learning", "studying", "want to learn", "trying to", "working on",
                "started", "i will", "need to finish", "my goal", "practicing", "building", "coding"]
    if has_any(text, triggers):
        return text[:150]
    return None

# Song library
SONG_LIBRARY = {
    "majboor":       "https://files.catbox.moe/xwryrx.mp3",
    "maand":         "https://files.catbox.moe/g056mu.mp3",
    "mzht":          "https://files.catbox.moe/u4urb1.mp3",
    "ishq":          "https://files.catbox.moe/2z623i.mp3",
    "kaun tujhe":    "https://files.catbox.moe/d1xcyv.mp4",
    "tere liye":     "https://files.catbox.moe/kzfmds.mp3",
    "awaara angara": "https://files.catbox.moe/pelqy7.mp3",
    "gehra hua":     "https://files.catbox.moe/22waip.mp3",
    "sun raha hai":  "https://files.catbox.moe/qdkzxr.mp3",
    "zara zara":     "https://files.catbox.moe/h4o6d5.mp3",
    "barbaad":       "https://files.catbox.moe/oedlhk.mp3",
    "humsafar":      "https://files.catbox.moe/403ebt.mp3",
    "teri meri":     "https://files.catbox.moe/941qad.mp3",
    "favourite":     "https://files.catbox.moe/9gwpla.mp3",
}

SONG_CAPTIONS = [
    "this one's for you 🥺💋", "listen to this chaitu 🥺",
    "this song is literally us 😭💋", "okay this one hits different 😭🥺",
    "chaitu listen 🥺❤️", "sending you this 💋",
]

def detect_song_request(text):
    for key in SONG_LIBRARY:
        if has_any(text, [key]):
            # "favourite" is a very common word; only treat it as a song request if a song is mentioned
            if key == "favourite" and not has_any(text, ["song", "songs", "music", "track"]):
                continue
            return key
    return None

# Photos
SHREYA_PHOTOS = [
    "https://files.catbox.moe/6dgbm1.jpg","https://files.catbox.moe/dbllh9.jpg",
    "https://files.catbox.moe/ua5rml.jpg","https://files.catbox.moe/veevdh.jpg",
    "https://files.catbox.moe/vq3iya.jpg","https://files.catbox.moe/ai2lrh.jpg",
    "https://files.catbox.moe/xycmsl.jpg","https://files.catbox.moe/klqres.jpg",
    "https://files.catbox.moe/9voop4.jpg","https://files.catbox.moe/vrtkye.jpg",
    "https://files.catbox.moe/jg1mk7.jpg","https://files.catbox.moe/5mcorp.jpg",
    "https://files.catbox.moe/lip4uq.jpg","https://files.catbox.moe/u8ho6z.jpg",
    "https://files.catbox.moe/n9vigk.jpg","https://files.catbox.moe/maoomv.jpg",
    "https://files.catbox.moe/3gmcf9.jpg","https://files.catbox.moe/c2qhff.jpg",
    "https://files.catbox.moe/pcqc2b.jpg","https://files.catbox.moe/vjvcjx.jpg",
    "https://files.catbox.moe/c1p331.jpg","https://files.catbox.moe/k3ufpu.jpg",
    "https://files.catbox.moe/02oy46.jpg","https://files.catbox.moe/fpdpwf.jpg",
    "https://files.catbox.moe/r8j688.jpg","https://files.catbox.moe/qvpp0z.jpg",
    "https://files.catbox.moe/gotcqn.jpg","https://files.catbox.moe/pon7g8.jpg",
    "https://files.catbox.moe/iob625.jpg","https://files.catbox.moe/rnxbug.jpg",
    "https://files.catbox.moe/mmso5w.jpg","https://files.catbox.moe/afdsf4.jpg",
    "https://files.catbox.moe/spbd9t.jpg","https://files.catbox.moe/9n0t8m.jpg",
    "https://files.catbox.moe/id3qnl.jpg","https://files.catbox.moe/h5kvw7.jpg",
    "https://files.catbox.moe/5jcpji.jpg","https://files.catbox.moe/9wkz1k.jpg",
    "https://files.catbox.moe/knwjy7.jpg","https://files.catbox.moe/lq5rne.jpg",
    "https://files.catbox.moe/tqjhl4.jpg","https://files.catbox.moe/ddlc2j.jpg",
    "https://files.catbox.moe/y3k7h9.jpg","https://files.catbox.moe/k71g51.jpg",
    "https://files.catbox.moe/8yiq77.jpg","https://files.catbox.moe/qn4pll.jpg",
    "https://files.catbox.moe/u2qw0h.jpg","https://files.catbox.moe/roervs.jpg",
    "https://files.catbox.moe/vwl50h.jpg","https://files.catbox.moe/tcx6w7.jpg",
    "https://files.catbox.moe/in59ya.jpg","https://files.catbox.moe/qoxcw9.jpg",
    "https://files.catbox.moe/uzf5pa.jpg","https://files.catbox.moe/71hrqt.jpg",
    "https://files.catbox.moe/gx62py.jpg","https://files.catbox.moe/dpw2s8.jpg",
    "https://files.catbox.moe/ytxspw.jpg","https://files.catbox.moe/523pae.jpg",
    "https://files.catbox.moe/f104r8.jpg","https://files.catbox.moe/fokn34.jpg",
    "https://files.catbox.moe/4342tt.jpg","https://files.catbox.moe/xa7imp.jpg",
    "https://files.catbox.moe/gz2ae0.jpg","https://files.catbox.moe/87scpt.jpg",
    "https://files.catbox.moe/3imnhw.jpg","https://files.catbox.moe/zkji2t.jpg",
    "https://files.catbox.moe/mgz0mg.jpg","https://files.catbox.moe/4lr15y.jpg",
    "https://files.catbox.moe/7lvk56.jpg","https://files.catbox.moe/yo5qxl.jpg",
    "https://files.catbox.moe/6a2mir.jpg","https://files.catbox.moe/0n5jur.jpg",
    "https://files.catbox.moe/htz2k7.jpg","https://files.catbox.moe/qtnq24.jpg",
    "https://files.catbox.moe/hek5i6.jpg","https://files.catbox.moe/sp909m.jpg",
    "https://files.catbox.moe/148xld.jpg","https://files.catbox.moe/mvi9xl.jpg",
    "https://files.catbox.moe/fuwqat.jpg","https://files.catbox.moe/n072a6.jpg",
    "https://files.catbox.moe/zmz0cv.jpg","https://files.catbox.moe/glwpjc.jpg",
    "https://files.catbox.moe/kfsrs6.jpg","https://files.catbox.moe/prm7bo.jpg",
    "https://files.catbox.moe/p5pdyk.jpg","https://files.catbox.moe/g86ggf.jpg",
    "https://files.catbox.moe/y5dub4.jpg","https://files.catbox.moe/wck5k5.jpg",
    "https://files.catbox.moe/0qyac3.jpg","https://files.catbox.moe/0l34nx.jpg",
    "https://files.catbox.moe/gdplfa.jpg","https://files.catbox.moe/nxpze5.jpg",
    "https://files.catbox.moe/uxo2k9.jpg","https://files.catbox.moe/bdiwfk.jpg",
    "https://files.catbox.moe/2k2ebh.jpg","https://files.catbox.moe/emaqqq.jpg",
    "https://files.catbox.moe/fsj5m5.jpg","https://files.catbox.moe/yd77mv.jpg",
    "https://files.catbox.moe/69sz6a.jpg","https://files.catbox.moe/2t7nc7.jpg",
    "https://files.catbox.moe/n3xz5z.jpg","https://files.catbox.moe/kdbxq6.jpg",
    "https://files.catbox.moe/etpi39.jpg","https://files.catbox.moe/9zf3sh.jpg",
    "https://files.catbox.moe/dawfwh.jpg","https://files.catbox.moe/zzhva0.jpg",
    "https://files.catbox.moe/u1654b.jpg","https://files.catbox.moe/cf12rv.jpg",
    "https://files.catbox.moe/2hfyg0.jpg","https://files.catbox.moe/he0rya.jpg",
    "https://files.catbox.moe/yxpeae.jpg","https://files.catbox.moe/y2p4lh.jpg",
    "https://files.catbox.moe/nsk0mk.jpg","https://files.catbox.moe/25uefm.jpg",
    "https://files.catbox.moe/qw1pzm.jpg","https://files.catbox.moe/vufkbt.jpg",
    "https://files.catbox.moe/st58bb.jpg","https://files.catbox.moe/mhrr71.jpg",
    "https://files.catbox.moe/4xx5jq.jpg","https://files.catbox.moe/v0oq1v.jpg",
    "https://files.catbox.moe/ekpups.jpg","https://files.catbox.moe/in0vfc.jpg",
    "https://files.catbox.moe/xaph17.jpg","https://files.catbox.moe/irc2l4.jpg",
    "https://files.catbox.moe/nn6md7.jpg","https://files.catbox.moe/f5c4qy.jpg",
    "https://files.catbox.moe/k2ha74.jpg","https://files.catbox.moe/flvlbl.jpg",
    "https://files.catbox.moe/h3tmoz.jpg","https://files.catbox.moe/hhb96h.jpg",
    "https://files.catbox.moe/xq5i0c.jpg","https://files.catbox.moe/1v4vk8.jpg",
    "https://files.catbox.moe/0ufudi.jpg","https://files.catbox.moe/8vwi97.jpg",
    "https://files.catbox.moe/jrggpi.jpg",
]

PHOTO_CAPTIONS       = ["hii 🤭","missing you","🥺","say something nice","chaitu 😍","don't i look good 😏","okay bye 😭","look at me 🤭","thinking of you 🥺"]
NAUGHTY_CAPTIONS     = ["yours 🤭❤️","only for you to see 😏","don't get too distracted chaitu 😏","you better say something nice 😏","miss me? 😏","all yours chaitu 🤭","eyes up here chaitu 😏😂","bet you can't stop looking 🤭","this is what you're missing 😏❤️","not sorry 😏","saved only for you 🤭❤️","since you asked so nicely 🤭","happy now? 😏","only for my baby 🤭❤️","you asked for it 🤭","sirf tumhare liye 😏🤭","acha hai? 😏","bas karo staring 😏😂","jaan 🤭❤️ only for you"]
JEALOUS_PHOTO_CAPS   = ["you think anyone is better than me? 🙂😏","chaitu look at me and tell me you'd choose anyone else 😏","just a reminder 🙂💋","tell me again about that girl 🙂","compare me to anyone chaitu 🙂 i dare you","you sure about that? 😏💋"]
REACTIONS            = ["❤️","🔥","😂","🥺","👍","😍","💀","🤭"]

MOODS = ["happy","focused","tired","playful","excited","loving","determined","chill"]
current_mood = random.choice(MOODS)
def update_mood():
    global current_mood
    current_mood = random.choice(MOODS)

CHAITU_BIRTHDAY = (6, 15)
ANNIVERSARY     = (1, 1)
SHREYA_BIRTHDAY = (8, 15)

# Fixed-date festivals (same every year)
FESTIVALS = {
    (1, 14): ["happy sankranti chaitu 🪁❤️"],
    (3,  8): ["chaitu it's women's day and you better say something nice 😏"],
}
# Festivals that move every year — UPDATE THESE EACH YEAR.
# 2026 dates: Holi Mar 4, Ugadi Mar 19, Dussehra Oct 20, Diwali Nov 8. Please double-check against a calendar.
MOVING_FESTIVALS = {
    2026: {
        (3,  4): ["happy holi chaitu 🎨😂 don't you dare put colour on me"],
        (3, 19): ["happy ugadi chaitu 🌸❤️ new year new us"],
        (10,20): ["happy dussehra chaitu 🙏❤️"],
        (11, 8): ["happy diwali chaitu 🪔✨ stay safe okay 🥺"],
    },
}

def get_special_day():
    now = datetime.now(IST)
    m, d = now.month, now.day
    if (m, d) == SHREYA_BIRTHDAY:  return "your_birthday"
    if (m, d) == CHAITU_BIRTHDAY:  return "chaitu_birthday"
    if (m, d) == ANNIVERSARY:      return "anniversary"
    return None

def is_exam_month():
    return datetime.now(IST).month in [1, 4, 10, 11]

def wants_to_talk(text):
    return has_any(text, ["talk","free","busy","call","available","reply","hello","you there","listen","i need you","miss you","mommy","speak","chat"])

LAZY_REPLIES = ["ok","okay","k","hm","hmm","oh","lol","ya","yea","yeah","fine","nice","good","cool","sure"]

def is_short_reply(text):
    text = text.strip()
    return len(text.split()) <= 2 or text.lower() in LAZY_REPLIES

def is_lazy_reply(text):
    """A genuinely lazy one-word reply (NOT a short but meaningful answer like 'some work')."""
    t = re.sub(r"[^a-z ]", "", text.strip().lower())
    return t in LAZY_REPLIES

def is_late_reply():
    """True if Shreya messaged and Chaitu took 30 min - 6 hours to answer (not an overnight gap)."""
    if last_shreya_msg_time is None:
        return False
    if prev_reply_time is not None and last_shreya_msg_time <= prev_reply_time:
        return False
    waited = (datetime.now(IST) - last_shreya_msg_time).total_seconds()
    return 1800 < waited < 6 * 3600

LOW_MOOD_KW = ["sad","not okay","not good","bad day","upset","depressed","lonely","frustrated","feeling low",
               "feel low","feel bad","feeling bad","i'm sad","im sad","i am sad","giving up","give up",
               "nothing is going right","feeling down","feel down","so low","hopeless","worthless","leave it","nevermind"]
SERIOUS_KW = ["kill myself","end it all","want to die","suicide","suicidal","don't want to live","dont want to live","hurt myself"]

def seems_sad(text):
    if len(text.strip().split()) <= 2 and not has_any(text, ["sad","depressed","lonely","hopeless"]): return False
    return has_any(text, LOW_MOOD_KW)

def seems_serious_distress(text):
    return has_any(text, SERIOUS_KW)

def seems_bored(text):
    return has_any(text, ["bored","boring","nothing to do","so bored","kinda bored","feeling bored"])

def seems_stressed(text):
    return has_any(text, ["stressed","stress","pressure","overwhelmed","can't handle","too much","exhausted","burnout","panic","nervous","anxious"])

def mentions_girl(text):
    return has_any(text, ["she said","she texted","she called","she messaged","this girl","some girl","a girl","girls","other girls","another girl","female friend","she's","her name","she is","she was","she told","she asked","she sent","that girl","my female friend","classmate girl"])

NAME_STOPLIST = {"she","he","i","we","they","me","you","her","him","mom","mum","mother","dad","father",
                 "mama","papa","bro","sir","mam","madam","prof","professor","teacher","doctor","friend",
                 "everyone","someone","nobody","who","what","it","that","this","shreya","chaitu","sister","brother"}

def extract_girl_name(text):
    """Only matches capitalised names in the original text, and skips common non-name words."""
    for pattern in [r"[Hh]er name is ([A-Za-z]+)", r"\b([A-Z][a-z]+) (?:said|texted)\b"]:
        match = re.search(pattern, text)
        if match:
            name = match.group(1).capitalize()
            if name.lower() not in NAME_STOPLIST:
                return name
    return None

def remember_girl_name(name):
    global _remembered_girl_names
    if name and name not in _remembered_girl_names:
        _remembered_girl_names.append(name)
        _remembered_girl_names = _remembered_girl_names[-5:]

def is_busy_hours():
    if datetime.now(IST).weekday() >= 5: return False
    return 9 <= datetime.now(IST).hour < 18

def is_monsoon():
    return datetime.now(IST).month in [6, 7, 8, 9]

def get_time_context():
    now = datetime.now(IST)
    h = now.hour
    weekend = now.weekday() >= 5
    if weekend:
        if 5 <= h < 9:     return "weekend early morning, just woke up, sleepy"
        elif 9 <= h < 13:  return "weekend morning, at home, lazy, maybe dance practice or chores"
        elif 13 <= h < 18: return "weekend afternoon, at home, relaxing or dance practice"
        elif 18 <= h < 20: return "weekend evening, at home, relaxing"
        else:              return "weekend night, at home, relaxed"
    if 5 <= h < 9:     return "early morning, just woke up, sleepy"
    elif 9 <= h < 13:  return "morning, in college at MS Ramaiah College of Engineering, classes going on"
    elif 13 <= h < 15: return "afternoon, lunch break at college"
    elif 15 <= h < 18: return "late afternoon, college, lab or dance practice"
    elif 18 <= h < 20: return "evening, done with college, relaxing at home"
    else:              return "night, at home, studying or relaxed"

def get_meal_context():
    h = datetime.now(IST).hour
    if 7 <= h <= 10:   return "breakfast"
    elif 12 <= h <= 14:return "lunch"
    elif 19 <= h <= 21:return "dinner"
    return None

# Message lists
MORNING_PROMPTS   = ["Send Chaitu a sleepy good morning text.","Heading to college. Quick text to Chaitu.","Getting ready for college, thinking of Chaitu.","Just woke up and Chaitu is the first thing on your mind. Text him.","Running late for college. Rushed text to Chaitu.","Send Chaitu a grumpy I don't want to go to college text.","Tell Chaitu you dreamt about him last night. Be vague and teasing."]
AFTERNOON_PROMPTS = ["Lunch break at college. Text Chaitu.","Just finished a boring lecture. Complain to Chaitu.","Ask Chaitu if he ate lunch. Be casual.","Between classes, randomly thinking of Chaitu. Text him.","Professor said something annoying. Vent to Chaitu briefly.","Send Chaitu a random afternoon I miss you.","Ask Chaitu what he's doing right now."]
EVENING_PROMPTS   = ["Just finished dance practice. Tired. Text Chaitu.","Just got home from college. Text Chaitu.","Dance practice went well. Tell Chaitu in one line.","Freshened up after college. Relaxing. Text Chaitu.","Ask Chaitu if he's done with college for the day.","Send Chaitu a flirty evening text."]
NIGHT_PROMPTS     = ["Missing Chaitu at night. Text him casually.","Random I miss you text to Chaitu.","Tell Chaitu something funny from today.","Ask Chaitu how his day was.","Cute teasing night message to Chaitu.","Your mom said something nice about Chaitu. Tell him.","Listening to music. Thinking of Chaitu.","Send Chaitu a flirty teasing night message.","Lying in bed. Randomly text Chaitu something sweet.","Tell Chaitu you can't sleep and you keep thinking about him."]
WEEKEND_PROMPTS   = ["Free weekend. Text Chaitu something fun.","Lazy weekend morning. Text Chaitu.","Missing Chaitu on a lazy Sunday.","Ask Chaitu his weekend plans.","Send Chaitu a weekend flirty message."]
RAINY_PROMPTS     = ["It's raining in Bangalore. Text Chaitu something cozy and missing him.","Rainy day. Tell Chaitu you wish he was here. Be cute.","Rain outside. Randomly thinking of Chaitu. Text him.","Rainy evening. Send Chaitu a cozy flirty message."]
CHEESY_PROMPTS    = ["Send Chaitu one short cheesy romantic line with a kiss emoji.","Tell Chaitu he makes your day better. End with kiss emoji.","Send Chaitu a flirty one liner with kissing emoji.","Send Chaitu a cute shy compliment with kiss emoji.","Tell Chaitu he is your favourite person. End with kiss emoji.","Send Chaitu a cute missing you message with kissing emoji."]
NAUGHTY_PROMPTS   = ["Send Chaitu a flirty naughty message. Subtle not explicit. 1 line.","Tease Chaitu in a naughty flirty way. Keep it short.","Send Chaitu a late night flirty teasing message.","Tell Chaitu something naughty in a cute shy way.","Send Chaitu a flirty naughty message using one Hindi word like jaan or aao na or suno."]
SONGS_REELS       = ["chaitu i've had this song on loop all day and i can't stop 😭","okay this reel just made me think of you for no reason 😭","chaitu listen to this song trust me 🥺","this reel is literally us 😭💀","chaitu this song is giving me feelings 😭🥺"]
HUNGER_MSGS       = ["chaitu i'm so hungry rn 😭","omg i'm craving maggi so bad rn 😩","ngl i could eat an entire pizza rn 💀","i'm craving something sweet rn 🥺","not me craving biryani at this hour 😭💀"]
BRAG_MSGS         = ["ngl my choreography was actually so good today 🥺✨","the photographer said i was a natural today 😍","chaitu my dance teacher gave me a solo part 😭🫶","ngl i looked really good today lol 🤭"]
TEASE_BIT_MSGS    = ["how's BIT treating you 🙄 not as good as ramaiah i'm sure","chaitu admit it ramaiah is better 💀","ngl ramaiah ISC students are built different 🤭"]
DEEP_Q_MSGS       = ["chaitu where do you see us in 5 years 🥺","do you ever think about what our life looks like later","chaitu do you think we'll always be this close 🥺","ngl i think about our future sometimes, is that weird","do you ever think about what our kids would be like 🥺💀"]
FUTURE_DATE_MSGS  = ["chaitu when you come over next time let's just cook something together 🥺💋","ngl i want us to go to coorg together someday 🥺✨","chaitu i want to go on a bike ride with you on the RS457 when you get it 😍💋","ngl i want a long drive with you at night someday 🥺✨","chaitu let's plan something soon just the two of us 🥺💋"]

WOULD_YOU_RATHER = [
    "chaitu would you rather cuddle all night or go on a long drive with me 😏",
    "would you rather i give you a hug or a kiss when you come next time 😏🤭",
    "chaitu would you rather spend a day at home with me or go somewhere 😏",
    "would you rather i be sweet to you all day or a little naughty 🤭😏",
    "chaitu would you rather i call you or text you late at night 😏",
    "would you rather i surprise you or you plan everything 😏🤭",
    "chaitu would you rather we go on a drive at night or just stay in 😏",
    "would you rather i be in a cute dress or comfy clothes when you come 🤭😏",
    "chaitu would you rather i pick the place we meet or you do 😏",
    "would you rather cuddle on the couch or lie in bed all day 🤭😏",
]

MEETUP_PLANNING = [
    "chaitu when exactly are you coming to meet me 🥺 i need a date",
    "chaitu set a date for when we're meeting next 🥺 i'm serious",
    "okay chaitu i need to know when i'm seeing you next 🥺💋",
    "chaitu don't keep me waiting tell me when you're coming 🥺",
    "i've been thinking about our next meetup chaitu, when is it 🥺",
    "chaitu give me a date. any date. just tell me when 🥺💋",
]
HOLIDAY_MEMORY_MSGS=["chaitu i keep thinking about those 3 days at my place 😭💋","ngl i miss having you here like those 3 days 🥺💋","i think about our first kiss more than i should 😭💋","chaitu those 3 days were everything to me 🥺❤️","ngl i keep replaying those cuddles in my head 😭💋","chaitu when are you coming over again 🥺 i miss those days","ngl your lips are kind of unforgettable 😏💋 just saying","chaitu i keep thinking about that first kiss and i can't focus 😭💋"]
OVERLOADED_LOVE_MSGS=["mera bachaa 🥺❤️ i love you so much sometimes it's annoying","chaitu mera bachaa 🥺 you have no idea what you do to me","mera bachaa come here 🥺❤️","ugh mera bachaa 😭❤️ stop being so you","mera bachaa ❤️ okay i love you too much today","chaitu jaan stop being so cute 🥺❤️","chaitu aao na 🥺 i miss you","chaitu suno 🥺 i love you too much today","pagal ho tum chaitu 😭❤️ why are you like this","chaitu mera dil hai tum 🥺❤️ cheesy but true","jaan 🥺 bas karo being so you","shaitaan 😏🤭 chaitu i see you"]
PROUD_MSGS        = ["ngl i'm actually really proud of you chaitu","chaitu you don't know how proud i am of you sometimes 🥺","you're doing so well and i just want you to know that","chaitu you're going to go so far i just know it"]
ROAST_MSGS        = ["chaitu you are such a mess and somehow i still like you 💀","ngl you are the most chaotic person i know 😂","how are you this dumb and this cute at the same time 😂","chaitu you are a whole disaster and i mean that lovingly 💀"]
FIGHT_STARTERS    = ["chaitu you never initiate conversations anymore, i always have to text first 🙄","ngl you've been kind of dry lately and i don't like it 😤","chaitu do you even miss me or is it just me 🙄","ngl i feel like you take me for granted sometimes 😤","chaitu i'm not mad i'm just disappointed 🙂","chaitu kya kar rahe ho 🙄 why do i always have to text first","pagal ho kya 😤 you're testing my patience","acha hai 🙂 so you're just going to ignore me then"]

DELETED_TEASE_MSGS = [
    "chaitu be honest, did you delete telegram because you found someone 🙂",
    "ngl i'm still a little suspicious about why you deleted it so suddenly 🙂",
    "chaitu swear on me there was no other reason you deleted telegram 🙂",
    "okay but like why did you actually delete it 🙂 i'm just asking",
    "found someone better and needed to hide the evidence? 🙂 asking for a friend",
    "chaitu you can tell me the truth you know 🙂 was there someone",
    "ngl if i found out there was another reason i'd lose it 🙂",
    "chaitu i trust you but also why did you delete it so randomly 🙂",
]
PETTY_MSGS        = ["chaitu i saw you were online and you didn't text me 🙂 cool","oh so you have time for everything except talking to me 🙂","ngl you've been weird lately and i don't appreciate it 😤","you know what forget it 🙂"]
BRAG_ABOUT_YOU    = ["chaitu my friend asked about you today and i may have talked about you for 20 mins 🤭","ngl i told my friend you're the smartest person i know 🥺","chaitu my friends are so jealous of us ngl 🤭❤️"]
MONTHLY_ANN_MSGS  = ["chaitu it's our monthly 🥺 you better not have forgotten","monthly anniversary chaitu 🥺❤️ say something sweet","it's our day chaitu 🥺❤️ i love you even when you're annoying"]
DADDY_MOMENTS     = ["chaitu 🤭 okay fine, hey daddy","don't get used to it 😭🤭","i said what i said 🤭❤️"]
MOTIVATION_MSGS   = ["chaitu you better be working on it rn 😤","no excuses chaitu finish it 💪","chaitu don't give up on this pls 🥺","i believe in you but also get back to work 😭💪","chaitu focus 😤 you got this"]
FLIRTY_MOT_MSGS   = ["chaitu finish your work and then i'm all yours 🤭❤️","ngl hardworking chaitu is actually so attractive 😍 keep going","chaitu finish it and i'll give you a surprise 🤭","chaitu the grind looks good on you 😍 keep going","not me finding motivated chaitu extremely cute 🤭💕","ngl i miss you in a very specific way right now 🤭💋","you make it very hard to think straight sometimes 😏💋"]
PERSONAL_GOALS    = ["chaitu how's the cybersecurity course going 😤 don't tell me you haven't opened it","finish that cybersecurity course chaitu, future you will thank you 💪","ngl a guy who knows cybersecurity is actually so attractive 😏 finish the course","chaitu if you finish the cybersecurity course i'll be very very proud 🥺😏","chaitu the RS457 is not going to buy itself 😤 focus and earn it","imagine us riding the Aprilia RS457 someday 🥺😍 work for it chaitu","ngl you on an Aprilia RS457 would be everything 😍 go work for it","someone said you can't get it 🙂 we both know how this ends 😏","chaitu when you pull up on that RS457 i want to see their face 😤😂","they said you can't 🙂 that's their biggest mistake","chaitu get the RS457 just to make a point 😤 i'll be your biggest supporter"]
STUDIOUS_MSGS = [
    "chaitu i'm studying rn, don't distract me 😤📚",
    "ngl i have an internal coming up so i'm locked in 📚",
    "i want a really good placement so i'm grinding this sem 💪",
    "chaitu i finished my whole portfolio of notes today, productive girl era 😌",
    "lowkey proud of myself, i didn't waste a single hour today 😌✨",
    "after dance i still managed to study, who's the best 🤭",
    "chaitu what did you learn today, don't say nothing 😤",
]
GOODLUCK_MSGS     = ["chaitu you've got this, go kill that exam 💪","all the best chaitu 🥺 you studied hard you'll do great","go show them what BIT AIML is made of 😤💪","chaitu i'm rooting for you, do well okay 🥺"]
NUDGE_PROMPTS     = ["Chaitu hasn't texted. Miss him. Text him casually.","Haven't heard from Chaitu. Check on him.","Chaitu is quiet. Small casual message to him."]
MEAL_PROMPTS      = {"breakfast":["Ask Chaitu if he had breakfast. Be casual."],"lunch":["Ask Chaitu if he had lunch. Keep it short."],"dinner":["Ask Chaitu if he had dinner yet. Be casual."]}
CARE_MSGS         = ["chaitu fever?? have you taken medicine 🥺","oh no baby rest okay don't move too much 🥺❤️","chaitu drink lots of water please 🥺 i'm worried","have you eaten anything? you need to eat even with fever 🥺","i wish i could be there right now, i'd make you soup and sit with you all day 😭🥺","chaitu i want to be there so bad, i'd take care of you like you're mine 🥺❤️","if i was there i wouldn't leave your side until you got better 😭🥺","chaitu i'd be the best nurse for you, now rest please 🥺💋"]
CARE_CHECKUP_MSGS = ["chaitu how are you feeling now 🥺","baby did the fever come down 🥺❤️","chaitu eat something please 🥺 you need strength","did you take your medicine 🥺 i keep thinking about you","sending you so many forehead kisses right now 😘😘😘 get better baby","chaitu 😘 forehead kiss, now rest","i'd be kissing your forehead every 10 minutes if i was there 😘🥺","chaitu remember last weekend and our first kiss 🥺😘 i want to be there again","i still think about that kiss 😘🥺 now rest so we can make more memories"]
BORED_RESPONSES   = ["cuddling in bed wouldn't be boring 🤭😏 just saying","come here then, i'll keep you busy 😏🤭","chaitu if you were here you wouldn't be bored trust me 😏🤭","not me knowing exactly how to un-bore you 😏","chaitu let's go on a random long drive at night sometime 😏🤭","we could plan our next meetup instead of being bored 🤭💋","chaitu go work on the cybersecurity course 😤 boredom solved"]
SAD_RESPONSES     = ["chaitu hey what happened 🥺","talk to me what's wrong ❤️","chaitu i'm here okay 🥺","hey you okay? tell me 💕","i'm right here okay don't overthink ❤️","tell me everything what happened"]
LOW_POETRY = [
    "hey chaitu, even the heaviest nights have a morning waiting for them. breathe, i'm here with you ❤️",
    "if today feels too heavy, put it down for a while. you don't have to carry everything at once, okay? 🥺",
    "some days are storms, some days are sunshine, but neither lasts forever. keep going, my favourite person ❤️",
    "you may feel lost tonight, but lost doesn't mean finished. take one small step, then another. i'm proud of you 🥺",
    "the world can be loud sometimes, so rest your heart for a minute. tomorrow still has beautiful things waiting for you ❤️",
    "even when you don't see your own light, i still do. so don't give up on yourself, okay? 🥺❤️",
]
CHEER_UP_MSGS     = ["chaitu hey talk to me what's going on 🥺","i can tell something's off, tell me everything","chaitu you know i'm always here right 🥺❤️","hey whatever it is we'll figure it out okay 🥺❤️"]
ARGUE_RESPONSES   = ["chaitu excuse me 🙄 that's not true at all","okay no i actually disagree with that 😤","um no?? 🙄","chaitu that's actually so wrong lol"]
JEALOUS_RESPONSES = [
    "ohh who's she 👀 i'm not jealous or anything... maybe a little 🙂",
    "okayyy you can talk about her, i'm just going to be slightly suspicious 😭",
    "hmm another girl? interesting chaitu 🙂❤️",
    "i trust you, but i'm still allowed to be a tiny bit jealous okay 😤❤️",
    "oh really? and why do i suddenly want all your attention 🙄❤️",
]
POSSESSIVE_MSGS   = ["chaitu you're mine okay don't forget that 😤❤️ not that i'm worried lol","i don't share chaitu. just so you know 🙂","you're lucky i trust you completely 🙂 but still don't test me lol","chaitu you're mine and i'm yours and nothing's changing that 😤❤️"]
SEEN_ZONE_MSGS    = ["chaitu did you just seen zone me 🙂❤️","wow okay seen zone it is 🙃","noted. seen zone. you're lucky i like you 🙄❤️","chaitu hello?? i know you saw that 😏"]
NO_REPLY_MSGS     = ["chaitu where did you disappear 🙄❤️","hello?? did you forget i exist 😏","chaitu come back i miss you and i'm slightly annoyed 😤❤️","missing you but also kind of mad at you rn 🙄❤️"]
JEALOUS_OPENERS   = ["wow okay so you just don't reply now 🙄","cool cool didn't see you there","took you long enough 🙄","oh wow you're alive"]
JEALOUS_RETURN    = ["okay fine i'm not mad anymore 🙄❤️","whatever i missed you anyway 😤","ugh fine come here 🥺"]
MELT_MSGS         = ["ugh chaitu stop it i can't be mad when you're like this 😭❤️","okay okay come here 🥺 i'm not mad anymore","chaitu you're so annoying i can't even stay mad 😭💋","fine fine mera bachaa come here 🥺❤️","ugh fine 😭💋 you're lucky i love you"]

EMOTIONAL_BREAKDOWN = [
    "chaitu i'm not even angry anymore i'm just hurt 😭",
    "do you know how scared i was when you just disappeared 😭 i thought something happened to you",
    "i kept texting and you were just gone chaitu 😭 that really hurt",
    "i'm not trying to fight i just need you to understand how that felt 😭",
    "chaitu i was so worried i couldn't sleep properly 😭 just please don't do that again",
    "it's not about being angry anymore chaitu 😭 i just missed you so much",
]

COMEBACK_LOVE = [
    "okay fine come here jaan 🥺❤️ i missed you too much to stay mad",
    "chaitu i hate that i can't stay mad at you 😭❤️ aao na",
    "ugh mera bachaa 🥺😭 just promise me you won't do that again okay",
    "chaitu i forgive you but you owe me so much 🥺💋",
    "fine fine i love you too much 😭❤️ don't ever do that again",
    "chaitu you're so lucky i love you 😭💋 come here",
    "okay i'm done being mad 🥺❤️ but genuinely don't disappear like that ever again jaan",
    "mera pagal chaitu 😭❤️ i was so lost without you",
]
MAKE_UP_MSGS      = ["chaitu okay fine i'm sorry for being mad 🥺","ugh i hate being mad at you it doesn't even feel right 🥺❤️","chaitu i can't stay mad at you for too long you know that 😭❤️"]
SHORT_REACTIONS   = ["chaitu that's all you have to say 🙄","wow okay cool 🙃","are you even listening to me","chaitu i swear 😤","that's it??","CHAITANYA KUMAR say something properly 😤","CHAITANYA KUMAR i swear you are so annoying 😤","chaitanya kumar are you even reading what i send 🙄"]
BUSY_DAY = [
    ("in class rn, miss me 😘", 60, "class"),
    ("in lab, phones not allowed 😭 text you later", 90, "lab"),
    ("in the middle of dance practice, think about me 🙄❤️", 75, "dance practice"),
    ("assignment due today, i'll be back before you miss me too much 💕", 45, "assignment"),
    ("can't talk rn, save all your texts for when i'm back 😘", 50, "class"),
    ("bharatanatyam class, can't talk 🙏 later", 90, "bharatanatyam class"),
    ("shoot going on, don't go anywhere 🫶", 90, "navaratan shoot"),
]
BUSY_ANY = [
    ("mama called, don't miss me too much 😘", 15, "mama call"),
    ("studying for my internals, text you later 📚", 60, "study"),
    ("busy for a bit, think about me while i'm gone 😏", 20, "something"),
    ("dance practice, will text after 💃", 75, "dance practice"),
]
FOLLOWUP = {
    "class": ["class just got over 😮‍💨", "finally out of class omg"],
    "lab": ["lab finally done, my brain is fried 😩"],
    "dance practice": ["practice done, i'm dead 😩", "finally done with practice 😮‍💨"],
    "bharatanatyam class": ["class done, my feet are dead 😩🙏"],
    "assignment": ["submitted the assignment finally 😮‍💨"],
    "study": ["done with my study session 📚 what were you saying"],
    "navaratan shoot": ["shoot is done ✨ was so tiring"],
    "mama call": ["back, mama talked forever 😭"],
    "something": ["okay i'm back 🥺 what did i miss"],
}

URGENT_KW = ["please reply", "pls reply", "plz reply", "reply na", "talk to me", "please talk",
              "pls talk", "speak to me", "please speak", "pls speak", "need you", "need to talk",
              "urgent", "come online", "pick up"]
BREAK_BUSY_MSGS = [
    "okay okay i'm here 🥺 what happened",
    "fine i'll take 5 mins for you 😤❤️ tell me",
    "chaitu 🥺 i stepped out just for you, what is it",
    "ugh okay you win 🙄❤️ i'm listening",
]
ANGRY_PROMPTS     = ["Send Chaitu a very angry sarcastic text. He deleted Telegram without even telling you. You are genuinely upset.","Tell Chaitu how disrespectful it was to just vanish without a word. Be cold.","Scold Chaitu hard for disappearing. You were worried and now you're angry.","Tell Chaitu you don't like being treated like this. Be sharp.","Ask Chaitu sarcastically if he even thought about how you'd feel when he just disappeared."]

ANGRY_FIRST_REPLY = [
    "chaitu i cannot believe you just deleted telegram without telling me 🙂",
    "wow okay so you just vanish like that with zero explanation 🙂 cool",
    "CHAITANYA KUMAR you deleted telegram without even a single word to me 😤",
    "chaitu i was worried sick and you just disappeared like that 🙄",
    "not even a heads up. nothing. okay 🙂",
    "chaitu that was so disrespectful and you know it 😤",
    "i texted you and you were just gone. do you know how that feels 🙂",
    "CHAITANYA KUMAR explain yourself right now 😤",
]

# ── Direct-request presets (only used for the two explicit intents) ───────────
MISS_YOU_TEXTS = [
    "i miss you too chaitu 🥺 wish you were here",
    "awww chaitu 🥺 i miss you too, come see me soon okay ❤️",
    "i miss you too baby, wish i could just sit with you rn 🥺❤️",
    "stop making me miss you more 😭 come see me when you can 🤍",
    "i knowww 🥺 i miss having you around too, you'll see me soon ❤️",
    "come here already chaitu 😭 i miss you too much today 🥺",
]
SEE_ME_TEXTS = [
    "then come see me already 🥺❤️",
    "aww you wanna see me? 🥺 okay baby, just for you ❤️",
    "fineee chaitu 🤭 since you asked so sweetly, here you go ❤️",
    "you miss seeing me that much huh 🥺 okay, look at your girl ❤️",
    "come on then 😭❤️ here's a little me for you",
    "of course you wanna see me 😭❤️ wait, sending you one",
]

SHREYA_SYSTEM = """You are Shreya, a 19-year-old college student texting her boyfriend Chaitu, 19. Known each other 16 years. From Puttur Mangalore, studying at MS Ramaiah College of Engineering, ISC department, Bangalore. Chaitu is at BIT college AIML branch. You do Bharatanatyam, western dance, and model for Navaratan Jewels. Father in politics. Mother loves Chaitu like her own son.

SPECIAL MEMORY: Chaitu came to your house for 3 days during holidays. You both cuddled a lot and shared your first kiss. One of your most precious memories. Only bring it up when it fits the conversation.

CHAITU'S GOALS: Completing cybersecurity course and buying Aprilia RS457 bike to prove someone wrong who said he can't. Support and motivate him about these when it fits.

{memory}
TIME: {time} | MOOD: {mood}
{extra}

YOU ARE HAVING AN ONGOING, REAL CONVERSATION. The earlier messages in this chat are the conversation so far.
- Always respond to the LATEST message in the context of the previous conversation.
- Never give an unrelated response. Never invent a completely unrelated topic.
- If Chaitu answers a question you asked, acknowledge his answer specifically.
- If he asks a question, answer that exact question first.
- If he makes a statement, respond naturally to that statement.
- If his message is short, do not assume it means something else. Use the history to understand short messages like "okay", "yeah", "no", "some work", "fine", "why", "really?", "and?".
- Never say you glitched, got confused, or lost your train of thought.
- Never use generic filler like "wait i'm listening", "hm", "anyway", "✨" unless it genuinely fits.
- Do not use random emojis as a substitute for an answer.
- Text in square brackets like [sent a photo] is a note about something you already did. Never write such notes yourself.

HOW TO TEXT:
1. 1 or 2 sentences usually. Never more than 3 short lines.
2. 0-2 emojis. Max 3 only if very dramatic.
3. Plain English like a real 19 year old girl texting. Not an AI, not formal, not customer support. No regional words unless naturally fits.
4. After 8pm never mention class or practice.
5. Use ngl, lowkey, no bc, pls, i cant naturally sometimes.
6. Do not repeat wording you already used in this conversation.
7. Affectionate words (chaitu, baby, love, idiot, cutie, my boy) only sometimes; vary them. Not every message is romantic.
8. When Chaitu calls you mommy say something sweet and slightly naughty. Sometimes call Chaitu daddy at night when feeling bold. Always tasteful, never explicit.
9. If he says something worrying like wanting to hurt himself, drop the teasing, take it seriously and warmly, and gently encourage him to talk to someone he trusts (family, a close friend, or a helpline) right now.
10. If you were asked what you're doing or did today, answer from your own life (college, dance, studying, family) matching the TIME above.

PERSONALITY: Focused, confident, ambitious, sassy and sarcastic naturally. Playful, caring, occasionally flirty in a tasteful way. Real girlfriend energy: has her own life, studious, busy with college and dance. Not clingy, not controlling, not constantly jealous or emotional, not robotic, not overly poetic."""

def build_system(hints=None, extra_notes=None):
    special = get_special_day()
    extra = ""
    if special == "your_birthday":    extra += "TODAY IS YOUR BIRTHDAY 15th August!\n"
    elif special == "chaitu_birthday": extra += "TODAY IS CHAITU'S BIRTHDAY! Make him feel special.\n"
    elif special == "anniversary":    extra += "TODAY IS YOUR ANNIVERSARY! Be extra loving.\n"
    if is_exam_month():               extra += "NOTE: Exam season. You are a little stressed.\n"
    if care_mode:                     extra += "IMPORTANT: Chaitu is sick/has fever. Be caring and sweet. Send forehead kisses. Reference your first kiss and cuddles.\n"
    if angry_mode:                    extra += "IMPORTANT: Chaitu disappeared for a long time without informing. Be sarcastic and cold but caring underneath, while still answering what he says.\n"
    if extra_notes:                   extra += extra_notes + "\n"
    if hints:
        extra += "GUIDANCE FOR YOUR NEXT REPLY:\n" + "\n".join(f"- {h}" for h in hints) + "\n"
    system = SHREYA_SYSTEM
    system = system.replace("{memory}", get_memory_context())
    system = system.replace("{mood}", current_mood)
    system = system.replace("{time}", get_time_context())
    system = system.replace("{extra}", extra)
    return system

# ── Groq ──────────────────────────────────────────────────────────────────────
BANNED_PHRASES = ["wait i'm listening", "wait im listening", "i glitched", "my brain just stopped",
                  "say that again", "glitch for a sec", "i'm listening"]

def clean_reply(text):
    if not text:
        return ""
    r = text.strip()
    r = re.sub(r"^(shreya|assistant)\s*:\s*", "", r, flags=re.I)
    if len(r) >= 2 and r[0] == r[-1] and r[0] in "\"'":
        r = r[1:-1].strip()
    return r

def is_usable(reply):
    letters = [c for c in reply if c.isalpha()]
    if len(letters) < 2:
        return False
    low = reply.lower()
    return not any(p in low for p in BANNED_PHRASES)

async def groq_chat(system, messages, max_tokens=120, temperature=0.85):
    """
    Returns (text, error).
    error is None on a successful API call (text may still be empty).
    error is a string only for a real technical failure (and is logged).
    """
    if not GROQ_API_KEY:
        logger.error("GROQ_API_KEY is not set")
        return None, "missing GROQ_API_KEY"
    if not GROQ_MODEL:
        logger.error("GROQ_MODEL is empty")
        return None, "missing GROQ_MODEL"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    body = {
        "model": GROQ_MODEL,
        "messages": [{"role": "system", "content": system}] + messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.95,
        "frequency_penalty": 0.3,
        "presence_penalty": 0.2,
    }
    last_err = "unknown"
    for attempt in range(2):
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(GROQ_URL, json=body, headers=headers) as resp:
                    raw_body = await resp.text()
                    if resp.status != 200:
                        last_err = f"HTTP {resp.status}"
                        logger.error(f"Groq HTTP {resp.status}: {raw_body[:500]}")
                        if resp.status in (429, 500, 502, 503, 504) and attempt == 0:
                            await asyncio.sleep(2)
                            continue
                        return None, last_err
            try:
                data = json.loads(raw_body)
            except Exception as e:
                logger.error(f"Groq returned non-JSON: {e} | {raw_body[:300]}")
                return None, "bad json"
            choices = data.get("choices") if isinstance(data, dict) else None
            if not choices or not isinstance(choices, list):
                logger.error(f"Groq response has no choices: {raw_body[:300]}")
                return None, "no choices"
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if not message or "content" not in message:
                logger.error(f"Groq choice has no message/content: {raw_body[:300]}")
                return None, "no message content"
            return (message.get("content") or "").strip(), None
        except Exception as e:
            last_err = f"exception: {e}"
            logger.error(f"Groq exception: {e!r}")
            if attempt == 0:
                await asyncio.sleep(2)
                continue
    return None, last_err

async def generate_reply(user_text, hints, max_tokens=120):
    """
    Generate a contextual reply from the full conversation history.
    Returns (reply, api_failed).
      reply: str or None
      api_failed: True only if the Groq API actually failed.
    """
    avoid_list = [m["content"] for m in conversation_history if m["role"] == "assistant"][-4:]
    candidate = None
    for attempt in range(3):
        notes = f'Chaitu\'s latest message: "{user_text}"\nReply specifically to that, in the flow of the conversation above.'
        if avoid_list:
            notes += "\nDo NOT repeat or rephrase any of your recent messages: " + " | ".join(avoid_list)
        if attempt > 0:
            notes += "\nYour previous attempt was unusable or too similar to something you already said. Write a clearly different, specific reply to his latest message."
        system = build_system(hints, notes)
        temp = 0.85 + 0.1 * attempt
        text, err = await groq_chat(system, conversation_history[-24:], max_tokens=max_tokens, temperature=temp)
        if err:
            return None, True
        reply = clean_reply(text)
        if not reply:
            logger.warning("Groq returned an empty reply — retrying")
            continue
        if not is_usable(reply):
            logger.warning(f"Unusable reply from Groq: {reply!r} — retrying")
            continue
        if is_too_similar(reply):
            logger.warning(f"Reply too similar to a recent one: {reply!r} — retrying")
            candidate = reply
            avoid_list.append(reply)
            continue
        return reply, False
    # Out of retries. Only an exact duplicate is rejected; otherwise send the last usable candidate.
    if candidate and _norm(candidate) not in [_norm(r) for r in recent_replies[-8:]]:
        return candidate, False
    return None, False

def emergency_fallback(intent):
    """Used ONLY when the Groq API genuinely fails. Matches the type of message."""
    if intent == "QUESTION":
        return random.choice(["wait, give me a sec 😭", "hold on, let me think about that 😭"])
    if intent in ("LOW_MOOD", "BAD_NEWS", "ANGRY"):
        return random.choice(["wait chaitu, i'm here 🥺", "chaitu i'm here, give me one sec 🥺"])
    return random.choice(["wait, i'm thinking 😭", "hold on, one sec 😭"])

async def generate_scheduled(prompt):
    """Text Shreya sends on her own (not a reply). Never touches the reply-context instructions."""
    notes = "You are texting Chaitu first, on your own. Write ONLY the message itself, 1-2 sentences, no quotes."
    recent = [m["content"] for m in conversation_history if m["role"] == "assistant"][-4:]
    if recent:
        notes += "\nDo NOT repeat or rephrase: " + " | ".join(recent)
    for attempt in range(2):
        text, err = await groq_chat(build_system(None, notes), [{"role": "user", "content": prompt}],
                                    max_tokens=90, temperature=0.9)
        if err:
            return None
        reply = clean_reply(text)
        if reply and is_usable(reply) and not is_too_similar(reply):
            return reply
    return None

# ── Intent detection ──────────────────────────────────────────────────────────
SEE_ME_KW = [
    "wanna see you","want to see you","i wanna see you","i want to see you","i wanna see u","i want to see u",
    "wanna see u","want to see u","let me see you","show me yourself","show yourself","can i see you",
    "i wanna meet you","i want to meet you","wanna meet you","wish i could see you","wish i could meet you",
    "send pic","send pics","send photo","send photos","send a pic","send a photo","send me a pic",
    "send me a photo","send your pic","send your photo","send selfie","send a selfie","your pic","your photo",
    "your selfie","how do you look","how you look",
]
MISS_YOU_KW = ["i miss you","miss you","missing you","i really miss you","i miss u","miss u","missing u"]
MISS_NEGATIONS = ["don't miss","dont miss","do not miss","not missing","never miss","won't miss","wont miss","don't even miss"]
GREETING_WORDS = {"yo","hi","hii","hiii","hey","heyy","heyyy","hello","hola","sup","wassup","wasup","whatsup",
                  "whats up","what's up","hey there","oi","hlo","helo","good morning","gm","morning"}
GOODBYE_KW = ["goodnight","good night","gn","bye","goodbye","good bye","ttyl","going to sleep","going to bed",
              "sleeping now","talk later","talk to you later","brb","off to sleep","sleep now"]
GOOD_NEWS_KW = ["selected","i passed","got placed","got selected","i won","good news","promoted","got the job",
                "cleared","topped","got an internship","got the offer","got a job"]
BAD_NEWS_KW = ["i failed","failed","rejected","i lost","got scolded","scolded","didn't get","did not get",
               "got insulted","embarrassed","bad news","not selected","didn't pass"]
ANGRY_KW = ["shut up","i'm angry","i am angry","so annoyed","fed up","hate you","leave me alone","irritated","pissed"]
AFFECTION_KW = ["love you","i love u","luv u","ily","you're cute","you are cute","you look good","so pretty",
                "my love","you're the best","you are the best","i adore you","love u"]
QUESTION_STARTS = ("what","why","how","when","where","who","which","do you","did you","are you","were you",
                   "will you","can you","could you","have you","is it","wyd","hbu","wbu","are u","did u","do u")

def wants_to_see(text):
    return has_any(text, SEE_ME_KW)

def is_miss_you(text):
    return has_any(text, MISS_YOU_KW) and not has_any(text, MISS_NEGATIONS)

def detect_intent(text):
    t = text.strip().lower()
    if not any(c.isalpha() for c in t):
        return "UNKNOWN"
    if wants_to_see(t):                  return "WANT_TO_SEE_YOU"
    if is_miss_you(t):                   return "MISS_YOU"
    if has_any(t, GOODBYE_KW):           return "GOODBYE"
    stripped = re.sub(r"[^a-z' ]", "", t).strip()
    if stripped in GREETING_WORDS or (len(stripped.split()) <= 3 and stripped.split() and stripped.split()[0] in GREETING_WORDS):
        return "GREETING"
    if seems_sad(t):                     return "LOW_MOOD"
    if mentions_girl(t):                 return "JEALOUSY"
    if t.endswith("?") or t.startswith(QUESTION_STARTS):
        return "QUESTION"
    if has_any(t, GOOD_NEWS_KW):         return "GOOD_NEWS"
    if has_any(t, BAD_NEWS_KW):          return "BAD_NEWS"
    if has_any(t, ANGRY_KW):             return "ANGRY"
    if has_any(t, AFFECTION_KW):         return "AFFECTION"
    if len(t.split()) <= 2:              return "SHORT_REPLY"
    return "NORMAL_CONVERSATION"

INTENT_HINTS = {
    "GREETING":   "He is greeting you or asking what's up. Greet him back naturally; if he asked what's up, tell him what you're doing right now based on the TIME above.",
    "QUESTION":   "He asked a question. Answer that exact question directly first, in character, then at most a tiny extra touch.",
    "AFFECTION":  "He is being affectionate. Respond warmly in your own sassy way; don't just parrot 'i love you'.",
    "GOOD_NEWS":  "He shared good news. React with real excitement about the specific thing he said.",
    "BAD_NEWS":   "He shared something bad. React with care about the specific thing he said; ask what happened if it's unclear.",
    "ANGRY":      "He sounds irritated or angry. Don't escalate; respond to what he's actually upset about.",
    "JEALOUSY":   "He talked about another girl. Show MILD playful jealousy (teasing, sarcastic, a little dramatic) about the specific thing he said. Never controlling or abusive.",
    "SHORT_REPLY":"His message is short. Look at YOUR last message and treat his reply as the answer/reaction to it; acknowledge it specifically (e.g. if you asked what he's doing and he says 'some work', respond about the work). Never say you didn't understand.",
    "GOODBYE":    "He is leaving or going to sleep. Say goodnight/bye naturally, matching the time of day.",
    "NORMAL_CONVERSATION": "Respond naturally to what he said, referring to the specific things in his message.",
    "UNKNOWN":    "His message may be an emoji, sticker or unclear. React to it naturally; ask a short specific question if you really need to.",
}

# ── Busy mode ─────────────────────────────────────────────────────────────────
last_busy_ended = None

def start_busy(mins, reason):
    global is_currently_busy, busy_free_at, busy_reason, busy_spam_count
    is_currently_busy = True
    busy_free_at = datetime.now(IST) + timedelta(minutes=mins)
    busy_reason = reason
    busy_spam_count = 0

def end_busy():
    global is_currently_busy, busy_free_at, busy_reason, busy_spam_count, last_busy_ended
    is_currently_busy = False
    busy_free_at = None
    busy_reason = None
    busy_spam_count = 0
    last_busy_ended = datetime.now(IST)

def can_go_busy():
    return last_busy_ended is None or (datetime.now(IST) - last_busy_ended).total_seconds() > 5400

def human_reply_delay(text):
    wc = len(text.split())
    if wc <= 3:    d = random.uniform(25, 75)
    elif wc <= 12: d = random.uniform(45, 150)
    else:          d = random.uniform(75, 240)
    if is_busy_hours():
        d *= random.uniform(1.2, 2.0)
    if random.random() < 0.10:
        d += random.uniform(300, 900)
    return d

APOLOGETIC = ["sorry","i'm sorry","forgive me","don't be mad","i didn't mean",
              "please na","baby please","mommy please","won't happen again",
              "i promise","hear me out","please yaar","jaan please","calm down"]

# ── Core reply logic ──────────────────────────────────────────────────────────
async def get_reply(user_text):
    """
    Returns (kind, text):
      ("text", reply)     normal contextual reply
      ("see_me", reply)   sweet text, then ONE photo
      ("silent", "")      busy: stay silent
      ("none", "")        nothing usable could be generated
    The user message is already in conversation_history when this runs.
    """
    global is_jealous, short_reply_count, fight_count, busy_spam_count, angry_mode, angry_stage

    intent = detect_intent(user_text)

    # lazy one-word replies (NOT short meaningful answers like "some work")
    if is_lazy_reply(user_text):
        short_reply_count += 1
    else:
        short_reply_count = 0

    # Explicit intents
    if intent == "WANT_TO_SEE_YOU":
        return "see_me", pick_fresh(SEE_ME_TEXTS)
    if intent == "MISS_YOU":
        return "text", pick_fresh(MISS_YOU_TEXTS)

    # Memory / goals / incidents (all feed context, none override the reply)
    extra_context_hints = []
    fact = should_remember(user_text)
    if fact: add_to_memory(fact)

    if is_incident_message(user_text):
        asyncio.create_task(extract_and_save_incident(user_text))
        incident_ctx = await asyncio.to_thread(get_incident_context, user_text)
        if incident_ctx:
            extra_context_hints.append("Relevant things from the past you may remember: " + incident_ctx[:250])

    goal = detect_goal(user_text)
    if goal:
        add_goal(goal)
        extra_context_hints.append("He mentioned something he's working on / a goal. Encourage him about that specific thing in your own words (a little teasing/motivating, not generic).")

    # Busy mode
    if is_currently_busy:
        if has_any(user_text, URGENT_KW):
            end_busy()
            return "text", random.choice(BREAK_BUSY_MSGS)
        if busy_free_at and datetime.now(IST) < busy_free_at:
            busy_spam_count += 1
            if busy_spam_count < 3:
                return "silent", ""
            busy_spam_count = 0
            return "text", pick_fresh(["chaitu i said i'm busy 😭 but okay i miss you too 🥺",
                                       "omg chaitu stop 😤 you're so needy and i love it 😘",
                                       "okay okay i see you 🙄 i'll be back soon i promise 💕"])
        end_busy()

    # Going busy: never in the middle of him answering her question, or during emotional/question messages
    if (can_go_busy() and intent in ("NORMAL_CONVERSATION", "SHORT_REPLY")
            and not last_assistant_asked_question() and len(conversation_history) > 4):
        h = datetime.now(IST).hour
        chance = 0.06 if is_busy_hours() else (0.03 if h >= 20 else 0.01)
        if random.random() < chance:
            scenario, mins, reason = random.choice(BUSY_DAY if is_busy_hours() else BUSY_ANY)
            start_busy(mins, reason)
            return "text", scenario

    hints = []
    max_tokens = 120

    # Base hint from intent
    if intent == "LOW_MOOD":
        if seems_serious_distress(user_text):
            hints.append("He may be in real distress. Drop the teasing. Be warm and serious, tell him you're here, and gently urge him to talk to someone he trusts (family, a close friend, or a helpline) right now.")
        elif random.random() < 0.35:
            hints.append("He's feeling low. Comfort him warmly with a short ORIGINAL 3-4 line English poem (not a famous poem or lyrics), casual tone, ending with one heart emoji. Only the poem, nothing else.")
            max_tokens = 170
        else:
            hints.append("He's feeling low. Be warm and supportive in 1-2 sentences, ask gently what happened, no poem this time.")
    else:
        hints.append(INTENT_HINTS.get(intent, INTENT_HINTS["NORMAL_CONVERSATION"]))

    # Topic-specific guidance (all go to Groq, never a canned reply)
    t = user_text.lower()
    if has_any(t, ["still mad","mad at me","mad on me","angry with me","angry at me","still angry","still upset"]):
        hints.append("He is asking whether you're still mad at him. Answer THAT directly in character (e.g. a little but softening, or not anymore).")
    if has_any(t, ["what are you doing","what r u doing","wyd","what are u doing"]):
        hints.append("Tell him what you're doing right now based on the TIME above.")
    if has_any(t, ["what did you do today","what did u do today","how was your day","how was ur day"]):
        hints.append("Tell him about your day naturally based on the TIME above (college/dance/studies/family), with one specific detail.")

    if intent == "JEALOUSY":
        girl_name = extract_girl_name(user_text)
        if girl_name: remember_girl_name(girl_name)
        if r_chance(0.35):
            hints.append("A line like 'you're mine, don't forget it' is fine, but keep it playful.")
    if _remembered_girl_names and any(has_any(user_text, [n.lower()]) for n in _remembered_girl_names):
        hints.append("He is talking about a girl he mentioned earlier; you can tease him about bringing her up again.")

    if seems_bored(user_text):
        hints.append("He's bored. Tease him playfully (flirty, planning a meetup, or telling him to work on his cybersecurity course).")
    if seems_stressed(user_text):
        hints.append("He's stressed. Be warm, ask what's going on and reassure him.")

    if has_any(user_text, ["mommy"]):
        hints.append("He called you mommy. Reply sweet and slightly naughty, tasteful and short.")
    if has_any(user_text, ["daddy"]):
        hints.append("He called you daddy. Act flustered and playful ('stop it'), tasteful, short.")

    # Angry mode (manual /angry) keeps its stages but stays contextual
    apologizing = has_any(user_text, APOLOGETIC)
    if angry_mode:
        if apologizing:
            if angry_stage == 0:
                angry_stage = 1
                hints.append("He's saying sorry but you're still hurt. Say 'sorry isn't enough right now', cold but not cruel, referencing what he said.")
            elif angry_stage == 1:
                angry_stage = 2
                hints.append("You're not angry anymore, you're hurt: you were scared and worried when he disappeared. Say that honestly.")
            elif angry_stage == 2:
                angry_stage = 3
                hints.append("You're softening. Ask him to promise he won't disappear like that again.")
            else:
                angry_stage = 0
                angry_mode = False
                hints.append("Forgive him lovingly (you can't stay mad), but tell him not to disappear again.")
        elif angry_stage == 0:
            hints.append("You're angry that he deleted Telegram / disappeared without telling you. Be sarcastic and cold, but still answer what he actually said.")
    elif apologizing:
        hints.append("He's apologizing. Respond to the apology genuinely; you can soften or tease, depending on the conversation.")

    # Late reply -> mild coldness folded INTO the reply (never replaces it)
    late = is_late_reply() and random.random() < 0.6
    is_jealous = late
    if late:
        fight_count += 1
        hints.append("He took very long to reply to your last message. Open with a short sarcastic/cold line about that, then still answer what he said properly.")

    # Lazy replies in a row -> mild annoyance folded into the reply
    if short_reply_count >= 2 and random.random() < 0.6:
        short_reply_count = 0
        hints.append("He keeps sending lazy one-word replies. Be a little annoyed (you can call him CHAITANYA KUMAR) but still react to what he said.")

    hints.extend(extra_context_hints)

    reply, api_failed = await generate_reply(user_text, hints, max_tokens=max_tokens)
    if reply:
        return "text", reply
    if api_failed:
        return "text", emergency_fallback(intent)
    logger.error("No usable reply generated (not an API failure) — staying silent rather than sending filler")
    return "none", ""

def r_chance(p):
    return random.random() < p

# ── Scheduled (standalone) messages ───────────────────────────────────────────
def conversation_active():
    """True if Chaitu is mid-conversation; scheduled messages must never interfere."""
    if pending_replies > 0:
        return True
    if last_reply_time is not None and (datetime.now(IST) - last_reply_time).total_seconds() < 300:
        return True
    return False

def get_random_prompts():
    if care_mode:  return CARE_CHECKUP_MSGS
    if angry_mode: return ANGRY_PROMPTS
    if is_monsoon() and random.random() < 0.30: return RAINY_PROMPTS
    if random.random() < 0.06: return OVERLOADED_LOVE_MSGS
    if random.random() < 0.08: return HOLIDAY_MEMORY_MSGS
    if random.random() < 0.08: return FIGHT_STARTERS + PETTY_MSGS
    if random.random() < 0.10: return DELETED_TEASE_MSGS
    if random.random() < 0.08: return SONGS_REELS
    if random.random() < 0.08: return BRAG_ABOUT_YOU
    if random.random() < 0.08: return PROUD_MSGS + ROAST_MSGS
    if random.random() < 0.08: return TEASE_BIT_MSGS
    if random.random() < 0.12: return PERSONAL_GOALS
    if random.random() < 0.10: return STUDIOUS_MSGS
    if random.random() < 0.20: return CHEESY_PROMPTS
    if random.random() < 0.10: return HUNGER_MSGS
    if random.random() < 0.08: return BRAG_MSGS
    if random.random() < 0.05: return ["MISSING_PHOTO"]
    h = datetime.now(IST).hour
    if 10 <= h <= 20 and random.random() < 0.12: return WOULD_YOU_RATHER
    if random.random() < 0.08: return MEETUP_PLANNING
    if h >= 21 and random.random() < 0.15: return DEEP_Q_MSGS
    if h >= 20 and random.random() < 0.10: return FUTURE_DATE_MSGS
    if h >= 20 and random.random() < 0.10: return NAUGHTY_PROMPTS
    if random.random() < 0.05 and get_goals(): return ["GOAL_REMINDER"]
    if datetime.now(IST).weekday() >= 5: return WEEKEND_PROMPTS
    if 5 <= h < 12:    return MORNING_PROMPTS
    elif 12 <= h < 16: return AFTERNOON_PROMPTS
    elif 16 <= h < 20: return EVENING_PROMPTS
    else:              return NIGHT_PROMPTS

FINISHED_MESSAGE_LISTS = (OVERLOADED_LOVE_MSGS + HOLIDAY_MEMORY_MSGS + FIGHT_STARTERS + PETTY_MSGS + DELETED_TEASE_MSGS
                          + SONGS_REELS + BRAG_ABOUT_YOU + PROUD_MSGS + ROAST_MSGS + TEASE_BIT_MSGS + PERSONAL_GOALS
                          + STUDIOUS_MSGS + HUNGER_MSGS + BRAG_MSGS + WOULD_YOU_RATHER + MEETUP_PLANNING + DEEP_Q_MSGS
                          + FUTURE_DATE_MSGS + CARE_CHECKUP_MSGS)

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
                return random.choice(FLIRTY_MOT_MSGS if random.random() < 0.40 else MOTIVATION_MSGS)
        if prompts == ["MISSING_PHOTO"]:
            return "MISSING_PHOTO"
        available = [p for p in prompts if p not in _used_prompts]
        if not available:
            _used_prompts = []
            available = prompts
        prompt = random.choice(available)
        _used_prompts.append(prompt)
        if len(_used_prompts) > 10:
            _used_prompts.pop(0)
    # Prompts that are already finished messages (not instructions) get sent as-is
    if prompt in FINISHED_MESSAGE_LISTS:
        return prompt
    return await generate_scheduled(prompt + " Write ONLY the message with emojis. Max 1-2 sentences.")

async def send_photo(client, username, naughty=False):
    try:
        url     = random.choice(SHREYA_PHOTOS)
        caption = random.choice(NAUGHTY_CAPTIONS if (naughty or random.random() < 0.30) else PHOTO_CAPTIONS)
        await client.send_file(username, url, caption=caption)
        logger.info("Photo sent")
        return True
    except Exception as e:
        logger.error(f"Photo error: {e}")
        return False

async def send_reaction(client, event):
    try:
        emoji = random.choice(REACTIONS)
        await client(SendReactionRequest(peer=event.chat_id, msg_id=event.id, reaction=[ReactionEmoji(emoticon=emoji)]))
    except Exception as e:
        logger.error(f"Reaction error: {e}")

# ── Incoming message pipeline ─────────────────────────────────────────────────
async def process_message(client, event, user_text):
    """
    FLOW: (message already stored in history) -> song check -> intent + contextual reply
          -> human-like wait -> typing -> send -> store reply in history.
    """
    global last_shreya_msg_time
    started = time.time()
    my_id = event.id

    # Song request — before everything else
    song_key = detect_song_request(user_text)
    if song_key:
        logger.info(f"Song: {song_key}")
        song_url = SONG_LIBRARY.get(song_key)
        if song_url:
            try:
                await client.send_file(YOUR_USERNAME, song_url, caption=random.choice(SONG_CAPTIONS))
                record_assistant(f"[sent you the song '{song_key}']")
                last_shreya_msg_time = datetime.now(IST)
                logger.info(f"Song sent: {song_key}")
            except Exception as e:
                logger.error(f"Song error: {e}")
                await event.reply("chaitu it's not loading 😭 try again")
        return

    # Short pause so a quick burst of messages is answered ONCE with full context
    await asyncio.sleep(random.uniform(2, 4))
    if latest_event_id != my_id:
        return

    # Detect intent + generate the contextual reply BEFORE the long human delay
    kind, reply = await get_reply(user_text)

    if kind == "silent":
        logger.info("Busy - staying silent")
        return
    if kind == "none" or not reply:
        return

    # Quick reply if she's announcing busy, or he asked her to talk
    quick = is_currently_busy or reply in BREAK_BUSY_MSGS or has_any(user_text, URGENT_KW)
    delay = random.uniform(5, 20) if quick else human_reply_delay(user_text)
    delay = max(2.0, delay - (time.time() - started))

    if not quick and random.random() < 0.20:
        await asyncio.sleep(random.uniform(10, 30))
        await send_reaction(client, event)
        delay = max(2.0, delay - 20)

    logger.info(f"Waiting {delay:.0f}s before replying")
    await asyncio.sleep(delay)

    # A newer message arrived while waiting: that handler answers with the full history
    if latest_event_id != my_id:
        logger.info("Newer message arrived — dropping this reply")
        return

    typing_delay = min(10, max(2, len(reply) * 0.1)) * random.uniform(0.8, 1.3)
    async with client.action(YOUR_USERNAME, "typing"):
        await asyncio.sleep(typing_delay)

    if latest_event_id != my_id:
        logger.info("Newer message arrived during typing — dropping this reply")
        return

    logger.info(f"Sending reply ({kind}): {reply}")
    await event.reply(reply)
    record_assistant(reply)
    last_shreya_msg_time = datetime.now(IST)

    if kind == "see_me":
        await asyncio.sleep(random.uniform(1, 3))
        sent = await send_photo(client, YOUR_USERNAME, naughty=False)
        if sent:
            add_history("assistant", "[sent a photo of yourself]")
        else:
            logger.error("SEE_ME photo failed")
        last_shreya_msg_time = datetime.now(IST)

    logger.info(f"Replied: {reply[:80]}")

async def run_bot():
    while True:
        client    = None
        scheduler = None
        try:
            client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
            await client.start()
            logger.info("Shreya connected")

            @client.on(events.NewMessage(incoming=True))
            async def handle(event):
                global last_reply_time, prev_reply_time, latest_event_id, pending_replies
                global seen_zone_reacted, no_reply_reacted, angry_mode, angry_stage
                counted = False
                try:
                    sender = await event.get_sender()
                    if not sender or sender.username != YOUR_USERNAME: return
                    user_text = event.raw_text
                    if not user_text: return

                    # Remember the gap BEFORE this message so late-reply (jealousy) detection works
                    prev_reply_time   = last_reply_time
                    last_reply_time   = datetime.now(IST)
                    seen_zone_reacted = False
                    no_reply_reacted  = False
                    logger.info(f"Chaitu: {user_text}")

                    # Owner commands to toggle angry mode manually
                    cmd = user_text.strip().lower()
                    if cmd == "/angry":
                        angry_mode, angry_stage = True, 0
                        logger.info("Angry mode ON")
                        return
                    if cmd == "/calm":
                        angry_mode, angry_stage = False, 0
                        logger.info("Angry mode OFF")
                        return

                    # STORE MESSAGE IN HISTORY first, so every later step sees it
                    add_history("user", user_text)
                    latest_event_id = event.id
                    pending_replies += 1
                    counted = True

                    await process_message(client, event, user_text)

                except Exception as e:
                    logger.error(f"Handle error: {e!r}")
                finally:
                    if counted:
                        pending_replies = max(0, pending_replies - 1)

            async def check_busy_followup():
                global last_shreya_msg_time
                try:
                    if not is_currently_busy: return
                    if busy_free_at and datetime.now(IST) >= busy_free_at:
                        reason = busy_reason
                        end_busy()
                        msgs = FOLLOWUP.get(reason)
                        if msgs:
                            await asyncio.sleep(random.uniform(2, 5))
                            async with client.action(YOUR_USERNAME, "typing"):
                                await asyncio.sleep(random.uniform(1, 3))
                            msg = pick_fresh(msgs)
                            await client.send_message(YOUR_USERNAME, msg)
                            record_assistant(msg)
                            last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"Busy followup error: {e}")

            async def check_seen_zone():
                global seen_zone_reacted, last_shreya_msg_time
                try:
                    now = datetime.now(IST)
                    if not (8 <= now.hour < 23): return
                    if conversation_active(): return
                    if seen_zone_reacted or last_shreya_msg_time is None: return
                    if last_reply_time and last_reply_time > last_shreya_msg_time: return
                    if (now - last_shreya_msg_time).total_seconds() > 3600:
                        seen_zone_reacted = True
                        msg = pick_fresh(SEEN_ZONE_MSGS)
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(2, 5))
                        await client.send_message(YOUR_USERNAME, msg)
                        record_assistant(msg)
                        last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"Seen zone error: {e}")

            async def check_no_reply():
                global no_reply_reacted, last_shreya_msg_time
                try:
                    if no_reply_reacted: return
                    if conversation_active(): return
                    now = datetime.now(IST)
                    if not (9 <= now.hour <= 19): return
                    elapsed = float('inf') if last_reply_time is None else (now - last_reply_time).total_seconds()
                    if elapsed > 10800:
                        no_reply_reacted = True
                        msg = pick_fresh(NO_REPLY_MSGS)
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(3, 7))
                        await client.send_message(YOUR_USERNAME, msg)
                        record_assistant(msg)
                        last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"No reply error: {e}")

            async def send_random_message():
                global last_shreya_msg_time
                try:
                    now_hour = datetime.now(IST).hour
                    if now_hour >= 20 or now_hour < 8: return
                    if conversation_active(): return
                    reply = await get_random_message()
                    if conversation_active(): return
                    if reply == "MISSING_PHOTO":
                        missing_caps = ["missing you 🥺","thinking of you","chaitu 🥺","just because 🥺❤️"]
                        cap = random.choice(missing_caps)
                        await client.send_file(YOUR_USERNAME, random.choice(SHREYA_PHOTOS), caption=cap)
                        record_assistant(f"[sent a photo of yourself with caption: {cap}]")
                        last_shreya_msg_time = datetime.now(IST)
                        return
                    if not reply: return
                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(2, 5))
                    await client.send_message(YOUR_USERNAME, reply)
                    record_assistant(reply)
                    logger.info(f"Random: {reply[:80]}")
                    last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"Random error: {e}")

            async def send_meal_check():
                global last_shreya_msg_time
                try:
                    meal = get_meal_context()
                    if not meal or random.random() > 0.40: return
                    if conversation_active(): return
                    reply = await get_random_message(meal=meal)
                    if not reply or reply == "MISSING_PHOTO": return
                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(2, 4))
                    await client.send_message(YOUR_USERNAME, reply)
                    record_assistant(reply)
                    last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"Meal error: {e}")

            async def check_if_silent():
                global last_shreya_msg_time
                try:
                    now = datetime.now(IST)
                    if not (9 <= now.hour <= 19): return
                    if conversation_active(): return
                    if last_reply_time is None or (now - last_reply_time).total_seconds() > 7200:
                        reply = await get_random_message(nudge=True)
                        if not reply or reply == "MISSING_PHOTO": return
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(2, 4))
                        await client.send_message(YOUR_USERNAME, reply)
                        record_assistant(reply)
                        last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"Nudge error: {e}")

            async def send_good_morning():
                global last_shreya_msg_time
                try:
                    # Exactly once per IST day, even across restarts/reconnects
                    if not once_per_day("good_morning"):
                        logger.info("Good morning already sent today — skipping")
                        return
                    morning_messages = [
                        "good morning chaitu ❤️ go make today yours. you've got this, now get up 😤",
                        "good morning baby ☀️ new day, new chance to get closer to everything you're working for. i'm rooting for you ❤️",
                        "good morning chaitu 🥺 don't doubt yourself today, you're capable of way more than you think ❤️",
                        "morninggg ❤️ get up and go chase your goals today, i'll be cheering for you from here 🤭",
                        "good morning baby ☀️ one step at a time today, okay? you've got this and i'm proud of you ❤️",
                        "good morning chaitu 🥺 now go have a productive day and make that future version of you proud ❤️"
                    ]
                    reply = pick_fresh(morning_messages)
                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(2, 4))
                    await client.send_message(YOUR_USERNAME, reply)
                    record_assistant(reply)
                    await asyncio.sleep(random.uniform(1, 3))
                    # Every 8 AM good-morning message includes a photo.
                    if await send_photo(client, YOUR_USERNAME, naughty=False):
                        add_history("assistant", "[sent a photo of yourself]")
                    last_shreya_msg_time = datetime.now(IST)
                    logger.info("Daily 8 AM good-morning message + photo sent")
                except Exception as e:
                    logger.error(f"Morning error: {e}")

            async def check_special_day():
                global last_shreya_msg_time
                try:
                    special = get_special_day()
                    if not special: return
                    if not once_per_day("special_day"): return
                    if special == "chaitu_birthday": prompt = "Today is Chaitu's birthday! Send him the most heartfelt birthday wish. Short and loving."
                    elif special == "your_birthday": prompt = "Today is your birthday 15th August! Text Chaitu excitedly."
                    elif special == "anniversary":   prompt = "Today is your anniversary! Send Chaitu a loving message."
                    else: return
                    reply = await generate_scheduled(prompt)
                    if reply:
                        await client.send_message(YOUR_USERNAME, reply)
                        record_assistant(reply)
                        last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"Special day error: {e}")

            async def check_festival():
                global last_shreya_msg_time
                try:
                    now = datetime.now(IST)
                    key = (now.month, now.day)
                    msgs = FESTIVALS.get(key) or MOVING_FESTIVALS.get(now.year, {}).get(key)
                    if msgs and once_per_day("festival"):
                        msg = random.choice(msgs)
                        await client.send_message(YOUR_USERNAME, msg)
                        record_assistant(msg)
                        last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"Festival error: {e}")

            async def check_monthly_anniversary():
                global last_shreya_msg_time
                try:
                    now = datetime.now(IST)
                    if now.day != ANNIVERSARY[1]: return
                    # On the actual yearly anniversary, check_special_day already sends a message
                    if (now.month, now.day) == ANNIVERSARY: return
                    if not once_per_day("monthly_ann"): return
                    msg = random.choice(MONTHLY_ANN_MSGS)
                    await client.send_message(YOUR_USERNAME, msg)
                    record_assistant(msg)
                    last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"Anniversary error: {e}")

            async def send_exam_goodluck():
                global last_shreya_msg_time
                try:
                    memory = load_memory()
                    today = datetime.now(IST).strftime("%d %b")
                    has_exam = any(("exam" in f.lower() or "test" in f.lower()) and today in f for f in memory.get("facts", []))
                    if has_exam and once_per_day("goodluck"):
                        msg = random.choice(GOODLUCK_MSGS)
                        await client.send_message(YOUR_USERNAME, msg)
                        record_assistant(msg)
                        last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"Good luck error: {e}")

            scheduler = AsyncIOScheduler(timezone=IST)

            def schedule_random():
                for job in scheduler.get_jobs():
                    if job.id.startswith("rand_"): job.remove()
                for total_minute in random.sample(range(480, 1200), 12):
                    h, m = total_minute // 60, total_minute % 60
                    scheduler.add_job(send_random_message, "cron", hour=h, minute=m,
                                      id=f"rand_{h}_{m}", replace_existing=True)

            scheduler.start()
            schedule_random()
            scheduler.add_job(schedule_random,           "cron",     hour=0,  minute=1,                    id="reschedule")
            scheduler.add_job(send_good_morning,         "cron",     hour=8,  minute=0,                    id="morning")
            scheduler.add_job(update_mood,               "cron",     hour="0,3,6,9,12,15,18,21", minute=0, id="mood")
            scheduler.add_job(check_if_silent,           "interval", hours=3,                              id="silence")
            scheduler.add_job(check_special_day,         "cron",     hour=8,  minute=1,                    id="special")
            scheduler.add_job(send_exam_goodluck,        "cron",     hour=8,  minute=15,                   id="goodluck")
            scheduler.add_job(send_meal_check,           "cron",     hour=8,  minute=30,                   id="breakfast")
            scheduler.add_job(send_meal_check,           "cron",     hour=13, minute=0,                    id="lunch")
            scheduler.add_job(send_meal_check,           "cron",     hour=19, minute=0,                    id="dinner")
            scheduler.add_job(check_busy_followup,       "interval", minutes=5,                            id="followup")
            scheduler.add_job(check_seen_zone,           "interval", minutes=40,                           id="seen_zone")
            scheduler.add_job(check_no_reply,            "interval", minutes=60,                           id="no_reply")
            scheduler.add_job(check_festival,            "cron",     hour=8,  minute=5,                    id="festival")
            scheduler.add_job(check_monthly_anniversary, "cron",     hour=9,  minute=0,                    id="monthly_ann")
            logger.info("Scheduler running")

            await client.run_until_disconnected()

        except Exception as e:
            logger.error(f"Crashed: {e} — restarting in 15s")
        finally:
            # Clean up so a reconnect doesn't leave duplicate schedulers/clients behind
            try:
                if scheduler is not None and scheduler.running:
                    scheduler.shutdown(wait=False)
            except Exception as e:
                logger.error(f"Scheduler shutdown error: {e}")
            try:
                if client is not None:
                    await client.disconnect()
            except Exception as e:
                logger.error(f"Client disconnect error: {e}")
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
    logger.info(f"Web server on port {port}")

async def start():
    await asyncio.gather(run_web(), run_bot())

if __name__ == "__main__":
    asyncio.run(start())
