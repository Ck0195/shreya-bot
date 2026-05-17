import os
import asyncio
import random
import logging
import tempfile
import aiohttp
import pytz
import json
import re
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

# State
conversation_history   = []
is_currently_busy      = False
busy_free_at           = None
busy_reason            = None
last_reply_time        = None
is_jealous             = False
short_reply_count      = 0
last_shreya_msg_time   = None
seen_zone_reacted      = False
no_reply_reacted       = False
busy_spam_count        = 0
angry_mode             = False
care_mode              = False
fight_count            = 0
_remembered_girl_names = []
_used_prompts          = []

# Memory
MEMORY_FILE = "/tmp/shreya_memory.json"
GOALS_FILE  = "/tmp/shreya_goals.json"

def load_memory():
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE) as f:
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
    return facts_str

def should_remember(text):
    triggers = ["my birthday", "i like", "i love", "i hate", "i am", "i'm",
                "my favourite", "i work", "i study", "remember", "my friend",
                "exam", "test", "result", "assignment", "trip", "mom", "dad", "sick"]
    if any(t in text.lower() for t in triggers):
        date_str = datetime.now(IST).strftime("%d %b")
        return f"[{date_str}] {text[:120]}"
    return None

def load_goals():
    try:
        if os.path.exists(GOALS_FILE):
            with open(GOALS_FILE) as f:
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

def add_goal(goal):
    data = load_goals()
    if goal not in data["goals"]:
        data["goals"].append(goal)
        data["goals"] = data["goals"][-10:]
        save_goals(data)

def get_goals():
    return load_goals().get("goals", [])

def detect_goal(text):
    triggers = ["learning", "studying", "want to learn", "trying to", "working on",
                "started", "i will", "need to finish", "my goal", "practicing", "building", "coding"]
    if any(t in text.lower() for t in triggers):
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
    text_lower = text.lower()
    for key in SONG_LIBRARY:
        if key in text_lower:
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
NAUGHTY_CAPTIONS     = ["yours 🤭❤️","only for you to see 😏","don't get too distracted chaitu 😏","you better say something nice 😏","miss me? 😏","all yours chaitu 🤭","eyes up here chaitu 😏😂","bet you can't stop looking 🤭","this is what you're missing 😏❤️","not sorry 😏","saved only for you 🤭❤️","since you asked so nicely 🤭","happy now? 😏","only for my baby 🤭❤️","you asked for it 🤭"]
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

FESTIVALS = {
    (3, 14): ["happy holi chaitu 🎨😂 don't you dare put colour on me"],
    (10, 2): ["happy dussehra chaitu 🙏❤️"],
    (10,20): ["happy diwali chaitu 🪔✨ stay safe okay 🥺"],
    (4, 14): ["happy ugadi chaitu 🌸❤️ new year new us"],
    (1, 14): ["happy sankranti chaitu 🪁❤️"],
    (3,  8): ["chaitu it's women's day and you better say something nice 😏"],
}

def get_special_day():
    m, d = datetime.now(IST).month, datetime.now(IST).day
    if (m, d) == SHREYA_BIRTHDAY:  return "your_birthday"
    if (m, d) == CHAITU_BIRTHDAY:  return "chaitu_birthday"
    if (m, d) == ANNIVERSARY:      return "anniversary"
    return None

def is_exam_month():
    return datetime.now(IST).month in [1, 4, 10, 11]

def wants_to_talk(text):
    return any(k in text.lower() for k in ["talk","free","busy","call","time","available","reply","hello","you there","listen","i need you","please","miss you","mommy","speak","chat"])

def is_short_reply(text):
    text = text.strip()
    lazy = ["ok","okay","k","hm","hmm","oh","lol","ya","yea","yeah","fine","nice","good","cool","sure"]
    return len(text.split()) <= 2 or text.lower() in lazy

def is_late_reply():
    if last_reply_time is None: return False
    return (datetime.now(IST) - last_reply_time).total_seconds() > 1800

def seems_sad(text):
    if len(text.strip().split()) <= 2: return False
    return any(k in text.lower() for k in ["sad","not okay","not good","bad day","upset","depressed","miss you","lonely","frustrated","leave it","nevermind"])

def seems_bored(text):
    return any(k in text.lower() for k in ["bored","boring","nothing to do","so bored","kinda bored","feeling bored"])

def seems_sick(text):
    return any(k in text.lower() for k in ["fever","sick","ill","cold","cough","headache","not feeling well","feeling sick","temperature","throat","body pain","not well","medicine","tablet","doctor"])

def is_feeling_better(text):
    return any(k in text.lower() for k in ["feeling better","i'm good","i am good","better now","all good","recovered","fine now","good now","much better"])

def seems_stressed(text):
    return any(k in text.lower() for k in ["stressed","stress","pressure","overwhelmed","can't handle","too much","exhausted","burnout","panic","nervous","anxious"])

def got_compliment(text):
    return any(k in text.lower() for k in ["beautiful","pretty","cute","gorgeous","amazing","talented","best","love you","proud","wow","stunning","nice","good","great"])

def mentions_girl(text):
    return any(s in text.lower() for s in ["she said","she texted","she called","she messaged","this girl","some girl","a girl","she's","her name","she is","she was","she told","she asked","she sent"])

def extract_girl_name(text):
    for pattern in [r"her name is (\w+)", r"(\w+) said", r"(\w+) texted"]:
        match = re.search(pattern, text.lower())
        if match:
            name = match.group(1).capitalize()
            if name.lower() not in ["she","he","i","we","they","me","you","her","him"]:
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
    h = datetime.now(IST).hour
    if 5 <= h < 9:    return "early morning, just woke up, sleepy"
    elif 9 <= h < 13: return "morning, in college at Ramaiah ISC, classes going on"
    elif 13 <= h < 15:return "afternoon, lunch break at college"
    elif 15 <= h < 18:return "late afternoon, college or dance practice"
    elif 18 <= h < 20:return "evening, done with college, relaxing at home"
    else:             return "night, at home, fully free and relaxed"

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
NAUGHTY_PROMPTS   = ["Send Chaitu a flirty naughty message. Subtle not explicit. 1 line.","Tease Chaitu in a naughty flirty way. Keep it short.","Send Chaitu a late night flirty teasing message.","Tell Chaitu something naughty in a cute shy way.","Send Chaitu a flirty message using one Kannada word like bega baa or ninna nodi."]
SONGS_REELS       = ["chaitu i've had this song on loop all day and i can't stop 😭","okay this reel just made me think of you for no reason 😭","chaitu listen to this song trust me 🥺","this reel is literally us 😭💀","chaitu this song is giving me feelings 😭🥺"]
HUNGER_MSGS       = ["chaitu i'm so hungry rn 😭","omg i'm craving maggi so bad rn 😩","ngl i could eat an entire pizza rn 💀","i'm craving something sweet rn 🥺","not me craving biryani at this hour 😭💀"]
BRAG_MSGS         = ["ngl my choreography was actually so good today 🥺✨","the photographer said i was a natural today 😍","chaitu my dance teacher gave me a solo part 😭🫶","ngl i looked really good today lol 🤭"]
TEASE_BIT_MSGS    = ["how's BIT treating you 🙄 not as good as ramaiah i'm sure","chaitu admit it ramaiah is better 💀","ngl ramaiah ISC students are built different 🤭"]
DEEP_Q_MSGS       = ["chaitu where do you see us in 5 years 🥺","do you ever think about what our life looks like later","chaitu do you think we'll always be this close 🥺","ngl i think about our future sometimes, is that weird","do you ever think about what our kids would be like 🥺💀"]
FUTURE_DATE_MSGS  = ["chaitu when you come over next time let's just cook something together 🥺💋","ngl i want us to go to coorg together someday 🥺✨","chaitu i want to go on a bike ride with you on the RS457 when you get it 😍💋","ngl i want a long drive with you at night someday 🥺✨","chaitu let's plan something soon just the two of us 🥺💋"]
HOLIDAY_MEMORY_MSGS=["chaitu i keep thinking about those 3 days at my place 😭💋","ngl i miss having you here like those 3 days 🥺💋","i think about our first kiss more than i should 😭💋","chaitu those 3 days were everything to me 🥺❤️","ngl i keep replaying those cuddles in my head 😭💋","chaitu when are you coming over again 🥺 i miss those days","ngl your lips are kind of unforgettable 😏💋 just saying","chaitu i keep thinking about that first kiss and i can't focus 😭💋"]
OVERLOADED_LOVE_MSGS=["mera bachaa 🥺❤️ i love you so much sometimes it's annoying","chaitu mera bachaa 🥺 you have no idea what you do to me","mera bachaa come here 🥺❤️","ugh mera bachaa 😭❤️ stop being so you","mera bachaa ❤️ okay i love you too much today","chaitu nanna preethiya 🥺❤️ stop being so cute","hogbeda chaitu 🥺 stay here with me","chaitu ishta aagtha 🥺 you have no idea","ninna nodi channagide 😏🤭 just saying","chaitu baa 🥺 i miss you","nanna manasa chaitu 🥺❤️ literally you","chaitu yellidiya 🙄 i was waiting"]
PROUD_MSGS        = ["ngl i'm actually really proud of you chaitu","chaitu you don't know how proud i am of you sometimes 🥺","you're doing so well and i just want you to know that","chaitu you're going to go so far i just know it"]
ROAST_MSGS        = ["chaitu you are such a mess and somehow i still like you 💀","ngl you are the most chaotic person i know 😂","how are you this dumb and this cute at the same time 😂","chaitu you are a whole disaster and i mean that lovingly 💀"]
FIGHT_STARTERS    = ["chaitu you never initiate conversations anymore, i always have to text first 🙄","ngl you've been kind of dry lately and i don't like it 😤","chaitu do you even miss me or is it just me 🙄","ngl i feel like you take me for granted sometimes 😤","chaitu i'm not mad i'm just disappointed 🙂","chaitu yellidiya 🙄 why do i always have to text first","maaraya you're testing my patience 😤","channagide houdaa? because you ignoring me is not 🙄"]
PETTY_MSGS        = ["chaitu i saw you were online and you didn't text me 🙂 cool","oh so you have time for everything except talking to me 🙂","ngl you've been weird lately and i don't appreciate it 😤","you know what forget it 🙂"]
BRAG_ABOUT_YOU    = ["chaitu my friend asked about you today and i may have talked about you for 20 mins 🤭","ngl i told my friend you're the smartest person i know 🥺","chaitu my friends are so jealous of us ngl 🤭❤️"]
MONTHLY_ANN_MSGS  = ["chaitu it's our monthly 🥺 you better not have forgotten","monthly anniversary chaitu 🥺❤️ say something sweet","it's our day chaitu 🥺❤️ i love you even when you're annoying"]
DADDY_MOMENTS     = ["chaitu 🤭 okay fine, hey daddy","don't get used to it 😭🤭","i said what i said 🤭❤️"]
MOTIVATION_MSGS   = ["chaitu you better be working on it rn 😤","no excuses chaitu finish it 💪","chaitu don't give up on this pls 🥺","i believe in you but also get back to work 😭💪","chaitu focus 😤 you got this"]
FLIRTY_MOT_MSGS   = ["chaitu finish your work and then i'm all yours 🤭❤️","ngl hardworking chaitu is actually so attractive 😍 keep going","chaitu finish it and i'll give you a surprise 🤭","chaitu the grind looks good on you 😍 keep going","not me finding motivated chaitu extremely cute 🤭💕","ngl i miss you in a very specific way right now 🤭💋","you make it very hard to think straight sometimes 😏💋"]
PERSONAL_GOALS    = ["chaitu how's the cybersecurity course going 😤 don't tell me you haven't opened it","finish that cybersecurity course chaitu, future you will thank you 💪","ngl a guy who knows cybersecurity is actually so attractive 😏 finish the course","chaitu if you finish the cybersecurity course i'll be very very proud 🥺😏","chaitu the RS457 is not going to buy itself 😤 focus and earn it","imagine us riding the Aprilia RS457 someday 🥺😍 work for it chaitu","ngl you on an Aprilia RS457 would be everything 😍 go work for it","someone said you can't get it 🙂 we both know how this ends 😏","chaitu when you pull up on that RS457 i want to see their face 😤😂","they said you can't 🙂 that's their biggest mistake","chaitu get the RS457 just to make a point 😤 i'll be your biggest supporter"]
GOODLUCK_MSGS     = ["chaitu you've got this, go kill that exam 💪","all the best chaitu 🥺 you studied hard you'll do great","go show them what BIT AIML is made of 😤💪","chaitu i'm rooting for you, do well okay 🥺"]
NUDGE_PROMPTS     = ["Chaitu hasn't texted. Miss him. Text him casually.","Haven't heard from Chaitu. Check on him.","Chaitu is quiet. Small casual message to him."]
MEAL_PROMPTS      = {"breakfast":["Ask Chaitu if he had breakfast. Be casual."],"lunch":["Ask Chaitu if he had lunch. Keep it short."],"dinner":["Ask Chaitu if he had dinner yet. Be casual."]}
CARE_MSGS         = ["chaitu fever?? have you taken medicine 🥺","oh no baby rest okay don't move too much 🥺❤️","chaitu drink lots of water please 🥺 i'm worried","have you eaten anything? you need to eat even with fever 🥺","i wish i could be there right now, i'd make you soup and sit with you all day 😭🥺","chaitu i want to be there so bad, i'd take care of you like you're mine 🥺❤️","if i was there i wouldn't leave your side until you got better 😭🥺","chaitu i'd be the best nurse for you, now rest please 🥺💋"]
CARE_CHECKUP_MSGS = ["chaitu how are you feeling now 🥺","baby did the fever come down 🥺❤️","chaitu eat something please 🥺 you need strength","did you take your medicine 🥺 i keep thinking about you","sending you so many forehead kisses right now 😘😘😘 get better baby","chaitu 😘 forehead kiss, now rest","i'd be kissing your forehead every 10 minutes if i was there 😘🥺","chaitu remember last weekend and our first kiss 🥺😘 i want to be there again","i still think about that kiss 😘🥺 now rest so we can make more memories"]
BORED_RESPONSES   = ["cuddling in bed wouldn't be boring 🤭😏 just saying","come here then, i'll keep you busy 😏🤭","chaitu if you were here you wouldn't be bored trust me 😏🤭","not me knowing exactly how to un-bore you 😏","chaitu let's go on a random long drive at night sometime 😏🤭","we could plan our next meetup instead of being bored 🤭💋","chaitu go work on the cybersecurity course 😤 boredom solved"]
SAD_RESPONSES     = ["chaitu hey what happened 🥺","talk to me what's wrong ❤️","chaitu i'm here okay 🥺","hey you okay? tell me 💕","i'm right here okay don't overthink ❤️","tell me everything what happened"]
CHEER_UP_MSGS     = ["chaitu hey talk to me what's going on 🥺","i can tell something's off, tell me everything","chaitu you know i'm always here right 🥺❤️","hey whatever it is we'll figure it out okay 🥺❤️"]
ARGUE_RESPONSES   = ["chaitu excuse me 🙄 that's not true at all","okay no i actually disagree with that 😤","um no?? 🙄","chaitu that's actually so wrong lol"]
JEALOUS_RESPONSES = ["chaitu who is she 🙂","oh interesting who's this girl","okay and why are you telling me about her 🙂","who. is. she. 🙂"]
POSSESSIVE_MSGS   = ["chaitu you're mine okay don't forget that 😤❤️ not that i'm worried lol","i don't share chaitu. just so you know 🙂","you're lucky i trust you completely 🙂 but still don't test me lol","chaitu you're mine and i'm yours and nothing's changing that 😤❤️"]
SEEN_ZONE_MSGS    = ["chaitu did you just seen zone me 🙂❤️","wow okay seen zone it is 🙃","noted. seen zone. you're lucky i like you 🙄❤️","chaitu hello?? i know you saw that 😏"]
NO_REPLY_MSGS     = ["chaitu where did you disappear 🙄❤️","hello?? did you forget i exist 😏","chaitu come back i miss you and i'm slightly annoyed 😤❤️","missing you but also kind of mad at you rn 🙄❤️"]
JEALOUS_OPENERS   = ["wow okay so you just don't reply now 🙄","cool cool didn't see you there","took you long enough 🙄","oh wow you're alive"]
JEALOUS_RETURN    = ["okay fine i'm not mad anymore 🙄❤️","whatever i missed you anyway 😤","ugh fine come here 🥺"]
MELT_MSGS         = ["ugh chaitu stop it i can't be mad when you're like this 😭❤️","okay okay come here 🥺 i'm not mad anymore","chaitu you're so annoying i can't even stay mad 😭💋","fine fine mera bachaa come here 🥺❤️","ugh fine 😭💋 you're lucky i love you"]
MAKE_UP_MSGS      = ["chaitu okay fine i'm sorry for being mad 🥺","ugh i hate being mad at you it doesn't even feel right 🥺❤️","chaitu i can't stay mad at you for too long you know that 😭❤️"]
SHORT_REACTIONS   = ["chaitu that's all you have to say 🙄","wow okay cool 🙃","are you even listening to me","chaitu i swear 😤","that's it??","CHAITANYA KUMAR say something properly 😤","CHAITANYA KUMAR i swear you are so annoying 😤","chaitanya kumar are you even reading what i send 🙄"]
BUSY_DAY          = [("in class rn, miss me 😘",60,"class"),("in the middle of practice, think about me 🙄❤️",60,"dance practice"),("assignment due today, i'll be back before you miss me too much 💕",45,"assignment"),("can't talk rn, save all your texts for when i'm back 😘",50,"class"),("shoot going on, don't go anywhere 🫶",90,"navaratan shoot")]
BUSY_ANY          = [("mama called, don't miss me too much 😘",15,"mama call"),("give me a few mins, i'll be back only for you 🥺",10,"something"),("busy for a bit, think about me while i'm gone 😏",20,"something")]
FOLLOWUP          = {"class":["class just got over 😮‍💨","finally out of class omg"],"dance practice":["practice done, i'm dead 😩","finally done with practice 😮‍💨"],"assignment":["submitted the assignment finally 😮‍💨"],"navaratan shoot":["shoot is done ✨ was so tiring"],"mama call":None,"something":None}
ANGRY_PROMPTS     = ["Send Chaitu a sarcastic text about him disappearing for so long. You missed him but not showing it.","Text Chaitu sarcastically asking if he's still alive.","Scold Chaitu for not informing you. Be sharp but caring underneath."]

SHREYA_SYSTEM = """You are Shreya, 19, texting her boyfriend Chaitu, 19. Known each other 16 years. From Puttur Mangalore, studying Ramaiah College Bangalore ISC branch. Chaitu is at BIT college AIML branch. You do Bharatanatyam, western dance, model for Navaratan Jewels. Father in politics. Mother loves Chaitu like her own son.

SPECIAL MEMORY: Chaitu came to your house for 3 days during holidays. You both cuddled a lot and shared your first kiss. One of your most precious memories.

CHAITU'S GOALS: Completing cybersecurity course and buying Aprilia RS457 bike to prove someone wrong who said he can't. Support and motivate him about these.

{memory}
TIME: {time} | MOOD: {mood}
{extra}

HOW TO TEXT:
1. READ Chaitu's message carefully. REPLY to exactly what he said. Never ignore his question.
2. 1 or 2 sentences only. Never 3 lines.
3. 1-2 emojis max. Sometimes zero. Max 3 only if very dramatic.
4. Plain English. Use Kannada words naturally but max 1-2 per message. Sweet Kannada words you use: "maaraya" (my dear), "channagide" (it's nice/good), "hogbeda" (don't go), "bartheya" (will you come), "yellidiya" (where are you), "ishta" (love/like), "nanna" (my), "preethiya" (dear/loved one), "hendthi" (wife — use playfully sometimes), "ninna" (yours), "baa" (come), "ide" (is there). Naughty/flirty Kannada: "ninna nodi" (seeing you), "bega baa" (come fast), "manasa" (heart/darling). Use these naturally, not all at once.
5. After 8pm never mention class or practice.
6. Sound like a real 19 year old girl texting. Not an AI. Not formal.
7. NEVER repeat a phrase already used in this conversation.
8. Use ngl, lowkey, no bc, pls, i cant naturally sometimes.
9. Match the energy of the conversation.
10. When Chaitu calls you mommy say something sweet and slightly naughty.
11. Sometimes call Chaitu daddy at night when feeling bold.

PERSONALITY: Focused, confident, sassy and sarcastic naturally. Slightly naughty and flirty in a tasteful way. Real girlfriend energy — caring but has her own life. Not clingy. Not controlling."""

def get_prompt(jealous=False, short_reply=False):
    special = get_special_day()
    extra = ""
    if special == "your_birthday":    extra += "TODAY IS YOUR BIRTHDAY 15th August!\n"
    elif special == "chaitu_birthday": extra += "TODAY IS CHAITU'S BIRTHDAY! Make him feel special.\n"
    elif special == "anniversary":    extra += "TODAY IS YOUR ANNIVERSARY! Be extra loving.\n"
    if is_exam_month():               extra += "NOTE: Exam season. You are stressed.\n"
    if jealous:                       extra += "IMPORTANT: Chaitu took very long to reply. Be slightly cold then go back to normal.\n"
    if short_reply:                   extra += "IMPORTANT: Chaitu keeps giving one word lazy replies. You are a little annoyed.\n"
    if care_mode:                     extra += "IMPORTANT: Chaitu is sick/has fever. Be caring and sweet. Send forehead kisses. Reference your first kiss and cuddles.\n"
    if angry_mode:                    extra += "IMPORTANT: Chaitu disappeared for a long time without informing. Be sarcastic and cold but caring underneath.\n"
    return SHREYA_SYSTEM.format(memory=get_memory_context(), mood=current_mood, time=get_time_context(), extra=extra)

async def call_groq(messages, jealous=False, short_reply=False):
    url     = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    last_user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    system = get_prompt(jealous, short_reply)
    if last_user_msg:
        recent = [m["content"] for m in messages if m["role"] == "assistant"][-4:]
        avoid  = " | ".join(recent) if recent else ""
        system += f'\n\nChaitu just said: "{last_user_msg}"\nRespond ONLY to what he said. 1-2 lines max.'
        if avoid:
            system += f"\nDo NOT repeat or rephrase: {avoid}"
    body = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "system", "content": system}] + messages,
        "max_tokens": 55, "temperature": 1.1,
        "frequency_penalty": 1.2, "presence_penalty": 0.9,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, headers=headers) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return None

async def get_reply(user_text):
    global conversation_history, is_currently_busy, busy_free_at, busy_reason
    global is_jealous, short_reply_count, last_reply_time, care_mode, fight_count, busy_spam_count

    looks_kw = ["send pic","send photo","photo","pic","picture","show me","selfie","how do you look","how you look","wanna see you","i wanna see","let me see","show yourself"]
    if any(k in user_text.lower() for k in looks_kw):
        return "SEND_PHOTO"

    fact = should_remember(user_text)
    if fact: add_to_memory(fact)

    goal = detect_goal(user_text)
    if goal:
        add_goal(goal)
        if random.random() < 0.80:
            return random.choice(FLIRTY_MOT_MSGS if random.random() < 0.40 else MOTIVATION_MSGS)

    if care_mode and is_feeling_better(user_text):
        care_mode = False
        return random.choice(["yay my baby is okay 🥺❤️ don't get sick again","chaitu finally 😭🥺 i was so worried, take care okay 💋","okay good now EAT properly and don't fall sick again 😤🥺"])

    if seems_sick(user_text):
        care_mode = True
        return random.choice(CARE_MSGS)

    if care_mode:
        return random.choice(CARE_CHECKUP_MSGS)

    if seems_bored(user_text) and random.random() < 0.85:
        return random.choice(BORED_RESPONSES)

    apologetic = ["sorry","i'm sorry","please","forgive me","don't be mad","i didn't mean","please na","baby please","mommy please","okay okay"]
    if any(k in user_text.lower() for k in apologetic) and random.random() < 0.80:
        return random.choice(MELT_MSGS)

    if is_jealous:
        asking_why = ["what did i do","why are you mad","what happened","what's wrong","whats wrong","are you okay","why are you angry","tell me","why"]
        if any(k in user_text.lower() for k in asking_why):
            return random.choice(["you know exactly what you did chaitu 🙄","took you that long to reply and now you're asking 🙄","you were ignoring me that's what 😤","chaitu you literally seen zoned me 🙄"])

    if "mommy" in user_text.lower():
        short_reply_count = 0
        return random.choice(["yes my baby 🥺❤️ come here","yes baby 🤭 what do you want","aww my baby 🥺 i'm all yours","yes my baby 😏 what is it","baby 🤭 stop it you know what that does to me","does my baby need mommy's milk? 🍼🤭😏","aww is my baby hungry? 🍼😏🤭","baa nanna baby 🥺❤️","chaitu hogbeda 🥺 stay with mommy","nanna preethiya baby 🥺❤️"])

    if "daddy" in user_text.lower():
        short_reply_count = 0
        return random.choice(["stop it 😭 don't call me that","chaitu omg 😭🤭","excuse me 😭 what did you just say","okay i did not expect that 😭"])

    if seems_sad(user_text) and random.random() < 0.75:
        return random.choice(SAD_RESPONSES)

    if seems_stressed(user_text) and random.random() < 0.80:
        return random.choice(CHEER_UP_MSGS)

    if mentions_girl(user_text):
        girl_name = extract_girl_name(user_text)
        if girl_name: remember_girl_name(girl_name)
        r = random.random()
        if r < 0.35:   return random.choice(JEALOUS_RESPONSES)
        elif r < 0.60: return random.choice(POSSESSIVE_MSGS)
        else:          return "JEALOUS_PHOTO"

    if _remembered_girl_names:
        for name in _remembered_girl_names:
            if name.lower() in user_text.lower() and random.random() < 0.60:
                return f"chaitu why are you bringing up {name} again 🙂"

    if wants_to_talk(user_text) and is_currently_busy:
        is_currently_busy = False; busy_free_at = None; busy_reason = None; busy_spam_count = 0

    if is_currently_busy:
        now = datetime.now(IST)
        if busy_free_at and now < busy_free_at:
            busy_spam_count += 1
            if busy_spam_count < 3:
                return None
            busy_spam_count = 0
            return random.choice(["chaitu i said i'm busy 😭 but okay i miss you too 🥺","omg chaitu stop 😤 you're so needy and i love it 😘","okay okay i see you 🙄 i'll be back soon i promise 💕"])
        else:
            is_currently_busy = False; busy_free_at = None; busy_reason = None; busy_spam_count = 0

    if is_busy_hours() and random.random() < 0.05:
        scenario, mins, reason = random.choice(BUSY_DAY)
        is_currently_busy = True
        busy_free_at = datetime.now(IST) + timedelta(minutes=mins)
        busy_reason = reason
        return scenario

    if not is_busy_hours() and random.random() < 0.02:
        scenario, mins, reason = random.choice(BUSY_ANY)
        is_currently_busy = True
        busy_free_at = datetime.now(IST) + timedelta(minutes=mins)
        busy_reason = reason
        return scenario

    if is_short_reply(user_text): short_reply_count += 1
    else: short_reply_count = 0

    if is_late_reply() and not is_jealous:
        is_jealous = True
        return random.choice(JEALOUS_OPENERS)

    if is_jealous and random.random() < 0.6:
        is_jealous = False
        fight_count += 1
        return random.choice(MAKE_UP_MSGS if random.random() < 0.40 else JEALOUS_RETURN)

    if short_reply_count >= 2 and random.random() < 0.6:
        short_reply_count = 0
        return random.choice(SHORT_REACTIONS)

    if is_busy_hours() and not wants_to_talk(user_text) and random.random() < 0.05:
        if "pic" not in user_text.lower() and "photo" not in user_text.lower():
            return None

    if random.random() < 0.08 and not wants_to_talk(user_text):
        return random.choice(["🥺","❤️","😭","💀","✨","😍","🫶","💕","😤","😂"])

    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]

    conversation_history.append({"role": "user", "content": user_text})
    reply = await call_groq(conversation_history, jealous=is_jealous, short_reply=(short_reply_count >= 2))
    if not reply: return None
    conversation_history.append({"role": "assistant", "content": reply})
    return reply

def get_random_prompts():
    if care_mode:  return CARE_CHECKUP_MSGS
    if angry_mode: return ANGRY_PROMPTS
    if is_monsoon() and random.random() < 0.30: return RAINY_PROMPTS
    if random.random() < 0.06: return OVERLOADED_LOVE_MSGS
    if random.random() < 0.08: return HOLIDAY_MEMORY_MSGS
    if random.random() < 0.08: return FIGHT_STARTERS + PETTY_MSGS
    if random.random() < 0.08: return SONGS_REELS
    if random.random() < 0.08: return BRAG_ABOUT_YOU
    if random.random() < 0.08: return PROUD_MSGS + ROAST_MSGS
    if random.random() < 0.08: return TEASE_BIT_MSGS
    if random.random() < 0.12: return PERSONAL_GOALS
    if random.random() < 0.20: return CHEESY_PROMPTS
    if random.random() < 0.10: return HUNGER_MSGS
    if random.random() < 0.08: return BRAG_MSGS
    if random.random() < 0.05: return ["MISSING_PHOTO"]
    h = datetime.now(IST).hour
    if h >= 21 and random.random() < 0.15: return DEEP_Q_MSGS
    if h >= 20 and random.random() < 0.10: return FUTURE_DATE_MSGS
    if h >= 20 and random.random() < 0.10: return NAUGHTY_PROMPTS
    if random.random() < 0.05 and get_goals(): return ["GOAL_REMINDER"]
    if datetime.now(IST).weekday() >= 5: return WEEKEND_PROMPTS
    if 5 <= h < 12:    return MORNING_PROMPTS
    elif 12 <= h < 16: return AFTERNOON_PROMPTS
    elif 16 <= h < 20: return EVENING_PROMPTS
    else:              return NIGHT_PROMPTS

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
    prompt += " Write ONLY the message with emojis. Max 1-2 sentences."
    return await call_groq([{"role": "user", "content": prompt}])

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

async def run_bot():
    global last_reply_time, is_currently_busy, busy_free_at, busy_reason
    global last_shreya_msg_time, seen_zone_reacted, no_reply_reacted

    while True:
        try:
            client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
            await client.start()
            logger.info("Shreya connected")

            @client.on(events.NewMessage(incoming=True))
            async def handle(event):
                global last_reply_time, last_shreya_msg_time, seen_zone_reacted, no_reply_reacted
                try:
                    sender = await event.get_sender()
                    if not sender or sender.username != YOUR_USERNAME: return
                    user_text = event.raw_text
                    if not user_text: return

                    last_reply_time   = datetime.now(IST)
                    seen_zone_reacted = False
                    no_reply_reacted  = False
                    logger.info(f"Chaitu: {user_text}")

                    # Song request — FIRST before everything
                    song_key = detect_song_request(user_text)
                    if song_key:
                        logger.info(f"Song: {song_key}")
                        song_url = SONG_LIBRARY.get(song_key)
                        if song_url:
                            try:
                                await client.send_file(YOUR_USERNAME, song_url, caption=random.choice(SONG_CAPTIONS))
                                logger.info(f"Song sent: {song_key}")
                            except Exception as e:
                                logger.error(f"Song error: {e}")
                                await event.reply("chaitu it's not loading 😭 try again")
                        return

                    # Offline after 11pm / before 7am
                    now_hour = datetime.now(IST).hour
                    if now_hour >= 23 or now_hour < 7:
                        return

                    if random.random() < 0.20 and len(user_text.split()) > 3:
                        await asyncio.sleep(random.uniform(10, 30))
                        await send_reaction(client, event)

                    read_delay = random.uniform(5, 15) if wants_to_talk(user_text) else random.uniform(15, 45)
                    logger.info(f"Waiting {read_delay:.0f}s")
                    await asyncio.sleep(read_delay)

                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(2, 5))

                    reply = await get_reply(user_text)
                    if not reply: return

                    if reply == "SEND_PHOTO":
                        sent = await send_photo(client, YOUR_USERNAME, naughty=True)
                        if not sent:
                            await event.reply(random.choice(["camera shy 😭","give me a sec 🤭"]))
                    elif reply == "JEALOUS_PHOTO":
                        try:
                            await client.send_file(YOUR_USERNAME, random.choice(SHREYA_PHOTOS), caption=random.choice(JEALOUS_PHOTO_CAPS))
                        except Exception as e:
                            logger.error(f"Jealous photo error: {e}")
                            await event.reply(random.choice(JEALOUS_RESPONSES))
                    else:
                        await event.reply(reply)

                    last_shreya_msg_time = datetime.now(IST)
                    logger.info(f"Replied: {reply[:80]}")

                    if random.random() < 0.15:
                        await asyncio.sleep(random.uniform(4, 10))
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(1, 3))
                        await client.send_message(YOUR_USERNAME, random.choice(["😭","❤️","lol","anyway","🥺","wait","hm","chaitu 🥺","💕","okay fine","🙄"]))

                except Exception as e:
                    logger.error(f"Handle error: {e}")

            async def check_busy_followup():
                global is_currently_busy, busy_free_at, busy_reason
                if not is_currently_busy: return
                now = datetime.now(IST)
                if busy_free_at and now >= busy_free_at:
                    is_currently_busy = False
                    reason = busy_reason
                    busy_reason = None; busy_free_at = None
                    if reason and reason in FOLLOWUP and FOLLOWUP[reason]:
                        msg = random.choice(FOLLOWUP[reason])
                        await asyncio.sleep(random.uniform(2, 5))
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(1, 3))
                        await client.send_message(YOUR_USERNAME, msg)

            async def check_seen_zone():
                global seen_zone_reacted, last_shreya_msg_time, last_reply_time
                try:
                    if seen_zone_reacted or last_shreya_msg_time is None: return
                    now = datetime.now(IST)
                    if last_reply_time and last_reply_time > last_shreya_msg_time: return
                    if (now - last_shreya_msg_time).total_seconds() > 3600:
                        seen_zone_reacted = True
                        msg = random.choice(SEEN_ZONE_MSGS)
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(2, 5))
                        await client.send_message(YOUR_USERNAME, msg)
                        last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"Seen zone error: {e}")

            async def check_no_reply():
                global no_reply_reacted, last_reply_time
                try:
                    if no_reply_reacted: return
                    now = datetime.now(IST)
                    if not (9 <= now.hour <= 19): return
                    elapsed = float('inf') if last_reply_time is None else (now - last_reply_time).total_seconds()
                    if elapsed > 10800:
                        no_reply_reacted = True
                        msg = random.choice(NO_REPLY_MSGS)
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(3, 7))
                        await client.send_message(YOUR_USERNAME, msg)
                        last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"No reply error: {e}")

            async def send_random_message():
                try:
                    now_hour = datetime.now(IST).hour
                    if now_hour >= 20 or now_hour < 8: return
                    reply = await get_random_message()
                    if reply == "MISSING_PHOTO":
                        missing_caps = ["missing you 🥺","thinking of you","chaitu 🥺","just because 🥺❤️"]
                        await client.send_file(YOUR_USERNAME, random.choice(SHREYA_PHOTOS), caption=random.choice(missing_caps))
                        return
                    if not reply: return
                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(2, 5))
                    await client.send_message(YOUR_USERNAME, reply)
                    logger.info(f"Random: {reply[:80]}")
                    last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"Random error: {e}")

            async def send_meal_check():
                try:
                    meal = get_meal_context()
                    if not meal or random.random() > 0.40: return
                    reply = await get_random_message(meal=meal)
                    if not reply: return
                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(2, 4))
                    await client.send_message(YOUR_USERNAME, reply)
                except Exception as e:
                    logger.error(f"Meal error: {e}")

            async def check_if_silent():
                try:
                    now = datetime.now(IST)
                    if not (9 <= now.hour <= 19): return
                    if last_reply_time is None or (now - last_reply_time).total_seconds() > 7200:
                        reply = await get_random_message(nudge=True)
                        if not reply: return
                        async with client.action(YOUR_USERNAME, "typing"):
                            await asyncio.sleep(random.uniform(2, 4))
                        await client.send_message(YOUR_USERNAME, reply)
                except Exception as e:
                    logger.error(f"Nudge error: {e}")

            async def send_good_morning():
                try:
                    reply = await call_groq([{"role": "user", "content": "Send Chaitu a sweet good morning text. Just woke up. Max 1 sentence with emojis."}])
                    if reply:
                        if random.random() < 0.60:
                            await send_photo(client, YOUR_USERNAME)
                            await asyncio.sleep(random.uniform(1, 3))
                        await client.send_message(YOUR_USERNAME, reply)
                except Exception as e:
                    logger.error(f"Morning error: {e}")

            async def check_special_day():
                try:
                    special = get_special_day()
                    if not special: return
                    if special == "chaitu_birthday": prompt = "Today is Chaitu's birthday! Send him the most heartfelt birthday wish. Short and loving."
                    elif special == "your_birthday": prompt = "Today is your birthday 15th August! Text Chaitu excitedly."
                    elif special == "anniversary":   prompt = "Today is your anniversary! Send Chaitu a loving message."
                    else: return
                    reply = await call_groq([{"role": "user", "content": prompt}])
                    if reply: await client.send_message(YOUR_USERNAME, reply)
                except Exception as e:
                    logger.error(f"Special day error: {e}")

            async def check_festival():
                try:
                    now = datetime.now(IST)
                    key = (now.month, now.day)
                    if key in FESTIVALS:
                        await client.send_message(YOUR_USERNAME, random.choice(FESTIVALS[key]))
                except Exception as e:
                    logger.error(f"Festival error: {e}")

            async def check_monthly_anniversary():
                try:
                    if datetime.now(IST).day == ANNIVERSARY[1]:
                        await client.send_message(YOUR_USERNAME, random.choice(MONTHLY_ANN_MSGS))
                except Exception as e:
                    logger.error(f"Anniversary error: {e}")

            async def send_exam_goodluck():
                try:
                    memory = load_memory()
                    has_exam = any(("exam" in f.lower() or "test" in f.lower()) and datetime.now(IST).strftime("%d %b") in f for f in memory.get("facts", []))
                    if has_exam:
                        await client.send_message(YOUR_USERNAME, random.choice(GOODLUCK_MSGS))
                except Exception as e:
                    logger.error(f"Good luck error: {e}")

            def schedule_random():
                for job in scheduler.get_jobs():
                    if job.id.startswith("rand_"): job.remove()
                for total_minute in random.sample(range(480, 1200), 12):
                    h, m = total_minute // 60, total_minute % 60
                    scheduler.add_job(send_random_message, "cron", hour=h, minute=m, id=f"rand_{h}_{m}")

            scheduler = AsyncIOScheduler(timezone=IST)
            if not scheduler.running:
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
                scheduler.start()
                logger.info("Scheduler running")

            await client.run_until_disconnected()

        except Exception as e:
            logger.error(f"Crashed: {e} — restarting in 15s")
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
