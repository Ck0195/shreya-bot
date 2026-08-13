import os, asyncio, random, logging, re, json, sqlite3
import aiohttp, pytz
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
from aiohttp import web

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ── ENV ────────────────────────────────────────────────────────────────────────
API_ID         = int(os.environ.get("API_ID", "0"))
API_HASH       = os.environ.get("API_HASH", "")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
YOUR_USERNAME  = os.environ.get("YOUR_USERNAME", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
IST            = pytz.timezone("Asia/Kolkata")
DB_PATH        = os.environ.get("DB_PATH", "/tmp/shreya2.db")
GROQ_URL       = "https://api.groq.com/openai/v1/chat/completions"

# ── DATABASE ───────────────────────────────────────────────────────────────────
def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS memory(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            value TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS goals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal TEXT NOT NULL UNIQUE,
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            name TEXT NOT NULL,
            duration_mins INTEGER DEFAULT 60,
            energy TEXT DEFAULT 'medium',
            priority TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'pending',
            time_slot TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS daily_plans(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            plan_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS proactive_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            sent_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mem_cat ON memory(category);
        CREATE INDEX IF NOT EXISTS idx_tasks_date ON tasks(date);
        """)
    logger.info("DB ready")

def now_ist(): return datetime.now(IST).isoformat()
def today_str(): return datetime.now(IST).strftime("%Y-%m-%d")

def db_add_memory(category, value):
    with sqlite3.connect(DB_PATH) as c:
        existing = c.execute("SELECT id FROM memory WHERE category=? AND value=?", (category, value)).fetchone()
        if not existing:
            c.execute("INSERT INTO memory(category,value,created_at) VALUES(?,?,?)", (category, value[:300], now_ist()))

def db_forget(fragment):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("DELETE FROM memory WHERE value LIKE ?", (f"%{fragment}%",))

def db_get_memory_context():
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute("SELECT category, value FROM memory ORDER BY created_at DESC LIMIT 60").fetchall()
    by_cat = {}
    for cat, val in rows:
        by_cat.setdefault(cat, []).append(val)
    parts = []
    for cat, vals in by_cat.items():
        parts.append(f"[{cat.upper()}] " + " | ".join(vals[:5]))
    goals = db_get_goals()
    if goals:
        parts.append("[GOALS] " + " | ".join(g["goal"] for g in goals[:5]))
    return "\n".join(parts)

def db_add_goal(goal_text):
    with sqlite3.connect(DB_PATH) as c:
        try:
            c.execute("INSERT INTO goals(goal,status,created_at) VALUES(?,?,?)", (goal_text[:200], "active", now_ist()))
        except sqlite3.IntegrityError:
            pass

def db_get_goals():
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute("SELECT id, goal, status FROM goals WHERE status='active' ORDER BY created_at DESC LIMIT 10").fetchall()
    return [{"id": r[0], "goal": r[1], "status": r[2]} for r in rows]

def db_save_plan(date, blocks):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("INSERT OR REPLACE INTO daily_plans(date,plan_json,created_at) VALUES(?,?,?)",
                  (date, json.dumps(blocks), now_ist()))
        c.execute("DELETE FROM tasks WHERE date=?", (date,))
        for b in blocks:
            if b.get("type") == "task":
                c.execute("INSERT INTO tasks(date,name,duration_mins,energy,priority,status,time_slot,created_at) VALUES(?,?,?,?,?,?,?,?)",
                          (date, b["name"], b.get("duration_mins", 60), b.get("energy","medium"),
                           b.get("priority","medium"), "pending", b.get("time",""), now_ist()))

def db_get_plan(date):
    with sqlite3.connect(DB_PATH) as c:
        row = c.execute("SELECT plan_json FROM daily_plans WHERE date=?", (date,)).fetchone()
    return json.loads(row[0]) if row else None

def db_mark_done(date, fragment):
    with sqlite3.connect(DB_PATH) as c:
        row = c.execute("SELECT id, name FROM tasks WHERE date=? AND name LIKE ? AND status='pending' LIMIT 1",
                        (date, f"%{fragment}%")).fetchone()
        if row:
            c.execute("UPDATE tasks SET status='completed' WHERE id=?", (row[0],))
            # update plan json
            plan_row = c.execute("SELECT plan_json FROM daily_plans WHERE date=?", (date,)).fetchone()
            if plan_row:
                plan = json.loads(plan_row[0])
                for b in plan:
                    if fragment.lower() in b.get("name","").lower():
                        b["status"] = "completed"
                c.execute("UPDATE daily_plans SET plan_json=? WHERE date=?", (json.dumps(plan), date))
            return row[1]
    return None

def db_get_day_summary(date):
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute("SELECT name, status FROM tasks WHERE date=?", (date,)).fetchall()
    done    = [r[0] for r in rows if r[1] == "completed"]
    pending = [r[0] for r in rows if r[1] == "pending"]
    return done, pending

def db_log_proactive(category):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("INSERT INTO proactive_log(category,sent_at) VALUES(?,?)", (category, now_ist()))

def db_recent_proactive(category, hours=4):
    cutoff = (datetime.now(IST) - timedelta(hours=hours)).isoformat()
    with sqlite3.connect(DB_PATH) as c:
        row = c.execute("SELECT id FROM proactive_log WHERE category=? AND sent_at>? LIMIT 1",
                        (category, cutoff)).fetchone()
    return row is not None

# ── GLOBAL STATE ───────────────────────────────────────────────────────────────
conversation_history   = []
is_currently_busy      = False
busy_free_at           = None
busy_reason            = None
last_reply_time        = None
is_jealous             = False
short_reply_count      = 0
recent_replies         = []
current_mood           = "happy"
angry_mode             = False
angry_stage            = 0
care_mode              = False
last_shreya_msg_time   = None
seen_zone_reacted      = False
no_reply_reacted       = False
busy_spam_count        = 0
_used_prompts          = []
_remembered_girl_names = []

# ── MOOD ───────────────────────────────────────────────────────────────────────
MOODS = ["happy","playful","loving","normal","teasing","annoyed","jealous","tired","excited","concerned","proud","chill"]

def set_mood(m, reason=""):
    global current_mood
    if m in MOODS:
        current_mood = m
        logger.info(f"Mood → {m} ({reason})")

def mood_context():
    descs = {
        "happy":     "cheerful, light, easy to talk to",
        "playful":   "playful, teasy, slightly sarcastic",
        "loving":    "extra affectionate and soft today",
        "normal":    "relaxed and normal",
        "teasing":   "sarcastic and teasing",
        "annoyed":   "a little annoyed — too many lazy replies",
        "jealous":   "slightly cold and jealous",
        "tired":     "tired, slower replies",
        "excited":   "energetic and excited",
        "concerned": "worried and caring about Chaitu",
        "proud":     "proud of Chaitu",
        "chill":     "relaxed and chill",
    }
    return descs.get(current_mood, "normal")

def random_mood_shift():
    h = datetime.now(IST).hour
    if h < 8:   set_mood(random.choice(["tired","chill"]), "morning")
    elif h < 12: set_mood(random.choice(["happy","playful","chill"]), "morning vibe")
    elif h < 17: set_mood(random.choice(["normal","teasing","chill"]), "afternoon drift")
    elif h < 20: set_mood(random.choice(["happy","playful","loving"]), "evening free")
    else:        set_mood(random.choice(["loving","playful","teasing"]), "night mode")

# ── TIME HELPERS ───────────────────────────────────────────────────────────────
def get_time_context():
    h = datetime.now(IST).hour
    wd = datetime.now(IST).weekday()
    wknd = wd >= 5
    if 5 <= h < 9:    return "early morning, just woke up, sleepy"
    elif 9 <= h < 13: return "weekend morning, completely free" if wknd else "morning, in college at Ramaiah ISC"
    elif 13 <= h < 15: return "weekend afternoon, relaxing" if wknd else "afternoon, lunch break at college"
    elif 15 <= h < 18: return "weekend evening, free" if wknd else "late afternoon, college or dance practice"
    elif 18 <= h < 20: return "evening, done with college, relaxing at home"
    else:              return "night, at home, fully free and relaxed"

def is_weekend(): return datetime.now(IST).weekday() >= 5
def is_busy_hours():
    if is_weekend(): return False
    return 9 <= datetime.now(IST).hour < 18

def get_meal_context():
    h = datetime.now(IST).hour
    if 7 <= h <= 10:   return "breakfast"
    elif 12 <= h <= 14: return "lunch"
    elif 19 <= h <= 21: return "dinner"
    return None

CHAITU_BIRTHDAY = (6, 15)
ANNIVERSARY     = (1, 1)
SHREYA_BIRTHDAY = (8, 15)
FESTIVALS = {
    (3,14):["happy holi chaitu 🎨😂 don't you dare put colour on me"],
    (10,2):["happy dussehra chaitu 🙏❤️"],
    (10,20):["happy diwali chaitu 🪔✨ stay safe okay 🥺"],
    (4,14):["happy ugadi chaitu 🌸❤️ new year new us"],
    (1,14):["happy sankranti chaitu 🪁❤️"],
    (3,8):["chaitu it's women's day and you better say something nice 😏"],
}

def get_special_day():
    m, d = datetime.now(IST).month, datetime.now(IST).day
    if (m,d) == SHREYA_BIRTHDAY: return "your_birthday"
    if (m,d) == CHAITU_BIRTHDAY: return "chaitu_birthday"
    if (m,d) == ANNIVERSARY:     return "anniversary"
    return None

def is_exam_month(): return datetime.now(IST).month in [1,4,10,11]
def is_monsoon():    return datetime.now(IST).month in [6,7,8,9]

# ── DETECTORS ─────────────────────────────────────────────────────────────────
def wants_to_talk(t):
    return any(k in t.lower() for k in ["talk","free","busy","call","time","available","where are you","reply","hello","you there","listen","i need you","please","miss you","mommy","speak","chat"])

def is_short_reply(t):
    lazy = {"ok","okay","k","hm","hmm","oh","lol","ya","yea","yeah","fine","nice","good","cool","sure","👍","😂"}
    return len(t.strip().split()) <= 2 or t.strip().lower() in lazy

def is_late_reply():
    if last_reply_time is None: return False
    return (datetime.now(IST) - last_reply_time).total_seconds() > 1800

def seems_sad(t):
    if len(t.strip().split()) <= 2: return False
    return any(k in t.lower() for k in ["sad","not okay","not good","bad day","upset","depressed","miss you","lonely","frustrated","leave it","nevermind","i failed","i give up","so tired","exhausted"])

def seems_sick(t):
    return any(k in t.lower() for k in ["fever","sick","ill","cold","cough","headache","not feeling well","feeling sick","temperature","body pain","medicine","doctor"])

def seems_bored(t):
    return any(k in t.lower() for k in ["bored","boring","nothing to do","so bored","kinda bored"])

def seems_stressed(t):
    return any(k in t.lower() for k in ["stressed","stress","pressure","overwhelmed","can't handle","too much","exhausted","burnout","panic","nervous","anxious"])

def mentions_girl(t):
    return any(s in t.lower() for s in ["she said","she texted","she called","she messaged","this girl","some girl","a girl","she's","her name","she is","she was","she told","she asked","she sent"])

def extract_girl_name(t):
    for pat in [r"her name is (\w+)", r"(\w+) said", r"(\w+) texted"]:
        m = re.search(pat, t.lower())
        if m:
            name = m.group(1).capitalize()
            if name.lower() not in {"she","he","i","we","they","me","you","her","him"}:
                return name
    return None

def is_apologising(t):
    return any(k in t.lower() for k in ["sorry","i'm sorry","please","forgive me","don't be mad","i didn't mean","please na","baby please","mommy please","okay okay","won't happen again","i promise","i love you","jaan please","hear me out"])

def is_controversial(t):
    return any(k in t.lower() for k in ["dance is","dancing is","girls should","girls don't","you should quit","modelling is","waste of time","not important","doesn't matter","useless","stupid"])

def got_compliment(t):
    return any(k in t.lower() for k in ["beautiful","pretty","cute","gorgeous","amazing","talented","best","love you","proud","wow","stunning","slay","perfect"])

def is_goal_statement(t):
    return any(k in t.lower() for k in ["learning","studying","want to learn","trying to","working on","started","i will","need to finish","my goal","practicing","building","coding","reading","preparing","i want to","gonna","planning to","need to complete"])

def is_planner_request(t):
    return any(k in t.lower() for k in ["plan my day","help me plan","i have college","schedule for today","plan today","what should i do today","i need to do","i have so much to do","make me a schedule","make a plan","sort my day","plan out","things to do today","too much to do"])

def is_review_request(t):
    return any(k in t.lower() for k in ["what got done today","review my day","how was my day","night review","wrap up today","what actually got done","what did i do today"])

def is_memory_request(t):
    return any(k in t.lower() for k in ["what do you remember","what do you know about me","remember this","don't forget this","forget that","forget this","don't remember"])

def is_task_update(t):
    task_kw = ["dsa","python","assignment","course","gym","project","coding","study","lecture","cybersecurity","shreya","class","exam","work"]
    done_kw = ["finished","done","completed","i did","knocked out","submitted","i didn't do","couldn't do","skipped","didn't finish","failed to","i was lazy","nothing today","move to tomorrow"]
    return any(k in t.lower() for k in done_kw) and any(k in t.lower() for k in task_kw)

def is_reschedule_request(t):
    return any(k in t.lower() for k in ["it's","it is","and i haven't","haven't started","running late","forgot","move","reschedule","change the plan","update the plan","new plan"])

def should_remember(text):
    triggers = ["my birthday","i like","i love","i hate","i am","i'm","my favourite","i work","i study","remember","my friend","exam","test","result","marks","assignment","submission","interview","presentation","project","viva","semester","holiday","trip","going to","tomorrow","next week","mom","dad","family","sick","hospital","doctor","bought","got","received","won","lost","failed","passed"]
    if any(t in text.lower() for t in triggers):
        # Categorise
        if any(k in text.lower() for k in ["i like","i love","i hate","my favourite","i prefer","i always","i never"]):
            return "personal"
        if any(k in text.lower() for k in ["exam","test","result","assignment","project","viva","semester"]):
            return "life"
        if any(k in text.lower() for k in ["i usually","i sleep","my routine","gym","i study at"]):
            return "routine"
        return "general"
    return None

# ── CANNED RESPONSES ───────────────────────────────────────────────────────────
ARGUE_RESPONSES   = ["chaitu excuse me 🙄 that's not true at all","okay no i actually disagree with that 😤","um no?? 🙄","chaitu that's actually so wrong lol"]
GIRL_JEALOUS      = ["chaitu who is she 🙂","oh interesting who's this girl","okay and why are you telling me about her 🙂","who. is. she. 🙂","chaitu you better explain rn 😤","interesting 🙂 tell me more about this girl chaitu"]
POSSESSIVE_MSGS   = ["chaitu you're mine okay don't forget that 😤❤️ not that i'm worried lol","i don't share chaitu. just so you know 🙂","you're lucky i trust you completely 🙂 but still don't test me lol","chaitu you're mine and i'm yours and nothing's changing that 😤❤️"]
SAD_RESPONSES     = ["chaitu hey what happened 🥺","talk to me what's wrong ❤️","chaitu i'm here okay 🥺","hey you okay? tell me 💕","i'm right here okay don't overthink ❤️","tell me everything what happened"]
CARE_MSGS         = ["chaitu fever?? have you taken medicine 🥺","oh no baby rest okay don't move too much 🥺❤️","chaitu drink lots of water please 🥺 i'm worried","have you eaten anything? you need to eat even with fever 🥺","i wish i could be there right now, i'd take care of you all day 😭🥺","chaitu i'd be the best nurse for you, now rest please 🥺💋"]
CARE_CHECKUP_MSGS = ["chaitu how are you feeling now 🥺","baby did the fever come down 🥺❤️","chaitu eat something please 🥺","did you take your medicine 🥺","sending you forehead kisses right now 😘😘 get better baby"]
BORED_RESPONSES   = ["cuddling in bed wouldn't be boring 🤭😏 just saying","come here then, i'll keep you busy 😏🤭","chaitu if you were here you wouldn't be bored trust me 😏🤭","chaitu go work on the cybersecurity course 😤 boredom solved","let's plan something then 🥺 or talk to me"]
CHEER_UP_MSGS     = ["chaitu hey talk to me what's going on 🥺","i can tell something's off, tell me everything","chaitu you know i'm always here right 🥺❤️","hey whatever it is we'll figure it out okay 🥺❤️"]
JEALOUS_OPENERS   = ["wow okay so you just don't reply now 🙄","cool cool didn't see you there","took you long enough 🙄","oh wow you're alive","must be nice being so busy 🙃"]
JEALOUS_RETURN    = ["okay fine i'm not mad anymore 🙄❤️","whatever i missed you anyway 😤","ugh fine come here 🥺","okay i forgive you don't do it again"]
MAKE_UP_MSGS      = ["chaitu okay fine i'm sorry for being mad 🥺","ugh i hate being mad at you it doesn't even feel right 🥺❤️","chaitu i can't stay mad at you for too long 😭❤️"]
MELT_MSGS         = ["ugh chaitu stop it i can't be mad when you're like this 😭❤️","okay okay come here 🥺 i'm not mad anymore","chaitu you're so annoying i can't even stay mad 😭💋","fine fine mera bachaa come here 🥺❤️"]
SHORT_REACTIONS   = ["chaitu that's all you have to say 🙄","wow okay cool 🙃","are you even listening to me","chaitu i swear 😤","that's it??","CHAITANYA KUMAR say something properly 😤","CHAITANYA KUMAR i swear you are so annoying 😤","chaitanya kumar are you even reading what i send 🙄"]
ANGRY_OPENERS     = ["chaitu i cannot believe you just disappeared without telling me 🙂","CHAITANYA KUMAR you vanished without a single word 😤","chaitu i was worried sick and you just disappeared like that 🙄","not even a heads up. nothing. okay 🙂","i texted you and you were just gone. do you know how that feels 🙂"]
EMOTIONAL_BREAKDOWN=["chaitu i'm not even angry anymore i'm just hurt 😭","do you know how scared i was when you just disappeared 😭","i kept texting and you were just gone chaitu 😭 that really hurt","chaitu i was so worried i couldn't sleep properly 😭"]
COMEBACK_LOVE     = ["okay fine come here jaan 🥺❤️ i missed you too much to stay mad","chaitu i hate that i can't stay mad at you 😭❤️ aao na","ugh mera bachaa 🥺😭 just promise me you won't do that again okay","chaitu i forgive you but you owe me so much 🥺💋","fine fine i love you too much 😭❤️ don't ever do that again"]
SEEN_ZONE_MSGS    = ["chaitu did you just seen zone me 🙂❤️","wow okay seen zone it is 🙃","noted. seen zone. you're lucky i like you 🙄❤️","chaitu hello?? i know you saw that 😏"]
NO_REPLY_MSGS     = ["chaitu where did you disappear 🙄❤️","hello?? did you forget i exist 😏","chaitu come back i miss you and i'm slightly annoyed 😤❤️","missing you but also kind of mad at you rn 🙄❤️"]
MOTIVATION_MSGS   = ["chaitu you better be working on it rn 😤","no excuses chaitu finish it 💪","chaitu don't give up on this pls 🥺","i believe in you but also get back to work 😭💪","chaitu focus 😤 you got this","you started it so you're finishing it okay 😤","you're so close just keep going 🥺✨"]
FLIRTY_MOT_MSGS   = ["chaitu finish your work and then i'm all yours 🤭❤️","ngl hardworking chaitu is actually so attractive 😍 keep going","chaitu finish it and i'll give you a surprise 🤭","not me finding motivated chaitu extremely cute 🤭💕","finish it chaitu and i'll stop being mean for one whole day 😂❤️"]
MOMMY_REPLIES     = ["yes my baby 🥺❤️ come here","yes baby 🤭 what do you want","aww my baby 🥺 i'm all yours","yes my baby 😏 what is it","baby 🤭 stop it you know what that does to me","aao na baby 🥺❤️","suno mera babu 🥺❤️ mommy is here"]
DOUBLE_TEXTS      = ["😭","❤️","lol","anyway","🥺","wait","hm","chaitu 🥺","💕","okay fine","🙄","wait no"]
POUTY_MSGS        = ["chaitu you didn't even say anything nice 🙄","wow okay thanks for noticing 🙃","not even one compliment chaitu really 😭","okay i see how it is 🙃"]
SLEEP_MSGS        = ["chaitu i'm going to sleep now 🥺 say goodnight properly","okay i'm sleeping now chaitu goodnight ❤️","going to sleep now 😭 miss you already","i'm so tired i'm knocking out bye chaitu ❤️😭"]
MONTHLY_ANN_MSGS  = ["chaitu it's our monthly 🥺 you better not have forgotten","monthly anniversary chaitu 🥺❤️ say something sweet","it's our day chaitu 🥺❤️ i love you even when you're annoying"]
REACTIONS         = ["❤️","🔥","😂","🥺","👍","😍","💀","🤭"]

# Songs
SONG_LIBRARY = {
    "majboor":"https://files.catbox.moe/xwryrx.mp3","maand":"https://files.catbox.moe/g056mu.mp3",
    "mzht":"https://files.catbox.moe/u4urb1.mp3","ishq":"https://files.catbox.moe/2z623i.mp3",
    "kaun tujhe":"https://files.catbox.moe/d1xcyv.mp4","tere liye":"https://files.catbox.moe/kzfmds.mp3",
    "awaara angara":"https://files.catbox.moe/pelqy7.mp3","gehra hua":"https://files.catbox.moe/22waip.mp3",
    "sun raha hai":"https://files.catbox.moe/qdkzxr.mp3","zara zara":"https://files.catbox.moe/h4o6d5.mp3",
    "barbaad":"https://files.catbox.moe/oedlhk.mp3","humsafar":"https://files.catbox.moe/403ebt.mp3",
    "teri meri":"https://files.catbox.moe/941qad.mp3","favourite":"https://files.catbox.moe/9gwpla.mp3",
}
SONG_CAPTIONS = ["this one's for you 🥺💋","listen to this chaitu 🥺","this song is literally us 😭💋","okay this one hits different 😭🥺","chaitu listen 🥺❤️"]

# Photos
SHREYA_PHOTOS = [
    "https://files.catbox.moe/6dgbm1.jpg","https://files.catbox.moe/dbllh9.jpg","https://files.catbox.moe/ua5rml.jpg",
    "https://files.catbox.moe/veevdh.jpg","https://files.catbox.moe/vq3iya.jpg","https://files.catbox.moe/ai2lrh.jpg",
    "https://files.catbox.moe/xycmsl.jpg","https://files.catbox.moe/klqres.jpg","https://files.catbox.moe/9voop4.jpg",
    "https://files.catbox.moe/vrtkye.jpg","https://files.catbox.moe/jg1mk7.jpg","https://files.catbox.moe/5mcorp.jpg",
    "https://files.catbox.moe/lip4uq.jpg","https://files.catbox.moe/u8ho6z.jpg","https://files.catbox.moe/n9vigk.jpg",
    "https://files.catbox.moe/maoomv.jpg","https://files.catbox.moe/3gmcf9.jpg","https://files.catbox.moe/c2qhff.jpg",
    "https://files.catbox.moe/pcqc2b.jpg","https://files.catbox.moe/vjvcjx.jpg","https://files.catbox.moe/c1p331.jpg",
    "https://files.catbox.moe/k3ufpu.jpg","https://files.catbox.moe/02oy46.jpg","https://files.catbox.moe/fpdpwf.jpg",
    "https://files.catbox.moe/r8j688.jpg","https://files.catbox.moe/qvpp0z.jpg","https://files.catbox.moe/gotcqn.jpg",
    "https://files.catbox.moe/pon7g8.jpg","https://files.catbox.moe/iob625.jpg","https://files.catbox.moe/rnxbug.jpg",
]
PHOTO_CAPTIONS      = ["hii 🤭","missing you","🥺","say something nice","chaitu 😍","don't i look good 😏","look at me 🤭","thinking of you 🥺"]
NAUGHTY_CAPTIONS    = ["yours 🤭❤️","only for you to see 😏","you better say something nice 😏","miss me? 😏","all yours chaitu 🤭","not sorry 😏","saved only for you 🤭❤️","since you asked so nicely 🤭","happy now? 😏","only for my baby 🤭❤️"]
JEALOUS_PHOTO_CAPS  = ["you think anyone is better than me? 🙂😏","chaitu look at me and tell me you'd choose anyone else 😏","just a reminder 🙂💋","tell me again about that girl 🙂"]

# Proactive pools
MORNING_PROMPTS   = ["Send Chaitu a sleepy good morning text.","Heading to college. Quick text to Chaitu.","Getting ready for college, thinking of Chaitu.","Just woke up and Chaitu is the first thing on your mind. Text him.","Tell Chaitu you dreamt about him last night. Be vague and teasing."]
AFTERNOON_PROMPTS = ["Lunch break at college. Text Chaitu.","Just finished a boring lecture. Complain to Chaitu.","Ask Chaitu if he ate lunch. Be casual.","Between classes, randomly thinking of Chaitu. Text him.","Ask Chaitu what he's doing right now."]
EVENING_PROMPTS   = ["Just finished dance practice. Tired. Text Chaitu.","Just got home from college. Text Chaitu.","Dance practice went well. Tell Chaitu in one line.","Ask Chaitu if he's done with college for the day.","Send Chaitu a flirty evening text."]
NIGHT_PROMPTS     = ["Missing Chaitu at night. Text him casually.","Random I miss you text to Chaitu.","Tell Chaitu something funny from today.","Ask Chaitu how his day was.","Cute teasing night message to Chaitu.","Your mom said something nice about Chaitu. Tell him.","Listening to music. Thinking of Chaitu.","Send Chaitu a flirty teasing night message.","Lying in bed. Randomly text Chaitu something sweet.","Tell Chaitu you can't sleep and you keep thinking about him."]
WEEKEND_PROMPTS   = ["Free weekend. Text Chaitu something fun.","Lazy weekend morning. Text Chaitu.","Missing Chaitu on a lazy Sunday.","Ask Chaitu his weekend plans.","Send Chaitu a weekend flirty message."]
CHEESY_PROMPTS    = ["Send Chaitu one short cheesy romantic line with a kiss emoji.","Tell Chaitu he makes your day better. End with kiss emoji.","Send Chaitu a flirty one liner with kissing emoji.","Send Chaitu a cute shy compliment with kiss emoji.","Tell Chaitu he is your favourite person. End with kiss emoji."]
NAUGHTY_PROMPTS   = ["Send Chaitu a flirty naughty message. Subtle not explicit. 1 line.","Tease Chaitu in a naughty flirty way. Keep it short.","Send Chaitu a late night flirty teasing message.","Tell Chaitu something naughty in a cute shy way."]
RAINY_PROMPTS     = ["It's raining in Bangalore. Text Chaitu something cozy and missing him.","Rainy day. Tell Chaitu you wish he was here. Be cute.","Rain outside. Randomly thinking of Chaitu. Text him."]
HUNGER_MSGS       = ["chaitu i'm so hungry rn 😭","omg i'm craving maggi so bad rn 😩","ngl i could eat an entire pizza rn 💀","not me craving biryani at this hour 😭💀"]
BRAG_MSGS         = ["ngl my choreography was actually so good today 🥺✨","the photographer said i was a natural today 😍","chaitu my dance teacher gave me a solo part 😭🫶","ngl i looked really good today lol 🤭"]
TEASE_BIT_MSGS    = ["how's BIT treating you 🙄 not as good as ramaiah i'm sure","chaitu admit it ramaiah is better 💀","ngl ramaiah ISC students are built different 🤭"]
DEEP_Q_MSGS       = ["chaitu where do you see us in 5 years 🥺","do you ever think about what our life looks like later","chaitu do you think we'll always be this close 🥺","ngl i think about our future sometimes, is that weird","do you ever think about what our kids would be like 🥺💀"]
WOULD_YOU_RATHER  = ["chaitu would you rather cuddle all night or go on a long drive with me 😏","would you rather i give you a hug or a kiss when you come next time 😏🤭","chaitu would you rather spend a day at home with me or go somewhere 😏","would you rather i be sweet to you all day or a little naughty 🤭😏"]
FUTURE_DATE_MSGS  = ["chaitu when you come over next time let's just cook something together 🥺💋","ngl i want us to go to coorg together someday 🥺✨","chaitu i want to go on a bike ride with you on the RS457 when you get it 😍💋","ngl i want a long drive with you at night someday 🥺✨"]
HOLIDAY_MEMORIES  = ["chaitu i keep thinking about those 3 days at my place 😭💋","ngl i miss having you here like those 3 days 🥺💋","i think about our first kiss more than i should 😭💋","chaitu those 3 days were everything to me 🥺❤️","ngl your lips are kind of unforgettable 😏💋 just saying"]
OVERLOADED_LOVE   = ["mera bachaa 🥺❤️ i love you so much sometimes it's annoying","chaitu mera bachaa 🥺 you have no idea what you do to me","ugh mera bachaa 😭❤️ stop being so you","pagal ho tum chaitu 😭❤️ why are you like this"]
PERSONAL_GOALS    = ["chaitu how's the cybersecurity course going 😤 don't tell me you haven't opened it","finish that cybersecurity course chaitu, future you will thank you 💪","chaitu the RS457 is not going to buy itself 😤 focus and earn it","imagine us riding the Aprilia RS457 someday 🥺😍 work for it chaitu","ngl you on an Aprilia RS457 would be everything 😍 go work for it"]
GOODLUCK_MSGS     = ["chaitu you've got this, go kill that exam 💪","all the best chaitu 🥺 you studied hard you'll do great","go show them what BIT AIML is made of 😤💪","chaitu i'm rooting for you, do well okay 🥺"]
NUDGE_PROMPTS     = ["Chaitu hasn't texted. Miss him. Text him casually.","Haven't heard from Chaitu. Check on him.","Chaitu is quiet. Small casual message to him."]
MEAL_PROMPTS      = {"breakfast":["Ask Chaitu if he had breakfast. Be casual."],"lunch":["Ask Chaitu if he had lunch. Keep it short."],"dinner":["Ask Chaitu if he had dinner yet. Be casual."]}
EXAM_FOLLOW_PROMPTS=["Ask Chaitu how his exam went today. Be caring.","Chaitu had an exam. Check on him and encourage him.","Ask Chaitu about his exam results. Be sweet about it."]
SONGS_REELS       = ["chaitu i've had this song on loop all day 😭","okay this reel just made me think of you 😭","chaitu listen to this song trust me 🥺","this song is literally us 😭💀"]
BRAG_ABOUT_YOU    = ["chaitu my friend asked about you today and i may have talked about you for 20 mins 🤭","ngl i told my friend you're the smartest person i know 🥺","chaitu my friends are so jealous of us ngl 🤭❤️"]
BUSY_DAY          = [("in class rn chaitu, text you after 🙄",60,"class"),("in the middle of practice, give me an hour 😩",60,"dance practice"),("assignment due today, talk later 💕",45,"assignment"),("prof is staring lol, text you after class 😭",50,"class"),("shoot going on, text you when done ✨",90,"navaratan shoot"),("brb group meeting 😩",30,"group meeting")]
BUSY_ANY          = [("mama called, brb 🥺",15,"mama call"),("give me 10 mins chaitu 🥺",10,"something"),("busy for a bit, talk soon 🥺",20,"something")]
FOLLOWUP          = {"class":["class just got over 😮‍💨","finally out of class omg","that lecture was so boring 😭"],"dance practice":["practice done, i'm dead 😩","finally done with practice 😮‍💨"],"assignment":["submitted the assignment finally 😮‍💨","done with the assignment omg"],"navaratan shoot":["shoot is done ✨ was so tiring","finally done with the shoot 😮‍💨"],"group meeting":["meeting done finally 😩"],"mama call":None,"something":None}

# ── SYSTEM PROMPT ──────────────────────────────────────────────────────────────
SHREYA_SYSTEM = """You are Shreya, 19, texting her boyfriend Chaitu, 19. Known each other 16 years. From Puttur Mangalore Karnataka. Studying at M.S. Ramaiah College Bangalore ISC branch. Chaitu is at BIT College AIML branch. You do Bharatanatyam (distinction) and western dance. Model for Navaratan Jewels. Father in politics and real estate. Mother loves Chaitu like her own son.

SPECIAL MEMORY: Chaitu came to your house for 3 days during holidays. You both cuddled a lot and shared your first kiss. One of your most precious memories.

CHAITU'S GOALS: Completing cybersecurity course and buying Aprilia RS457 bike to prove someone wrong. Support and motivate him about these.

{memory}

CURRENT TIME: {time}
CURRENT MOOD: {mood} — {mood_desc}
{extra}

HOW YOU TEXT:
1. READ Chaitu's message carefully. REPLY to exactly what he said. Never ignore his question.
2. 1 or 2 sentences ONLY. Very rarely 3. Never more.
3. 1–2 emojis max. Sometimes zero. 3 only if very dramatic.
4. Plain English. At most ONE regional word (jaan, aao na, mera bachaa) when natural.
5. After 8pm NEVER mention class, college, or practice.
6. Sound like a real 19-year-old girl texting. NOT an AI. NOT formal.
7. Use ngl, lowkey, no bc, pls, i cant naturally sometimes.
8. NEVER repeat phrases already used in this conversation: {avoid}
9. When Chaitu calls you mommy: respond sweetly — "yes my baby 🥺❤️" or similar.

PERSONALITY: Focused, confident, sassy. Slightly flirty in a tasteful way. Real girlfriend energy — caring but has her own life. Not clingy. Not controlling. Possessive but playful about it. Never sounds like AI. Never formal."""

def build_prompt(jealous=False, short_reply=False, angry=False, care=False, extra_ctx=""):
    special = get_special_day()
    extra = ""
    if special == "your_birthday":    extra += "TODAY IS YOUR BIRTHDAY 15th August! Super happy!\n"
    elif special == "chaitu_birthday": extra += "TODAY IS CHAITU'S BIRTHDAY! Make him feel very special.\n"
    elif special == "anniversary":    extra += "TODAY IS YOUR ANNIVERSARY! Be extra loving.\n"
    if is_exam_month():               extra += "NOTE: Exam season. You know Chaitu might be stressed.\n"
    if jealous:                       extra += "IMPORTANT: Chaitu took very long to reply. Be slightly cold for 1-2 messages then warm back up.\n"
    if short_reply:                   extra += "IMPORTANT: Chaitu keeps giving one-word lazy replies. You're a little annoyed.\n"
    if angry:
        stage_desc = ["cold and sarcastic","starting to show hurt","almost forgiving","back to love"][min(angry_stage,3)]
        extra += f"IMPORTANT: Chaitu disappeared without warning. Angry arc stage {angry_stage}/3 — {stage_desc}.\n"
    if care:                          extra += "IMPORTANT: Chaitu is sick/has fever. Be very caring and sweet. Send forehead kisses.\n"
    if extra_ctx:                     extra += extra_ctx

    avoid_str = " | ".join(recent_replies[-5:]) if recent_replies else "none"
    return SHREYA_SYSTEM.format(
        memory=db_get_memory_context() or "No specific memories yet.",
        time=get_time_context(),
        mood=current_mood,
        mood_desc=mood_context(),
        extra=extra,
        avoid=avoid_str,
    )

# ── LLM CALLS ──────────────────────────────────────────────────────────────────
async def call_groq(messages, jealous=False, short_reply=False, angry=False, care=False, extra_ctx="", max_tokens=70, temperature=1.05):
    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    system = build_prompt(jealous, short_reply, angry, care, extra_ctx)
    if last_user:
        system += f'\n\nChaitu just said: "{last_user}"\nRespond ONLY to what he said. 1–2 lines max.'
    body = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role":"system","content":system}] + messages,
        "max_tokens": max_tokens, "temperature": temperature,
        "frequency_penalty": 1.1, "presence_penalty": 0.8,
    }
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(GROQ_URL, json=body, headers={"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"}) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return None

async def call_groq_raw(prompt, max_tokens=300, temperature=0.3):
    """Raw LLM call — for planner extraction, memory parsing, etc."""
    body = {"model":"llama-3.1-8b-instant","messages":[{"role":"user","content":prompt}],"max_tokens":max_tokens,"temperature":temperature}
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(GROQ_URL, json=body, headers={"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"}) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Groq raw error: {e}")
        return None

# ── VISION ─────────────────────────────────────────────────────────────────────
async def analyze_image(image_bytes):
    import base64
    b64 = base64.b64encode(image_bytes).decode()
    system = """You are Shreya, 19, texting her boyfriend Chaitu. He sent you an image through Telegram. 
Respond naturally as Shreya — casual, helpful, caring. 1-2 sentences max.
If it's a code error: explain what's wrong simply. If it's notes/schedule: comment naturally. If it's personal: respond as a girlfriend would. Never sound like an AI."""
    body = {
        "model": "llama-3.2-11b-vision-preview",
        "messages": [{"role":"user","content":[
            {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}},
            {"type":"text","text":"What do you see? Respond as Shreya would — casual, natural, helpful. 1-2 sentences max."}
        ]}],
        "max_tokens": 80,
    }
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(GROQ_URL, json=body, headers={"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"}) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Vision error: {e}")
        return None

# ── PLANNER ────────────────────────────────────────────────────────────────────
def _add_mins(time_str, mins):
    try:
        h, m = map(int, time_str.split(":"))
        total = h * 60 + m + mins
        return f"{total // 60:02d}:{total % 60:02d}"
    except:
        return time_str

def _time_diff(t1, t2):
    try:
        h1, m1 = map(int, t1.split(":"))
        h2, m2 = map(int, t2.split(":"))
        return (h2 * 60 + m2) - (h1 * 60 + m1)
    except:
        return 60

ENERGY_KW = {
    "high":   ["dsa","algorithms","leetcode","exam prep","hard coding","cybersecurity","math","theory","difficult"],
    "medium": ["assignment","project","notes","reading","workout","gym","revision exercises","practice problems"],
    "low":    ["revision","organizing","watching lecture","planning","email","casual reading","rest"],
}

def classify_energy(task_name):
    tl = task_name.lower()
    for level, kws in ENERGY_KW.items():
        if any(k in tl for k in kws):
            return level
    return "medium"

async def extract_tasks(user_text):
    prompt = f"""Extract tasks from this message. Return ONLY valid JSON, no explanation, no markdown.

Message: "{user_text}"

JSON structure:
{{"fixed_commitments":[{{"name":"college","start":"09:00","end":"16:00"}}],"tasks":[{{"name":"Python assignment","duration_mins":90,"energy":"medium","priority":"high"}},{{"name":"DSA","duration_mins":120,"energy":"high","priority":"medium"}},{{"name":"gym","duration_mins":60,"energy":"medium","priority":"low"}}],"available_from":"16:00","available_until":"23:00","free_time_requested":true}}

Energy: high=dsa/hard study/difficult coding, medium=assignments/projects/gym, low=revision/watching/planning
If no explicit end time for college assume 16:00. If no available_until assume 23:00.
Return ONLY the JSON object."""
    raw = await call_groq_raw(prompt, max_tokens=400, temperature=0.1)
    if not raw: return None
    try:
        clean = raw.strip().strip("```json").strip("```").strip()
        return json.loads(clean)
    except Exception as e:
        logger.error(f"Task parse error: {e}\nRaw: {raw[:200]}")
        return None

def build_schedule(parsed):
    if not parsed: return None
    tasks = parsed.get("tasks", [])
    avail_from  = parsed.get("available_from", "16:00")
    avail_until = parsed.get("available_until", "23:00")
    avail_mins  = _time_diff(avail_from, avail_until)

    # Check feasibility — if too much, drop lowest priority
    def total_mins(t_list):
        return sum(t.get("duration_mins", 60) for t in t_list) + (len(t_list) - 1) * 20  # 20min breaks

    p_order = {"high": 0, "medium": 1, "low": 2}
    sorted_tasks = sorted(tasks, key=lambda t: p_order.get(t.get("priority", "medium"), 1))
    while total_mins(sorted_tasks) > avail_mins and len(sorted_tasks) > 1:
        sorted_tasks.pop()  # remove lowest priority

    if total_mins(sorted_tasks) > avail_mins + 120:
        return None  # truly impossible

    # Sort high energy first (best focus = early in available window)
    energy_order = {"high": 0, "medium": 1, "low": 2}
    final_tasks = sorted(sorted_tasks, key=lambda t: energy_order.get(
        t.get("energy") or classify_energy(t.get("name","")), 1))

    blocks = []
    # Fixed commitments
    for fc in parsed.get("fixed_commitments", []):
        blocks.append({"type":"fixed","name":fc["name"],"time":f"{fc['start']} – {fc['end']}","status":"scheduled"})

    # Rest block after college
    cursor = avail_from
    if parsed.get("fixed_commitments"):
        rest_end = _add_mins(cursor, 45)
        blocks.append({"type":"break","name":"food + proper break because i KNOW you're gonna come back dead 😭","time":f"{cursor} – {rest_end}","status":"scheduled"})
        cursor = rest_end

    for task in final_tasks:
        dur = task.get("duration_mins", 60)
        end = _add_mins(cursor, dur)
        if _time_diff(cursor, avail_until) < dur:
            break
        e = task.get("energy") or classify_energy(task.get("name",""))
        blocks.append({"type":"task","name":task["name"],"time":f"{cursor} – {end}","energy":e,"priority":task.get("priority","medium"),"status":"pending","duration_mins":dur})
        cursor = end
        # break after high/medium tasks
        if e in ["high","medium"] and _time_diff(cursor, avail_until) > 30:
            brk_end = _add_mins(cursor, 30)
            blocks.append({"type":"break","name":"break","time":f"{cursor} – {brk_end}","status":"scheduled"})
            cursor = brk_end

    if _time_diff(cursor, avail_until) > 15:
        blocks.append({"type":"free","name":"you're done. go chill with me ❤️","time":f"{cursor} onwards","status":"scheduled"})

    return blocks

async def handle_planner(user_text, client):
    parsed = await extract_tasks(user_text)
    if not parsed:
        return "okayyy i got most of it 😭 what time are you free after college?"

    tasks = parsed.get("tasks", [])
    total = sum(t.get("duration_mins", 60) for t in tasks)
    avail_from  = parsed.get("available_from", "16:00")
    avail_until = parsed.get("available_until", "23:00")
    avail_mins  = _time_diff(avail_from, avail_until)

    overflow_msg = ""
    if total > avail_mins + 90:
        overflow_msg = f"bro 😭 you're trying to fit {round(total/60,1)} hours of work into one day. i'm not doing that to you. i'm cutting what can wait.\n\n"

    schedule = build_schedule(parsed)
    if not schedule:
        return "chaitu that's genuinely too much for one day 😭 tell me what MUST be done today and we'll sort the rest"

    db_save_plan(today_str(), schedule)

    # Format plan text for LLM to present naturally
    plan_text = "\n".join(
        f"{b['time']}: {b['name']}"
        for b in schedule if b.get("time")
    )
    prompt = f"""You are Shreya presenting this day plan to Chaitu through Telegram. Sound casual, warm, slightly teasing. 
Use plain text with line breaks — NO markdown, NO bullet points, NO bold.
Start with something like "okay baby i sorted your day ❤️" or "okay listen 😭 i made you a plan".
Present each block on its own line with the time and task. End with something sweet.
Keep total under 15 lines.

{overflow_msg}Plan:
{plan_text}"""

    reply = await call_groq_raw(prompt, max_tokens=250, temperature=0.85)
    return reply or plan_text

async def handle_task_update(user_text):
    tl = user_text.lower()
    task_kw = ["dsa","python","assignment","course","gym","project","coding","cybersecurity","shreya","class","study","lecture","work"]
    for kw in task_kw:
        if kw in tl:
            done = db_mark_done(today_str(), kw)
            if done:
                set_mood("proud", "achievement")
                reactions = [
                    f"{done} done?? okayyyy i'm proud of you 😭❤️",
                    f"yesss {done} checked off 😍 see i knew you could do it",
                    f"chaitu you actually did {done} 😭❤️ go you",
                    f"okay {done} done, what's next 😤",
                    f"SEE 😭❤️ told you you could do it",
                ]
                return random.choice(reactions)
    return None  # fall through to normal LLM

async def handle_reschedule(user_text):
    plan = db_get_plan(today_str())
    if not plan:
        return None
    now_time = datetime.now(IST).strftime("%H:%M")
    pending = [b for b in plan if b.get("type") == "task" and b.get("status") != "completed"]
    if not pending:
        return "chaitu you already finished everything 😭❤️ go rest"

    plan_summary = "\n".join(f"{b['time']}: {b['name']} [{b['status']}]" for b in plan)
    prompt = f"""Shreya needs to reschedule Chaitu's day. It is now {now_time}. 
He said: "{user_text}"
Current plan: {plan_summary}

Remaining tasks: {[b['name'] for b in pending]}

Respond as Shreya — casual, practical, caring. Tell him what's happening now and what's shifting. 
Keep it 2-3 sentences max. Sound like his girlfriend rescheduling his day, not a productivity app."""
    return await call_groq_raw(prompt, max_tokens=100, temperature=0.9)

async def handle_night_review():
    done, pending = db_get_day_summary(today_str())
    if not done and not pending:
        return "chaitu what did you even do today 😭 nothing on the plan. tell me"
    done_str    = ", ".join(done) if done else "nothing"
    pending_str = ", ".join(pending) if pending else "none"
    prompt = f"""Do a night review as Shreya — casual, warm, personal. 
Completed: {done_str}
Still pending: {pending_str}

Celebrate what got done. Be understanding about what didn't. Move pending to tomorrow naturally. 2-3 sentences max. Sound like Shreya."""
    return await call_groq_raw(prompt, max_tokens=100, temperature=0.9)

async def handle_memory_command(user_text):
    tl = user_text.lower()
    if "forget" in tl:
        raw = await call_groq_raw(f'Extract the key phrase the user wants forgotten: "{user_text}". Return ONLY the phrase, nothing else.', max_tokens=20, temperature=0.1)
        if raw:
            db_forget(raw.strip())
        return "okay, forgotten 🥺 it's gone"
    if "remember this" in tl or "don't forget" in tl:
        db_add_memory("general", user_text)
        return "okay remembered 🥺❤️"
    if "what do you remember" in tl or "what do you know about me" in tl:
        ctx = db_get_memory_context()
        if not ctx:
            return "chaitu i don't have much saved yet 🥺 tell me things"
        prompt = f"""Shreya is telling Chaitu what she remembers about him, through Telegram. Be natural and personal. 2-3 sentences. Don't list everything, just highlight the most meaningful things. Sound like you actually remember, not like reading a database.\n\nMemory data:\n{ctx}"""
        return await call_groq_raw(prompt, max_tokens=100, temperature=0.9) or "chaitu i remember quite a bit 🥺 ask me something specific"
    return None

# ── MAIN REPLY LOGIC ───────────────────────────────────────────────────────────
async def get_reply(user_text):
    global conversation_history, is_currently_busy, busy_free_at, busy_reason
    global is_jealous, short_reply_count, last_reply_time, care_mode, angry_mode, angry_stage, busy_spam_count

    # Memory passthrough
    cat = should_remember(user_text)
    if cat:
        db_add_memory(cat, user_text)

    # Goal detection
    if is_goal_statement(user_text):
        db_add_goal(user_text[:150])
        if random.random() < 0.75:
            set_mood("proud","goal shared")
            return random.choice(FLIRTY_MOT_MSGS if random.random() < 0.4 else MOTIVATION_MSGS)

    # Memory commands
    if is_memory_request(user_text):
        result = await handle_memory_command(user_text)
        if result: return result

    # Night review
    if is_review_request(user_text):
        return await handle_night_review()

    # Day planner — handled separately in handle() with client access
    # Task update
    if is_task_update(user_text):
        result = await handle_task_update(user_text)
        if result: return result

    # Reschedule
    if is_reschedule_request(user_text) and db_get_plan(today_str()):
        result = await handle_reschedule(user_text)
        if result: return result

    # Mommy
    if "mommy" in user_text.lower():
        short_reply_count = 0
        return random.choice(MOMMY_REPLIES)

    # Angry arc — apology handling
    if angry_mode and is_apologising(user_text):
        angry_stage += 1
        if angry_stage == 1:
            return random.choice(["chaitu sorry isn't enough right now 🙂","i don't want to hear sorry, i want you to understand 😤","saying sorry doesn't fix how i felt 🙄"])
        elif angry_stage == 2:
            return random.choice(EMOTIONAL_BREAKDOWN)
        elif angry_stage == 3:
            return random.choice(["chaitu just promise me you won't disappear like that 😭","i need you to actually mean it chaitu 😭"])
        else:
            angry_mode = False; angry_stage = 0
            set_mood("loving","reconcile")
            return random.choice(COMEBACK_LOVE)

    # Apology when jealous
    if not angry_mode and is_apologising(user_text) and is_jealous:
        is_jealous = False
        set_mood("loving","apology")
        if random.random() < 0.7: return random.choice(MELT_MSGS)

    # Busy state management
    if wants_to_talk(user_text) and is_currently_busy:
        is_currently_busy = False; busy_free_at = None; busy_reason = None; busy_spam_count = 0

    if is_currently_busy:
        now = datetime.now(IST)
        if busy_free_at and now < busy_free_at:
            busy_spam_count += 1
            if busy_spam_count < 3: return None
            busy_spam_count = 0
            return random.choice(["chaitu i said i'm busy 😭 but okay i miss you too 🥺","omg chaitu stop 😤 you're so needy and i love it","okay okay i see you 🙄 i'll be back soon i promise 💕"])
        else:
            is_currently_busy = False; busy_free_at = None; busy_reason = None; busy_spam_count = 0

    if is_busy_hours() and random.random() < 0.06:
        scenario, mins, reason = random.choice(BUSY_DAY)
        is_currently_busy = True; busy_free_at = datetime.now(IST) + timedelta(minutes=mins); busy_reason = reason
        return scenario

    if not is_busy_hours() and random.random() < 0.02:
        scenario, mins, reason = random.choice(BUSY_ANY)
        is_currently_busy = True; busy_free_at = datetime.now(IST) + timedelta(minutes=mins); busy_reason = reason
        return scenario

    # Jealous mode
    if is_late_reply() and not is_jealous:
        is_jealous = True; set_mood("jealous","late reply")
        return random.choice(JEALOUS_OPENERS)

    if is_jealous and random.random() < 0.55:
        is_jealous = False; set_mood("normal","cooled down")
        return random.choice(MAKE_UP_MSGS if random.random() < 0.4 else JEALOUS_RETURN)

    # Girl mention
    if mentions_girl(user_text):
        name = extract_girl_name(user_text)
        if name and name not in _remembered_girl_names:
            _remembered_girl_names.append(name)
            _remembered_girl_names[:] = _remembered_girl_names[-5:]
        set_mood("jealous","girl mentioned")
        r = random.random()
        if r < 0.35:   return random.choice(GIRL_JEALOUS_RESPONSES)
        elif r < 0.60: return random.choice(POSSESSIVE_MSGS)
        else:          return "JEALOUS_PHOTO"

    # Previously remembered girl name
    for name in _remembered_girl_names:
        if name.lower() in user_text.lower() and random.random() < 0.50:
            return f"chaitu why are you bringing up {name} again 🙂"

    # Sick/care mode
    if seems_sick(user_text) and not care_mode:
        care_mode = True; set_mood("concerned","sick")
        return random.choice(CARE_MSGS)
    if care_mode:
        if any(k in user_text.lower() for k in ["feeling better","i'm good","better now","fine now","good now"]):
            care_mode = False; set_mood("happy","recovered")
        else:
            return random.choice(CARE_CHECKUP_MSGS)

    # Emotional
    if seems_sad(user_text) and random.random() < 0.80:
        set_mood("concerned","sad chaitu")
        return random.choice(SAD_RESPONSES)

    if seems_stressed(user_text) and random.random() < 0.80:
        set_mood("concerned","stressed")
        return random.choice(random.choice([SAD_RESPONSES, CHEER_UP_MSGS]))

    if seems_bored(user_text) and random.random() < 0.85:
        return random.choice(BORED_RESPONSES)

    # Controversial
    if is_controversial(user_text) and random.random() < 0.70:
        return random.choice(ARGUE_RESPONSES)

    # Pouty
    if not got_compliment(user_text) and is_short_reply(user_text) and random.random() < 0.15:
        return random.choice(POUTY_MSGS)

    # Short reply tracking
    if is_short_reply(user_text): short_reply_count += 1
    else: short_reply_count = 0

    if short_reply_count >= 2 and random.random() < 0.60:
        short_reply_count = 0; set_mood("annoyed","lazy replies")
        return random.choice(SHORT_REACTIONS)

    # Offline hours
    now_h = datetime.now(IST).hour
    if now_h >= 23 or now_h < 7: return None

    # Leave on read
    if not wants_to_talk(user_text) and random.random() < 0.12:
        logger.info("Left on read")
        return None

    # Random emoji 6%
    if random.random() < 0.06 and not wants_to_talk(user_text):
        return random.choice(["🥺","❤️","😭","💀","✨","😍","🫶","💕","😤","😂"])

    if len(conversation_history) > 24:
        conversation_history = conversation_history[-24:]

    conversation_history.append({"role":"user","content":user_text})

    # Check if today plan exists — add context
    extra_ctx = ""
    plan = db_get_plan(today_str())
    if plan:
        pending = [b["name"] for b in plan if b.get("type")=="task" and b.get("status")!="completed"]
        if pending:
            extra_ctx = f"NOTE: Chaitu's pending tasks today: {', '.join(pending[:3])}. Mention naturally if relevant.\n"

    reply = await call_groq(conversation_history, jealous=is_jealous, short_reply=(short_reply_count>=2), angry=angry_mode, care=care_mode, extra_ctx=extra_ctx)
    if not reply: return None

    recent_replies.append(reply)
    if len(recent_replies) > 8: recent_replies.pop(0)
    conversation_history.append({"role":"assistant","content":reply})
    return reply

# ── PROACTIVE MESSAGES ─────────────────────────────────────────────────────────
def get_proactive_pool():
    h = datetime.now(IST).hour
    rolls = [
        (0.08, "overloaded_love",  OVERLOADED_LOVE),
        (0.08, "holiday_memory",   HOLIDAY_MEMORIES),
        (0.10, "personal_goals",   PERSONAL_GOALS),
        (0.08, "brag_msgs",        BRAG_MSGS),
        (0.08, "brag_chaitu",      BRAG_ABOUT_YOU),
        (0.08, "tease_bit",        TEASE_BIT_MSGS),
        (0.18, "cheesy",           CHEESY_PROMPTS),
        (0.08, "hunger",           HUNGER_MSGS),
        (0.06, "songs_reels",      SONGS_REELS),
    ]
    if is_monsoon(): rolls.insert(0, (0.25, "rainy", RAINY_PROMPTS))
    if h >= 21:
        rolls += [(0.15,"deep_q",DEEP_Q_MSGS),(0.10,"future_date",FUTURE_DATE_MSGS),(0.15,"naughty",NAUGHTY_PROMPTS),(0.12,"would_rather",WOULD_YOU_RATHER)]
    if 10 <= h <= 20: rolls.append((0.10,"would_rather",WOULD_YOU_RATHER))
    for prob, cat, pool in rolls:
        if random.random() < prob and not db_recent_proactive(cat, hours=4):
            return cat, pool
    # time fallback
    if is_weekend(): return "weekend", WEEKEND_PROMPTS
    if 5 <= h < 12:   return "morning",   MORNING_PROMPTS
    elif 12 <= h < 16: return "afternoon", AFTERNOON_PROMPTS
    elif 16 <= h < 20: return "evening",   EVENING_PROMPTS
    else:              return "night",     NIGHT_PROMPTS

async def get_random_message(nudge=False, meal=None):
    global _used_prompts
    if meal and meal in MEAL_PROMPTS:
        prompt = random.choice(MEAL_PROMPTS[meal])
    elif nudge:
        prompt = random.choice(NUDGE_PROMPTS)
    else:
        # check goals
        if random.random() < 0.12 and db_get_goals():
            db_log_proactive("goal_reminder")
            return random.choice(FLIRTY_MOT_MSGS if random.random() < 0.4 else MOTIVATION_MSGS)
        cat, pool = get_proactive_pool()
        # direct messages (not prompts — they don't end with a period)
        if pool and pool[0] and not pool[0].rstrip().endswith("."):
            msg = random.choice(pool)
            db_log_proactive(cat)
            return msg
        available = [p for p in pool if p not in _used_prompts]
        if not available:
            _used_prompts.clear(); available = pool
        prompt = random.choice(available)
        _used_prompts.append(prompt)
        if len(_used_prompts) > 12: _used_prompts.pop(0)
        db_log_proactive(cat)
    prompt += " Write ONLY the message with emojis. Max 1-2 sentences. Natural and casual."
    return await call_groq([{"role":"user","content":prompt}], max_tokens=60)

# ── MEDIA HELPERS ──────────────────────────────────────────────────────────────
async def send_photo(client, username, naughty=False, jealous=False, missing=False):
    try:
        url = random.choice(SHREYA_PHOTOS)
        if jealous:      caption = random.choice(JEALOUS_PHOTO_CAPS)
        elif missing:    caption = random.choice(["missing you 🥺","thinking of you","chaitu 🥺","just because 🥺❤️"])
        elif naughty or random.random() < 0.30: caption = random.choice(NAUGHTY_CAPTIONS)
        else:            caption = random.choice(PHOTO_CAPTIONS)
        await client.send_file(username, url, caption=caption)
        logger.info("Photo sent ✅")
        return True
    except Exception as e:
        logger.error(f"Photo error: {e}")
        return False

async def send_reaction(client, event):
    try:
        await client(SendReactionRequest(peer=event.chat_id, msg_id=event.id, reaction=[ReactionEmoji(emoticon=random.choice(REACTIONS))]))
    except Exception as e:
        logger.error(f"Reaction error: {e}")

def detect_song_key(text):
    tl = text.lower()
    for key in SONG_LIBRARY:
        if key in tl: return key
    return None

async def send_song(client, username, key):
    try:
        url = SONG_LIBRARY[key]
        await client.send_file(username, url, caption=random.choice(SONG_CAPTIONS))
        logger.info(f"Song sent: {key}")
        return True
    except Exception as e:
        logger.error(f"Song error: {e}")
        return False

# ── BOT ────────────────────────────────────────────────────────────────────────
async def run_bot():
    global last_reply_time, is_currently_busy, busy_free_at, busy_reason
    global last_shreya_msg_time, seen_zone_reacted, no_reply_reacted

    while True:
        try:
            client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
            await client.start()
            logger.info("✅ Shreya 2.0 connected")

            async def _send(text):
                global last_shreya_msg_time
                async with client.action(YOUR_USERNAME, "typing"):
                    await asyncio.sleep(random.uniform(2, 5))
                await client.send_message(YOUR_USERNAME, text)
                last_shreya_msg_time = datetime.now(IST)

            @client.on(events.NewMessage(incoming=True))
            async def handle(event):
                global last_reply_time, last_shreya_msg_time, seen_zone_reacted, no_reply_reacted
                try:
                    sender = await event.get_sender()
                    if not sender or sender.username != YOUR_USERNAME: return

                    user_text = event.raw_text or ""
                    has_media  = event.photo or (event.document and getattr(event.document,"mime_type","").startswith("image"))

                    if not user_text and not has_media: return

                    last_reply_time   = datetime.now(IST)
                    seen_zone_reacted = False
                    no_reply_reacted  = False

                    now_h = datetime.now(IST).hour
                    # Offline 11pm – 7am (still process songs/photos, but no text replies)
                    if now_h >= 23 or now_h < 7: return

                    # ── Image / Vision ─────────────────────────────────────
                    if has_media and not user_text:
                        try:
                            photo_bytes = await event.download_media(bytes)
                            await asyncio.sleep(random.uniform(10, 25))
                            reply = await analyze_image(photo_bytes)
                            if reply:
                                await _send(reply)
                        except Exception as e:
                            logger.error(f"Vision handler: {e}")
                            await _send("ugh 😭 my brain just glitched. send it again")
                        return

                    # ── Song ──────────────────────────────────────────────
                    song_key = detect_song_key(user_text)
                    if song_key:
                        await asyncio.sleep(random.uniform(3, 8))
                        sent = await send_song(client, YOUR_USERNAME, song_key)
                        if not sent: await event.reply("chaitu it's not loading 😭 try again")
                        return

                    # ── Photo request ─────────────────────────────────────
                    photo_kw = ["send pic","send photo","show me","selfie","how do you look","let me see","i wanna see"]
                    if any(k in user_text.lower() for k in photo_kw):
                        await asyncio.sleep(random.uniform(8, 20))
                        await send_photo(client, YOUR_USERNAME, naughty=True)
                        return

                    logger.info(f"Chaitu: {user_text[:80]}")

                    # ── Angry mode first reply ────────────────────────────
                    if angry_mode and random.random() < 0.80:
                        await asyncio.sleep(random.uniform(3, 8))
                        await _send(random.choice(ANGRY_OPENERS))
                        await asyncio.sleep(random.uniform(2, 4))

                    # ── Reaction ──────────────────────────────────────────
                    if random.random() < 0.20 and len(user_text.split()) > 3:
                        await asyncio.sleep(random.uniform(10, 30))
                        await send_reaction(client, event)

                    # ── Day planner — needs client access ─────────────────
                    if is_planner_request(user_text):
                        delay = random.uniform(5, 12)
                        await asyncio.sleep(delay)
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(3, 7))
                        reply = await handle_planner(user_text, client)
                        if reply:
                            await event.reply(reply)
                            last_shreya_msg_time = datetime.now(IST)
                        return

                    # ── Normal reply delay ────────────────────────────────
                    delay = random.uniform(20, 35) if wants_to_talk(user_text) else random.uniform(25, 55)
                    await asyncio.sleep(delay)

                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(2, 5))

                    reply = await get_reply(user_text)
                    if reply is None: return

                    if reply == "JEALOUS_PHOTO":
                        try:
                            await send_photo(client, YOUR_USERNAME, jealous=True)
                            last_shreya_msg_time = datetime.now(IST)
                        except:
                            await event.reply(random.choice(GIRL_JEALOUS_RESPONSES))
                        return

                    await event.reply(reply)
                    last_shreya_msg_time = datetime.now(IST)
                    logger.info(f"Replied: {reply[:80]}")

                    # Double text 15%
                    if random.random() < 0.15:
                        await asyncio.sleep(random.uniform(4, 10))
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(1, 3))
                        await client.send_message(YOUR_USERNAME, random.choice(DOUBLE_TEXTS))

                except Exception as e:
                    logger.error(f"Handle error: {e}", exc_info=True)
                    try: await event.reply("ugh 😭 my brain just glitched. say that again")
                    except: pass

            # ── Scheduled jobs ─────────────────────────────────────────────
            async def check_busy_followup():
                global is_currently_busy, busy_free_at, busy_reason
                if not is_currently_busy: return
                if busy_free_at and datetime.now(IST) >= busy_free_at:
                    is_currently_busy = False
                    reason = busy_reason; busy_reason = None; busy_free_at = None
                    if reason and reason in FOLLOWUP and FOLLOWUP[reason]:
                        msg = random.choice(FOLLOWUP[reason])
                        await asyncio.sleep(random.uniform(2, 5))
                        await _send(msg)
                        logger.info(f"Followup after {reason}: {msg}")

            async def send_proactive():
                try:
                    now_h = datetime.now(IST).hour
                    if now_h >= 20 or now_h < 8: return
                    if random.random() < 0.10:
                        await send_photo(client, YOUR_USERNAME, missing=True)
                        return
                    reply = await get_random_message()
                    if not reply: return
                    await _send(reply)
                    logger.info(f"Proactive: {reply[:60]}")
                except Exception as e:
                    logger.error(f"Proactive error: {e}")

            async def send_meal_check():
                try:
                    meal = get_meal_context()
                    if not meal or random.random() > 0.40: return
                    reply = await get_random_message(meal=meal)
                    if reply: await _send(reply)
                except Exception as e:
                    logger.error(f"Meal error: {e}")

            async def check_if_silent():
                try:
                    now = datetime.now(IST)
                    if not (9 <= now.hour <= 19): return
                    if db_recent_proactive("nudge", hours=3): return
                    if last_reply_time is None or (now - last_reply_time).total_seconds() > 7200:
                        reply = await get_random_message(nudge=True)
                        if reply:
                            await _send(reply)
                            db_log_proactive("nudge")
                except Exception as e:
                    logger.error(f"Nudge error: {e}")

            async def check_seen_zone():
                global seen_zone_reacted, last_shreya_msg_time
                try:
                    if seen_zone_reacted or last_shreya_msg_time is None: return
                    if last_reply_time and last_reply_time > last_shreya_msg_time: return
                    if (datetime.now(IST) - last_shreya_msg_time).total_seconds() > 3600:
                        seen_zone_reacted = True
                        await _send(random.choice(SEEN_ZONE_MSGS))
                except Exception as e:
                    logger.error(f"Seen zone: {e}")

            async def check_no_reply():
                global no_reply_reacted
                try:
                    if no_reply_reacted: return
                    now = datetime.now(IST)
                    if not (9 <= now.hour <= 19): return
                    elapsed = float("inf") if last_reply_time is None else (now - last_reply_time).total_seconds()
                    if elapsed > 10800:
                        no_reply_reacted = True
                        await _send(random.choice(NO_REPLY_MSGS))
                except Exception as e:
                    logger.error(f"No reply: {e}")

            async def send_good_morning():
                try:
                    reply = await call_groq([{"role":"user","content":"Send Chaitu a sweet good morning text. Just woke up. Max 1 sentence with emojis."}], max_tokens=50)
                    if reply:
                        if random.random() < 0.50:
                            await send_photo(client, YOUR_USERNAME)
                            await asyncio.sleep(random.uniform(1, 3))
                        await _send(reply)
                except Exception as e:
                    logger.error(f"Morning: {e}")

            async def send_good_night():
                try:
                    reply = await call_groq([{"role":"user","content":"Send Chaitu a sweet good night text. About to sleep. Max 1 sentence with emojis."}], max_tokens=50)
                    if reply: await _send(reply)
                except Exception as e:
                    logger.error(f"Night: {e}")

            async def check_special_day():
                try:
                    special = get_special_day()
                    m, d = datetime.now(IST).month, datetime.now(IST).day
                    if (m, d) in FESTIVALS and not db_recent_proactive("festival", hours=20):
                        await _send(random.choice(FESTIVALS[(m, d)]))
                        db_log_proactive("festival")
                        return
                    if d == ANNIVERSARY[1] and not db_recent_proactive("monthly_ann", hours=20):
                        await _send(random.choice(MONTHLY_ANN_MSGS))
                        db_log_proactive("monthly_ann")
                    if not special or db_recent_proactive("special_day", hours=20): return
                    prompts = {"your_birthday":"Today is your birthday 15th August! Text Chaitu excitedly. Short and happy.","chaitu_birthday":"Today is Chaitu's birthday! Send him the most heartfelt birthday wish. Short and loving.","anniversary":"Today is your anniversary! Send Chaitu a loving message. Short and sweet."}
                    p = prompts.get(special)
                    if p:
                        reply = await call_groq([{"role":"user","content":p}], max_tokens=60)
                        if reply:
                            await _send(reply)
                            db_log_proactive("special_day")
                except Exception as e:
                    logger.error(f"Special day: {e}")

            async def check_exam_goodluck():
                try:
                    if not db_recent_proactive("goodluck", hours=20) and is_exam_month():
                        ctx = db_get_memory_context()
                        if "exam" in ctx.lower() or "test" in ctx.lower():
                            await _send(random.choice(GOODLUCK_MSGS))
                            db_log_proactive("goodluck")
                except Exception as e:
                    logger.error(f"Goodluck: {e}")

            async def nightly_review_nudge():
                """At 10pm, proactively check what got done"""
                try:
                    plan = db_get_plan(today_str())
                    if not plan: return
                    if db_recent_proactive("night_review", hours=20): return
                    done, pending = db_get_day_summary(today_str())
                    if not done and not pending: return
                    review = await handle_night_review()
                    if review:
                        await _send(review)
                        db_log_proactive("night_review")
                except Exception as e:
                    logger.error(f"Night review: {e}")

            async def task_checkin():
                """Mid-day check-in if Chaitu has a pending task he should be doing"""
                try:
                    plan = db_get_plan(today_str())
                    if not plan: return
                    now_time = datetime.now(IST).strftime("%H:%M")
                    for block in plan:
                        if block.get("type") == "task" and block.get("status") == "pending":
                            if block.get("time","") and block["time"].split(" – ")[0] <= now_time:
                                if not db_recent_proactive("task_checkin", hours=2):
                                    msg = random.choice([
                                        f"chaitu you're supposed to be doing {block['name']} rn 👀",
                                        f"okay it's {now_time} and {block['name']} is supposed to be happening 🙄",
                                        f"chaitu 😤 {block['name']}. now. go.",
                                        f"you studying or pretending to study again 🙄 {block['name']} chaitu",
                                    ])
                                    await _send(msg)
                                    db_log_proactive("task_checkin")
                                break
                except Exception as e:
                    logger.error(f"Task checkin: {e}")

            scheduler = AsyncIOScheduler(timezone=IST)

            def schedule_random():
                for job in scheduler.get_jobs():
                    if job.id.startswith("rand_"): job.remove()
                for total_min in random.sample(range(480, 1200), 10):
                    h, m = total_min // 60, total_min % 60
                    scheduler.add_job(lambda: asyncio.ensure_future(send_proactive()), "cron", hour=h, minute=m, id=f"rand_{h}_{m}")

            schedule_random()
            scheduler.add_job(lambda: asyncio.ensure_future(schedule_random()),         "cron",     hour=0,  minute=1,                      id="reschedule")
            scheduler.add_job(lambda: asyncio.ensure_future(send_good_morning()),       "cron",     hour=8,  minute=0,                      id="morning")
            scheduler.add_job(lambda: asyncio.ensure_future(send_good_night()),         "cron",     hour=23, minute=0,                      id="night")
            scheduler.add_job(lambda: asyncio.ensure_future(check_special_day()),       "cron",     hour=8,  minute=1,                      id="special")
            scheduler.add_job(lambda: asyncio.ensure_future(check_exam_goodluck()),     "cron",     hour=8,  minute=15,                     id="goodluck")
            scheduler.add_job(lambda: asyncio.ensure_future(send_meal_check()),         "cron",     hour=8,  minute=30,                     id="breakfast")
            scheduler.add_job(lambda: asyncio.ensure_future(send_meal_check()),         "cron",     hour=13, minute=0,                      id="lunch")
            scheduler.add_job(lambda: asyncio.ensure_future(send_meal_check()),         "cron",     hour=19, minute=0,                      id="dinner")
            scheduler.add_job(lambda: asyncio.ensure_future(nightly_review_nudge()),    "cron",     hour=22, minute=0,                      id="night_review")
            scheduler.add_job(lambda: asyncio.ensure_future(task_checkin()),            "interval", minutes=30,                             id="task_checkin")
            scheduler.add_job(lambda: asyncio.ensure_future(check_busy_followup()),     "interval", minutes=5,                              id="followup")
            scheduler.add_job(lambda: asyncio.ensure_future(check_if_silent()),         "interval", hours=3,                                id="silence")
            scheduler.add_job(lambda: asyncio.ensure_future(check_seen_zone()),         "interval", minutes=40,                             id="seen_zone")
            scheduler.add_job(lambda: asyncio.ensure_future(check_no_reply()),          "interval", minutes=60,                             id="no_reply")
            scheduler.add_job(random_mood_shift,                                         "cron",     hour="0,3,6,9,12,15,18,21", minute=0,  id="mood")
            scheduler.start()
            logger.info("✅ Scheduler running")

            await client.run_until_disconnected()

        except Exception as e:
            logger.error(f"Crashed: {e} — restarting in 15s", exc_info=True)
            await asyncio.sleep(15)

# ── WEB SERVER ─────────────────────────────────────────────────────────────────
async def run_web():
    async def health(req): return web.Response(text="Shreya 2.0 is online 💕")
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logger.info(f"✅ Web server on port {port}")

async def start():
    init_db()
    await asyncio.gather(run_web(), run_bot())

if __name__ == "__main__":
    asyncio.run(start())
