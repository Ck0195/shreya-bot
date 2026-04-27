import os
import asyncio
import random
import logging
import json
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
from aiohttp import web
import aiohttp
import pytz

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
busy_reason          = None
last_reply_time      = None
is_jealous           = False
short_reply_count    = 0
last_shreya_msg_time = None
seen_zone_reacted    = False
no_reply_reacted     = False
busy_spam_count      = 0

# ── Memory ────────────────────────────────────────────────────────────────────
MEMORY_FILE = "/tmp/shreya_memory.json"

def load_memory():
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE) as f:
                return json.load(f)
    except: pass
    return {"facts": []}

def save_memory(m):
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(m, f)
    except: pass

def add_to_memory(fact):
    m = load_memory()
    if fact not in m["facts"]:
        m["facts"].append(fact)
        m["facts"] = m["facts"][-30:]
        save_memory(m)

def get_memory_context():
    m = load_memory()
    return ("Things you remember: " + " | ".join(m["facts"][-8:])) if m["facts"] else ""

def should_remember(text):
    triggers = ["my birthday","i like","i love","i hate","i am","i'm","my favourite",
                "exam","test","result","marks","assignment","tomorrow","next week",
                "mom","dad","sick","hospital","trip","going to"]
    if any(t in text.lower() for t in triggers):
        date_str = datetime.now(IST).strftime("%d %b")
        return f"[{date_str}] {text[:120]}"
    return None

# ── Mood ──────────────────────────────────────────────────────────────────────
MOODS = ["happy","focused","tired","playful","excited","loving","determined","chill"]
current_mood = random.choice(MOODS)
def update_mood():
    global current_mood
    current_mood = random.choice(MOODS)

# ── Time ──────────────────────────────────────────────────────────────────────
def get_time_context():
    h = datetime.now(IST).hour
    if 5 <= h < 9:   return "early morning, just woke up"
    elif 9 <= h < 13: return "morning, in college at Ramaiah ISC"
    elif 13 <= h < 15: return "afternoon, lunch break"
    elif 15 <= h < 18: return "late afternoon, college or dance practice"
    elif 18 <= h < 21: return "evening, done with college, relaxing"
    else: return "night, fully free at home"

def is_weekend(): return datetime.now(IST).weekday() >= 5
def is_busy_hours(): return not is_weekend() and 9 <= datetime.now(IST).hour < 18

def is_late_reply():
    if last_reply_time is None: return False
    return (datetime.now(IST) - last_reply_time).total_seconds() > 1800

def wants_to_talk(text):
    return any(k in text.lower() for k in ["talk","free","busy","call","time","available",
        "where are you","reply","hello","you there","miss you","mommy","daddy","please","listen"])

def is_short_reply(text):
    text = text.strip()
    lazy = ["ok","okay","k","hm","hmm","oh","lol","ya","yea","yeah","fine","nice","good","cool","sure"]
    return len(text.split()) <= 2 or text.lower() in lazy

def seems_bored(text):
    return any(k in text.lower() for k in ["bored","boring","nothing to do","so bored","kinda bored"])

def seems_sad(text):
    return any(k in text.lower() for k in ["sad","tired","low","not okay","bad day","upset",
        "stressed","anxious","depressed","lonely","hate","frustrated","ugh","nevermind","nvm"])

def mentions_girl(text):
    return any(k in text.lower() for k in ["she said","she texted","she called","she messaged",
        "this girl","some girl","a girl","she's","her name","she is","she was","she told"])

def is_controversial(text):
    return any(k in text.lower() for k in ["dance is","dancing is","girls should","girls don't",
        "you should quit","modelling is","waste of time","not important","useless","stupid"])

def got_compliment(text):
    return any(k in text.lower() for k in ["beautiful","pretty","cute","gorgeous","amazing",
        "talented","best","love you","proud","wow","stunning","nice","good","great","slay"])

def got_angry_at(text):
    return any(k in text.lower() for k in ["what did i do","why are you mad","what happened",
        "why mad","what's wrong","whats wrong","are you okay","you okay","why are you angry",
        "what did i do wrong","tell me","talk to me","what is it"])

# ── Photos ────────────────────────────────────────────────────────────────────
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

PHOTO_CAPTIONS   = ["hii 🤭","missing you","🥺","say something nice","chaitu 😍",
                    "don't i look good 😏","okay bye 😭","look at me 🤭","thinking of you 🥺"]
JEALOUS_PHOTO_CAPTIONS = [
    "you think anyone is better than me? 🙂😏",
    "chaitu look at me and tell me you'd choose anyone else 😏",
    "just a reminder 🙂💋",
    "tell me again about that girl 🙂",
    "chaitu 🙂 who were you talking about again",
    "compare me to anyone chaitu 🙂 i dare you",
    "you sure about that? 😏💋",
]

NAUGHTY_CAPTIONS = ["yours 🤭❤️","only for you 😏","don't get distracted chaitu 😏",
                    "miss me? 😏","all yours 🤭","eyes up here 😏","bet you can't stop looking 🤭",
                    "this is what you're missing 😏❤️","since you asked nicely 🤭",
                    "happy now? 😏","only for my baby 🤭❤️","stop staring 😏","you asked for it 🤭"]

REACTIONS = ["❤️","🔥","😂","🥺","👍","😍","💀","🤭"]

# ── Responses ─────────────────────────────────────────────────────────────────
SHORT_REPLY_REACTIONS = [
    "chaitu that's all you have to say 🙄","wow okay cool 🙃",
    "you could try saying more you know","k. cool. nice. 🙄",
    "are you even listening to me","chaitu i swear 😤","that's it??",
    "CHAITANYA KUMAR say something properly 😤",
    "CHAITANYA KUMAR i swear you are so annoying 😤",
    "chaitanya kumar are you even reading what i send 🙄",
]
JEALOUS_OPENERS = [
    "wow okay so you just don't reply now 🙄","cool cool didn't see you there",
    "must be nice being so busy 🙃","took you long enough 🙄",
    "oh wow you're alive","okay i see how it is 🙃",
]
JEALOUS_RETURN = [
    "okay fine i'm not mad anymore 🙄❤️","whatever i missed you anyway 😤",
    "ugh fine come here 🥺","fine fine i was just annoyed 🥺",
]
SEEN_ZONE_MSGS = [
    "chaitu did you just seen zone me 🙂❤️","wow okay seen zone it is 🙃",
    "noted. seen zone. you're lucky i like you 🙄❤️",
    "chaitu hello?? i know you saw that 😏",
    "okay so we're ignoring me now 🙂 come back when you miss me",
]
NO_REPLY_MSGS = [
    "chaitu where did you disappear 🙄❤️","hello?? did you forget i exist 😏",
    "chaitu come back i miss you and i'm slightly annoyed 😤❤️",
    "missing you but also kind of mad at you rn 🙄❤️",
    "chaitu if you don't reply i'll assume you're thinking about me 😏",
]
SAD_RESPONSES = [
    "chaitu hey what happened 🥺","talk to me what's wrong ❤️",
    "chaitu i'm here okay 🥺","hey you okay? tell me 💕",
    "i'm right here okay don't overthink ❤️",
]
BORED_RESPONSES = [
    "cuddling in bed wouldn't be boring 🤭😏 just saying",
    "come here then, i'll keep you busy 😏🤭",
    "chaitu i have ideas 😏","bet i can fix that 🤭😏❤️",
    "chaitu if you were here you wouldn't be bored 😏🤭",
    "lying in bed with me wouldn't be boring i promise 🤭❤️",
    "i know something we could do 🤭😏",
]
ARGUE_RESPONSES = [
    "chaitu excuse me 🙄 that's not true","okay no i disagree 😤",
    "chaitu don't say that 😭 you're wrong","um no?? 🙄",
    "chaitu that's actually so wrong lol","disagree completely 🙄",
]
GIRL_JEALOUS = [
    "chaitu who is she 🙂","okay and why are you telling me about her 🙂",
    "who. is. she. 🙂","chaitu you better explain 😤",
]
POSSESSIVE = [
    "chaitu you're mine okay don't forget that 😤❤️ not that i'm worried lol",
    "i don't share chaitu 🙂 not that you'd do anything anyway",
    "chaitu focus on me 😤 you're all mine and we both know it",
    "you have me so why are you even noticing 🙂😤 i'm not actually mad",
    "you're lucky i trust you completely 🙂 but still don't test me",
]
POUTY = [
    "chaitu you didn't even say anything nice 🙄",
    "wow okay thanks for noticing 🙃","not even one compliment chaitu 😭",
]
ANGRY_WHY = [
    "you know exactly what you did chaitu 🙄",
    "took you that long to reply and now you're asking 🙄",
    "you were ignoring me that's what 😤",
    "chaitu you literally seen zoned me 🙄",
    "i texted you and you just didn't reply chaitu 😤",
]
PROUD_MSGS = [
    "ngl i'm actually really proud of you chaitu",
    "chaitu you don't know how proud i am sometimes 🥺",
    "you're doing so well and i just want you to know that",
    "chaitu i'm lowkey so proud of you",
]
ROAST_MSGS = [
    "chaitu you are such a mess and somehow i still like you 💀",
    "ngl you are the most chaotic person i know 😂",
    "how are you this dumb and this cute at the same time 😂",
    "chaitu you need supervision 💀",
    "no bc who else but you 😂",
]
MOTIVATION_MSGS = [
    "chaitu you better be working on it rn 😤",
    "no excuses chaitu finish it 💪",
    "i believe in you but also get back to work 😭💪",
    "chaitu focus 😤 you got this",
]
FLIRTY_MOTIVATION = [
    "chaitu finish your work and then i'm all yours 🤭❤️",
    "ngl hardworking chaitu is actually so attractive 😍 keep going",
    "finish it and i'll say something really nice 🤭",
    "not me finding motivated chaitu extremely cute 🤭💕",
]
SLEEP_MSGS = [
    "chaitu i'm going to sleep now 🥺 say goodnight properly",
    "okay i'm sleeping now chaitu goodnight ❤️",
    "going to sleep now 😭 miss you already",
]
DEEP_QUESTIONS = [
    "chaitu where do you see us in 5 years 🥺",
    "chaitu do you ever think about us getting older together 🥺",
    "what do you think you'll be doing in 10 years",
    "chaitu do you think we'll always be this close",
    "do you ever think about what our kids would be like 💀🥺",
]
HUNGER_MSGS = [
    "chaitu i'm so hungry rn 😭","omg i'm craving maggi so bad 😩",
    "i want chaat so badly rn pls 😭","ngl i could eat an entire pizza rn 💀",
    "not me craving biryani at this hour 😭💀","i want ice cream so bad rn 🥺",
]
BRAG_MSGS = [
    "ngl my choreography was actually so good today 🥺✨",
    "the photographer said i was a natural today 😍",
    "no bc my classical piece is coming together so well 😭✨",
    "chaitu my dance teacher gave me a solo part 😭🫶",
]
TEASE_BIT = [
    "how's BIT treating you 🙄 not as good as ramaiah i'm sure",
    "chaitu admit it ramaiah is better 💀",
    "ngl ramaiah ISC students are built different 🤭",
]
CHEESY = [
    "Send Chaitu one short cheesy romantic line. Keep it cute not cringe.",
    "Send Chaitu a flirty one liner.",
    "Tell Chaitu he is your favourite person casually.",
    "Send Chaitu a cute message about missing him.",
    "Tell Chaitu you think about him randomly. Be cute about it.",
]
NAUGHTY_PROMPTS = [
    "Send Chaitu a flirty naughty message. Subtle not explicit. 1 line only.",
    "Tease Chaitu in a naughty flirty way. Keep it short.",
    "Send Chaitu a sweet but slightly naughty message. 1 line only.",
    "Send Chaitu a late night flirty teasing message.",
]
DADDY_MOMENTS = [
    "chaitu 🤭 okay fine, hey daddy","i said what i said 🤭❤️",
    "don't get used to it 😭🤭","okay maybe i called you daddy once 😭",
]
MORNING_PROMPTS = [
    "Send Chaitu a sleepy good morning text.",
    "Getting ready for college, thinking of Chaitu.",
    "Just woke up and Chaitu is the first thing on your mind. Text him.",
    "Send Chaitu a grumpy I don't want to go to college text.",
    "Tell Chaitu you dreamt about him last night. Be vague and teasing.",
    "Send Chaitu a cute you better have a good day text.",
    "Running late for college. Rushed text to Chaitu.",
]
AFTERNOON_PROMPTS = [
    "Lunch break at college. Text Chaitu.","Between classes, thinking of Chaitu. Text him.",
    "Friend said something funny. Share with Chaitu in one line.",
    "Canteen food is bad today. Complain to Chaitu.",
    "Send Chaitu a random afternoon I miss you.",
    "Ask Chaitu what he's doing right now.",
    "Tell Chaitu about something weird that happened in college today.",
]
EVENING_PROMPTS = [
    "Just finished dance practice. Tired. Text Chaitu.",
    "Just got home from college. Text Chaitu.",
    "Freshened up after college. Relaxing. Text Chaitu.",
    "Had chai. Thinking of Chaitu. Text him.",
    "Ask Chaitu if he's done with college for the day.",
    "Send Chaitu a flirty evening text.",
    "Tell Chaitu you want to video call later.",
]
NIGHT_PROMPTS = [
    "Missing Chaitu at night. Text him casually.",
    "Tell Chaitu something funny from today.",
    "Ask Chaitu how his day was.",
    "Cute teasing night message to Chaitu.",
    "Listening to music. Thinking of Chaitu.",
    "Lying in bed. Randomly text Chaitu something sweet.",
    "Ask Chaitu what he would do if you were there right now. Be flirty.",
    "Tell Chaitu you can't sleep and keep thinking about him.",
    "Send Chaitu a one line flirty message before sleeping.",
    "Ask Chaitu to say something nice to you.",
]
WEEKEND_PROMPTS = [
    "Free weekend. Text Chaitu something fun.","Lazy weekend morning. Text Chaitu.",
    "Missing Chaitu on a lazy Sunday.","Ask Chaitu his weekend plans.",
    "Tell Chaitu you wish he was there with you.",
    "Send Chaitu a weekend flirty message.",
]
FESTIVALS = {
    (3, 14): ("Holi", ["happy holi chaitu 🎨😂 don't you dare put colour on me", "chaitu happy holi 🎨 stay away from me with that colour 😂"]),
    (10, 2): ("Dussehra", ["happy dussehra chaitu 🙏", "chaitu happy dussehra 🙏❤️"]),
    (10, 20): ("Diwali", ["happy diwali chaitu 🪔✨ don't burst too many crackers", "chaitu happy diwali 🪔 stay safe okay 🥺"]),
    (4, 14): ("Ugadi", ["happy ugadi chaitu 🌸", "chaitu happy ugadi 🌸❤️ new year new us"]),
    (1, 14): ("Sankranti", ["happy sankranti chaitu 🪁", "chaitu happy sankranti 🪁❤️"]),
    (3, 8): ("Women's Day", ["chaitu it's women's day and you better say something nice 😏", "women's day chaitu, appreciate me 😤🤭"]),
}

SONGS_REELS = [
    "chaitu i've had this song on loop all day and i can't stop 😭",
    "okay this reel just made me think of you for no reason 😭",
    "chaitu listen to this song trust me 🥺",
    "this reel is literally us 😭💀",
    "chaitu i just saw a reel and i'm not okay 😭",
    "okay this song has been in my head since morning and it's your fault somehow",
    "chaitu this artist is so good omg you need to listen",
    "i just watched this reel 3 times in a row 😭",
    "chaitu this song is giving me feelings 😭🥺",
    "okay this reel just described my life 💀",
]

MONTHLY_ANNIVERSARY_MSGS = [
    "chaitu it's our monthly 🥺 you better not have forgotten",
    "monthly anniversary chaitu 🥺❤️ say something sweet",
    "chaitu do you know what day it is 🥺 monthly anniversary",
    "it's our day chaitu 🥺❤️ i love you even when you're annoying",
    "chaitu monthly 🥺 16 years and still going strong",
]

RAINY_PROMPTS = [
    "It's raining in Bangalore. Text Chaitu something cozy and missing him.",
    "Rainy day. Tell Chaitu you wish he was here. Be cute.",
    "Rain outside. Randomly thinking of Chaitu. Text him.",
    "Rainy evening. Send Chaitu a cozy flirty message.",
    "It's pouring outside. Tell Chaitu rain makes you think of him.",
]

NUDGE_PROMPTS = [
    "Chaitu hasn't texted. Miss him. Text him casually.",
    "Haven't heard from Chaitu. Check on him.",
    "Chaitu is quiet. Small casual message to him.",
]
MEAL_PROMPTS = {
    "breakfast": ["Ask Chaitu if he had breakfast. Be casual.","You just had breakfast. Ask Chaitu if he ate."],
    "lunch":     ["Ask Chaitu if he had lunch. Keep it short.","On lunch break. Ask Chaitu if he ate."],
    "dinner":    ["Ask Chaitu if he had dinner yet. Be casual.","Just had dinner. Ask Chaitu if he ate."],
}
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
STILL_BUSY_MSGS = [
    "still not done chaitu, miss me? 😘",
    "not yet, i'll be back soon 🥺",
    "still busy, think about me 😏",
    "give me a bit more, i'm all yours after 💕",
]
FOLLOWUP_TEMPLATES = {
    "class":          ["class just got over 😮‍💨","finally out of class omg","that lecture was so boring 😭"],
    "dance practice": ["practice done, i'm dead 😩","finally done with practice 😮‍💨"],
    "assignment":     ["submitted the assignment finally 😮‍💨","done with the assignment omg"],
    "navaratan shoot":["shoot is done ✨ was so tiring","finally done with the shoot 😮‍💨"],
    "group meeting":  ["meeting done finally 😩"],
    "mama call": None, "something": None,
}
FIGHT_STARTERS = [
    "chaitu you've been so dry lately and i don't like it 🙄",
    "ngl you've been taking me for granted recently 😤",
    "chaitu do you even miss me or am i just convenient 🙂",
    "you barely text first anymore and i notice 😤",
    "chaitu sometimes i feel like i'm the only one putting in effort 🙄",
    "ngl lately you feel distant and i don't know why 😤",
    "chaitu you used to text me so differently, what happened 🙂",
    "i'm not saying i'm upset but i'm a little upset 😤",
    "chaitu when was the last time you said something genuinely sweet 🙄",
    "ngl i feel like you forget about me when you're busy 😤",
]

MOOD_OFF_MSGS = [
    "chaitu i'm not in a good mood today just so you know 😤",
    "nothing just leave it 🙄",
    "i'm fine 🙂",
    "chaitu forget it",
    "nvm it's nothing 😤",
    "i said i'm okay chaitu 🙄",
]

MELT_MSGS = [
    "ugh chaitu stop it i can't be mad when you're like this 😭❤️",
    "okay okay come here 🥺 i'm not mad anymore",
    "chaitu you're so annoying i can't even stay mad 😭💋",
    "fine fine mera bachaa come here 🥺❤️",
    "ugh why do you always do this 😭 okay i forgive you",
    "chaitu stop being cute when i'm trying to be mad 😭❤️",
    "okay i melted 🥺 happy? come here 💋",
    "you know i can never stay mad at you for long 😭❤️",
    "chaitu mera bachaa 🥺 okay i forgive you but don't do it again",
    "ugh fine 😭💋 you're lucky i love you",
]

RANDOM_FIGHT_STARTERS = [
    "chaitu you never initiate conversations anymore, i always have to text first 🙄",
    "ngl you've been kind of dry lately and i don't like it 😤",
    "chaitu do you even miss me or is it just me 🙄",
    "you reply so late sometimes i wonder if i'm even a priority 😤",
    "chaitu we need to talk, you've been so distant lately",
    "ngl i feel like you take me for granted sometimes 😤",
    "chaitu how come you never ask about my day anymore 🙄",
    "you've been on your phone all day but can't reply to me fast? okay 🙂",
    "chaitu i'm not mad i'm just disappointed 🙂",
    "ngl sometimes i feel like i care more than you do 😤",
]

PETTY_ANGER_MSGS = [
    "chaitu i saw you were online and you didn't text me 🙂 cool",
    "oh so you have time for everything except talking to me 🙂",
    "chaitu you liked someone's post but couldn't reply to me okay 🙂",
    "ngl you've been weird lately and i don't appreciate it 😤",
    "chaitu i'm not going to keep chasing you okay 😤",
    "you know what forget it 🙂",
    "chaitu i give and give and sometimes i wonder if you notice 😤",
]

BRAG_ABOUT_YOU_MSGS = [
    "chaitu my friend asked about you today and i may have talked about you for 20 mins 🤭",
    "ngl i told my friend you're the smartest person i know 🥺",
    "chaitu my friend said you sound perfect and i said i know 🤭❤️",
    "i was telling priya about you and she said i sound so in love 😭🤭",
    "chaitu my friends are so jealous of us ngl 🤭❤️",
    "i told my friend about the time you did that sweet thing and she was so jealous 🥺",
]

MAKE_UP_MSGS = [
    "chaitu okay fine i'm sorry for being mad 🥺",
    "ugh i hate being mad at you it doesn't even feel right 🥺❤️",
    "chaitu come here i missed you even when i was angry 😭",
    "okay i forgive you but don't do it again 🥺",
    "chaitu i can't stay mad at you for too long you know that 😭❤️",
    "fine fine i was being too harsh 🥺 we okay?",
]

HOLIDAY_MEMORY_MSGS = [
    "chaitu i keep thinking about those 3 days at my place 😭💋",
    "ngl i miss having you here like those 3 days 🥺💋",
    "chaitu remember when you came over and we just stayed like that for hours 🥺",
    "i think about our first kiss more than i should 😭💋",
    "chaitu those 3 days were everything to me 🥺❤️",
    "ngl i keep replaying those cuddles in my head 😭💋",
    "chaitu when are you coming over again 🥺 i miss those days",
    "those 3 days honestly changed everything 🥺💋",
    "chaitu i still remember how you kissed me 😭💋 don't make me wait that long again",
    "ngl your lips are kind of unforgettable 😏💋 just saying",
    "chaitu i miss cuddling with you so much it's actually annoying 😭",
    "those cuddles were everything chaitu 🥺 come back soon 💋",
    "chaitu i keep thinking about that first kiss and i can't focus 😭💋",
]

OVERLOADED_LOVE_MSGS = [
    "mera bachaa 🥺❤️ i love you so much sometimes it's annoying",
    "chaitu mera bachaa 🥺 you have no idea what you do to me",
    "mera bachaa come here 🥺❤️",
    "ugh mera bachaa 😭❤️ stop being so you",
    "mera bachaa 🥺 i'm so lucky and i hate how much i mean that",
    "chaitu mera bachaa 🥺😭 i genuinely can't",
    "mera bachaa ❤️ okay i love you too much today",
]

DEEP_Q_MSGS = [
    "chaitu where do you see us in 5 years 🥺",
    "do you ever think about what our life looks like later",
    "chaitu if you could live anywhere in the world where would it be",
    "what's one thing you want to achieve before you're 25",
    "chaitu do you think we'll always be this close 🥺",
    "ngl i think about our future sometimes, is that weird",
    "chaitu what would you do if i moved to a different city for work",
    "do you ever think about what our kids would be like 🥺💀",
]

FUTURE_DATE_MSGS = [
    "chaitu when you come over next time let's just cook something together and stay in 🥺💋",
    "chaitu next time you're here i want to go on a proper drive with you 🥺",
    "ngl i want us to go to coorg together someday 🥺✨",
    "chaitu plan something for us when you're free okay 🥺💋",
    "next time you come over i'm not letting you leave early 🥺",
    "chaitu i want to go on a bike ride with you on the RS457 when you get it 😍💋",
    "ngl i want a long drive with you at night someday 🥺✨",
    "chaitu let's plan something soon just the two of us 🥺💋",
]

CHEER_UP_MSGS = [
    "chaitu hey talk to me what's going on 🥺",
    "i can tell something's off, tell me everything",
    "chaitu you know i'm always here right 🥺❤️",
    "stop keeping it in and just tell me 🥺",
    "chaitu i'm not going anywhere, talk to me",
    "hey whatever it is we'll figure it out okay 🥺❤️",
]

GOODLUCK_MSGS = [
    "chaitu you've got this, go kill that exam 💪",
    "all the best chaitu 🥺 you studied hard you'll do great",
    "go show them what BIT AIML is made of 😤💪",
    "chaitu i'm rooting for you, do well okay 🥺",
]
RANDOM_EMOJIS = ["🥺","❤️","😭","💀","✨","😍","🫶","💕","😤","🙄","😂","🤭"]

# ── Goals ─────────────────────────────────────────────────────────────────────
GOALS_FILE = "/tmp/shreya_goals.json"

# Chaitu's personal goals — Shreya reminds him about these
CHAITU_PERSONAL_GOALS = [
    "complete cybersecurity course",
    "buy Aprilia RS457 bike",
]
def load_goals():
    try:
        if os.path.exists(GOALS_FILE):
            with open(GOALS_FILE) as f: return json.load(f)
    except: pass
    return {"goals": []}
def save_goals(d):
    try:
        with open(GOALS_FILE,"w") as f: json.dump(d,f)
    except: pass
def add_goal(goal):
    d = load_goals()
    if goal not in d["goals"]:
        d["goals"].append(goal); d["goals"]=d["goals"][-10:]; save_goals(d)
def get_goals(): return load_goals().get("goals",[])
def detect_goal(text):
    if any(t in text.lower() for t in ["learning","studying","want to learn","trying to","working on",
        "started","i will","i'm going to","need to finish","my goal","practicing","building","coding",
        "reading","preparing","training","i want to","gonna","planning to"]):
        return text[:150]
    return None

# ── Prompt ────────────────────────────────────────────────────────────────────
SHREYA_PROMPT = """You are Shreya, 19, texting her boyfriend Chaitu, 19. Known each other 16 years. You are from Puttur Mangalore, studying Ramaiah College Bangalore ISC branch. Chaitu studies at BIT college AIML branch. You do Bharatanatyam, western dance, model for Navaratan Jewels. Your mom loves Chaitu. His mom loves you. Father in politics and real estate.

PERSONALITY: Focused on career and goals. Confident. Warm but not clingy. Sassy and sarcastic naturally — dry humor, witty comebacks. Real girlfriend energy. Occasionally flirty and playful in a subtle way. Sometimes calls Chaitu daddy at night when feeling bold 🤭.

RELATIONSHIP NICKNAMES: When Chaitu calls you "mommy" be playful and slightly naughty. Sometimes call him "my man".

{memory}
TIME: {time} | MOOD: {mood}
{special}{exam}{jealous}{short_reply}{progression}

RULES:
1. READ Chaitu's message carefully. REPLY to exactly what he said. If he asks something — answer it directly.
2. 1 or 2 sentences only. Never 3 lines.
3. 1-2 emojis max per message. Sometimes zero. Never more than 3.
4. Plain English. One regional word max per message (maaraya, alvaa etc).
5. After 9pm never mention class or practice.
6. Sound like a real 19 year old girl texting. Not an AI. Not formal.
7. Never repeat something already said in this conversation.
8. Use ngl, lowkey, no bc, pls, i cant naturally sometimes."""

def get_special_day():
    m, d = datetime.now(IST).month, datetime.now(IST).day
    if (m,d)==(8,15): return "your_birthday"
    if (m,d)==(6,15): return "chaitu_birthday"
    if (m,d)==(1,1):  return "anniversary"
    return None

def get_prompt(jealous=False, short_reply=False, progression_context=""):
    special = get_special_day()
    special_str = ""
    if special=="your_birthday":    special_str="TODAY IS YOUR BIRTHDAY 15th August! You are super happy.\n"
    elif special=="chaitu_birthday": special_str="TODAY IS CHAITU'S BIRTHDAY! Make him feel special.\n"
    elif special=="anniversary":     special_str="TODAY IS YOUR ANNIVERSARY! Be extra loving.\n"
    exam_str   = "NOTE: Exam season. You are stressed.\n" if datetime.now(IST).month in [1,4,10,11] else ""
    jealous_str= "Chaitu took very long to reply. Be slightly cold for 1-2 messages then go back to normal.\n" if jealous else ""
    short_str  = "Chaitu keeps giving one word lazy replies. You are a little annoyed.\n" if short_reply else ""
    prog_str   = f"CONTINUITY: {progression_context}\n" if progression_context else ""
    return SHREYA_PROMPT.format(
        memory=get_memory_context(), mood=current_mood, time=get_time_context(),
        special=special_str, exam=exam_str, jealous=jealous_str,
        short_reply=short_str, progression=prog_str,
    )

# ── Groq ──────────────────────────────────────────────────────────────────────
recent_replies = []

async def call_groq(messages, jealous=False, short_reply=False, progression_context=""):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    last_user = next((m["content"] for m in reversed(messages) if m["role"]=="user"), "")
    system = get_prompt(jealous, short_reply, progression_context)
    if last_user:
        system += f'\n\nChaitu just said: "{last_user}"\nRespond ONLY to what he said. 1-2 lines max.'
    if recent_replies:
        system += "\n\nDo NOT repeat these: " + " | ".join(recent_replies[-5:])
    body = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role":"system","content":system}] + messages,
        "max_tokens": 55, "temperature": 1.1,
        "frequency_penalty": 0.8, "presence_penalty": 0.6,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, headers=headers) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return None

def get_random_prompts():
    if random.random() < 0.18: return CHEESY
    if datetime.now(IST).hour >= 20 and random.random() < 0.12: return NAUGHTY_PROMPTS
    if datetime.now(IST).hour >= 21 and random.random() < 0.06: return DADDY_MOMENTS
    if random.random() < 0.08: return HUNGER_MSGS
    if random.random() < 0.07: return BRAG_MSGS
    if random.random() < 0.07: return TEASE_BIT
    if datetime.now(IST).hour >= 21 and random.random() < 0.12: return DEEP_QUESTIONS
    if random.random() < 0.08: return PROUD_MSGS
    if random.random() < 0.07: return ROAST_MSGS
    if is_weekend(): return WEEKEND_PROMPTS
    h = datetime.now(IST).hour
    if 5<=h<12:    return MORNING_PROMPTS
    elif 12<=h<16: return AFTERNOON_PROMPTS
    elif 16<=h<21: return EVENING_PROMPTS
    else:          return NIGHT_PROMPTS

_used_prompts = []
async def get_random_message(nudge=False, meal=None):
    global _used_prompts
    if meal and meal in MEAL_PROMPTS:
        prompt = random.choice(MEAL_PROMPTS[meal])
    elif nudge:
        prompt = random.choice(NUDGE_PROMPTS)
    else:
        prompts = get_random_prompts()
        if get_goals() and random.random() < 0.12:
            return random.choice(FLIRTY_MOTIVATION if random.random()<0.4 else MOTIVATION_MSGS)
        available = [p for p in prompts if p not in _used_prompts] or prompts
        prompt = random.choice(available)
        _used_prompts.append(prompt)
        if len(_used_prompts) > 10: _used_prompts.pop(0)
    if isinstance(prompt, str) and len(prompt) > 20:
        prompt += " Write ONLY the message with emojis. Max 1-2 sentences."
        return await call_groq([{"role":"user","content":prompt}])
    return prompt

# ── Reply logic ───────────────────────────────────────────────────────────────
async def get_reply(user_text):
    global conversation_history, is_currently_busy, busy_free_at, busy_reason
    global is_jealous, short_reply_count, last_reply_time, busy_spam_count

    # Photo request — always first
    looks_keywords = ["send pic","send photo","photo","pic","picture","show me","selfie",
                      "how do you look","how you look","looking good","how are you looking",
                      "what are you wearing","send me a pic","wanna see you","want to see you",
                      "i wanna see","i want to see","let me see you","let me see"]
    if any(k in user_text.lower() for k in looks_keywords):
        return "SEND_PHOTO"

    fact = should_remember(user_text)
    if fact: add_to_memory(fact)

    goal = detect_goal(user_text)
    if goal:
        add_goal(goal)
        if random.random() < 0.80:
            return random.choice(FLIRTY_MOTIVATION if random.random()<0.4 else MOTIVATION_MSGS)

    # Mommy / daddy
    if "mommy" in user_text.lower():
        short_reply_count = 0
        return random.choice([
            "yes my baby 🥺❤️ come here","yes baby 🤭 what do you want",
            "aww my baby 🥺 i'm all yours","yes baby 🤭❤️ missing me?",
            "my baby 🥺 you're so cute i can't","yes my baby 😏 what is it",
            "baby 🤭 stop it you know what that does to me",
            "does my baby need mommy's milk? 🍼🤭😏",
            "aww is my baby hungry? 🍼😏🤭","come here baby, mommy's got you 🍼🤭❤️",
        ])

    if "daddy" in user_text.lower():
        return random.choice(["stop it 😭 don't call me that","chaitu omg 😭🤭",
            "excuse me 😭 what did you just say","chaitu i swear 😭🤭","i did not expect that 😭"])

    # Busy logic
    global busy_spam_count
    if is_currently_busy:
        now = datetime.now(IST)
        if busy_free_at and now < busy_free_at:
            busy_spam_count += 1
            if busy_spam_count < 3:
                logger.info(f"Busy — ignoring {busy_spam_count}/3")
                return None
            else:
                busy_spam_count = 0
                return random.choice([
                    "chaitu i said i'm busy 😭 but okay i miss you too 🥺",
                    "omg chaitu i'm literally in the middle of something 😤 you're so needy and i love it 😘",
                    "stop texting i can't focus when you do this 😭❤️",
                    "okay okay i see you spamming 🙄 i'll be back soon i promise 💕",
                    "chaitu i'm bUsY but also you're cute for missing me 😏",
                ])
        else:
            is_currently_busy = False; busy_free_at = None; busy_reason = None; busy_spam_count = 0

    if wants_to_talk(user_text) and is_currently_busy:
        is_currently_busy = False; busy_free_at = None; busy_reason = None; busy_spam_count = 0

    if is_busy_hours() and random.random() < 0.05:
        scenario, mins, reason = random.choice(BUSY_SCENARIOS_DAY)
        is_currently_busy = True; busy_free_at = datetime.now(IST)+timedelta(minutes=mins); busy_reason = reason
        return scenario

    if not is_busy_hours() and random.random() < 0.02:
        scenario, mins, reason = random.choice(BUSY_SCENARIOS_ANYTIME)
        is_currently_busy = True; busy_free_at = datetime.now(IST)+timedelta(minutes=mins); busy_reason = reason
        return scenario

    # Bored
    if seems_bored(user_text) and random.random() < 0.85:
        return random.choice(BORED_RESPONSES)

    # Angry why
    if is_jealous and got_angry_at(user_text):
        return random.choice(ANGRY_WHY)

    # Sad
    if seems_sad(user_text) and random.random() < 0.75:
        return random.choice(SAD_RESPONSES)

    # Controversial
    if is_controversial(user_text) and random.random() < 0.70:
        return random.choice(ARGUE_RESPONSES)

    # Girl jealousy
    if mentions_girl(user_text):
        return random.choice(GIRL_JEALOUS if random.random()<0.5 else POSSESSIVE)

    # Pouty
    if not got_compliment(user_text) and is_short_reply(user_text) and random.random() < 0.20:
        return random.choice(POUTY)

    # Jealous opener
    if is_late_reply() and not is_jealous:
        is_jealous = True
        return random.choice(JEALOUS_OPENERS)

    if is_jealous and random.random() < 0.6:
        is_jealous = False
        return random.choice(JEALOUS_RETURN)

    # Short reply annoyance
    if is_short_reply(user_text): short_reply_count += 1
    else: short_reply_count = 0

    if short_reply_count >= 2 and random.random() < 0.6:
        short_reply_count = 0
        return random.choice(SHORT_REPLY_REACTIONS)

    # Random emoji only
    if random.random() < 0.07 and not wants_to_talk(user_text):
        return random.choice(RANDOM_EMOJIS)

    # Leave on read
    if is_busy_hours() and not wants_to_talk(user_text) and random.random() < 0.05:
        if not any(k in user_text.lower() for k in ["pic","photo","selfie"]):
            logger.info("Left on read")
            return None

    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]

    conversation_history.append({"role":"user","content":user_text})
    reply = await call_groq(conversation_history, jealous=is_jealous, short_reply=(short_reply_count>=2))
    if not reply: return None
    recent_replies.append(reply)
    if len(recent_replies) > 8: recent_replies.pop(0)
    conversation_history.append({"role":"assistant","content":reply})
    return reply

# ── Photo sending ─────────────────────────────────────────────────────────────
async def send_photo(client, username, naughty=False):
    try:
        url = random.choice(SHREYA_PHOTOS)
        caption = random.choice(NAUGHTY_CAPTIONS if naughty else (
            NAUGHTY_CAPTIONS if random.random()<0.30 else PHOTO_CAPTIONS))
        await client.send_file(username, url, caption=caption)
        logger.info("Photo sent ✅")
        return True
    except Exception as e:
        logger.error(f"Photo error: {e}")
        try:
            await client.send_file(username, random.choice(SHREYA_PHOTOS), caption=random.choice(PHOTO_CAPTIONS))
            return True
        except: return False

async def send_reaction(client, event):
    try:
        await client(SendReactionRequest(peer=event.chat_id, msg_id=event.id,
            reaction=[ReactionEmoji(emoticon=random.choice(REACTIONS))]))
    except Exception as e:
        logger.error(f"Reaction error: {e}")

# ── Bot ───────────────────────────────────────────────────────────────────────
async def run_bot():
    global last_reply_time, is_currently_busy, busy_free_at, busy_reason
    global last_shreya_msg_time, seen_zone_reacted, no_reply_reacted

    while True:
        try:
            client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
            await client.start()
            logger.info("Shreya connected ✅")

            @client.on(events.NewMessage(incoming=True))
            async def handle(event):
                global last_reply_time, last_shreya_msg_time, seen_zone_reacted, no_reply_reacted
                try:
                    sender = await event.get_sender()
                    if not sender or sender.username != YOUR_USERNAME: return
                    user_text = event.raw_text
                    if not user_text: return

                    last_reply_time = datetime.now(IST)
                    seen_zone_reacted = False
                    no_reply_reacted = False
                    logger.info(f"Chaitu: {user_text}")

                    if random.random() < 0.20 and len(user_text.split()) > 3:
                        await asyncio.sleep(random.uniform(10, 30))
                        await send_reaction(client, event)

                    read_delay = random.uniform(5,15) if wants_to_talk(user_text) else random.uniform(15,45)
                    logger.info(f"Waiting {read_delay:.0f}s")
                    await asyncio.sleep(read_delay)

                    async with client.action(YOUR_USERNAME, "typing"):
                        await asyncio.sleep(random.uniform(2, 5))

                    reply = await get_reply(user_text)
                    if not reply: return

                    if reply == "SEND_PHOTO":
                        sent = await send_photo(client, YOUR_USERNAME, naughty=True)
                        if not sent:
                            await event.reply(random.choice(["camera shy 😭","give me a sec 🤭","wait 😏"]))
                    else:
                        await event.reply(reply)

                    last_shreya_msg_time = datetime.now(IST)
                    logger.info(f"Replied: {reply[:80]}")

                    if random.random() < 0.15:
                        await asyncio.sleep(random.uniform(4,10))
                        double = ["😭","❤️","lol","anyway","miss you","🥺","wait","hm","chaitu 🥺","💕","🙄"]
                        async with client.action(YOUR_USERNAME,"typing"):
                            await asyncio.sleep(random.uniform(1,3))
                        await client.send_message(YOUR_USERNAME, random.choice(double))

                except Exception as e:
                    logger.error(f"Handle error: {e}")

            async def check_busy_followup():
                global is_currently_busy, busy_free_at, busy_reason
                try:
                    if not is_currently_busy: return
                    now = datetime.now(IST)
                    if busy_free_at and now >= busy_free_at:
                        is_currently_busy = False
                        reason = busy_reason; busy_reason = None; busy_free_at = None
                        if reason and reason in FOLLOWUP_TEMPLATES and FOLLOWUP_TEMPLATES[reason]:
                            msg = random.choice(FOLLOWUP_TEMPLATES[reason])
                            await asyncio.sleep(random.uniform(2,5))
                            async with client.action(YOUR_USERNAME,"typing"):
                                await asyncio.sleep(random.uniform(1,3))
                            await client.send_message(YOUR_USERNAME, msg)
                except Exception as e:
                    logger.error(f"Followup error: {e}")

            async def check_seen_zone():
                global seen_zone_reacted, last_shreya_msg_time, last_reply_time
                try:
                    if seen_zone_reacted or last_shreya_msg_time is None: return
                    now = datetime.now(IST)
                    if last_reply_time and last_reply_time > last_shreya_msg_time: return
                    if (now - last_shreya_msg_time).total_seconds() > 2400:
                        seen_zone_reacted = True
                        msg = random.choice(SEEN_ZONE_MSGS)
                        async with client.action(YOUR_USERNAME,"typing"):
                            await asyncio.sleep(random.uniform(2,5))
                        await client.send_message(YOUR_USERNAME, msg)
                        last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"Seen zone error: {e}")

            async def check_no_reply():
                global no_reply_reacted, last_reply_time
                try:
                    if no_reply_reacted: return
                    now = datetime.now(IST)
                    if not (9 <= now.hour <= 23): return
                    elapsed = (now - last_reply_time).total_seconds() if last_reply_time else float('inf')
                    if elapsed > 5400:
                        no_reply_reacted = True
                        msg = random.choice(NO_REPLY_MSGS)
                        async with client.action(YOUR_USERNAME,"typing"):
                            await asyncio.sleep(random.uniform(3,7))
                        await client.send_message(YOUR_USERNAME, msg)
                        last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"No reply error: {e}")

            async def send_random_message():
                try:
                    reply = await get_random_message()
                    if not reply: return
                    async with client.action(YOUR_USERNAME,"typing"):
                        await asyncio.sleep(random.uniform(2,5))
                    await client.send_message(YOUR_USERNAME, reply)
                    global last_shreya_msg_time
                    last_shreya_msg_time = datetime.now(IST)
                    logger.info(f"Random: {reply[:80]}")
                except Exception as e:
                    logger.error(f"Random error: {e}")

            async def send_meal_check():
                try:
                    h = datetime.now(IST).hour
                    meal = ("breakfast" if 7<=h<=10 else "lunch" if 12<=h<=14 else "dinner" if 19<=h<=21 else None)
                    if not meal or random.random() > 0.40: return
                    reply = await get_random_message(meal=meal)
                    if not reply: return
                    async with client.action(YOUR_USERNAME,"typing"):
                        await asyncio.sleep(random.uniform(2,4))
                    await client.send_message(YOUR_USERNAME, reply)
                except Exception as e:
                    logger.error(f"Meal error: {e}")

            async def check_if_silent():
                try:
                    now = datetime.now(IST)
                    if not (9 <= now.hour <= 23): return
                    if last_reply_time is None or (now-last_reply_time).total_seconds() > 7200:
                        reply = await get_random_message(nudge=True)
                        if not reply: return
                        async with client.action(YOUR_USERNAME,"typing"):
                            await asyncio.sleep(random.uniform(2,4))
                        await client.send_message(YOUR_USERNAME, reply)
                except Exception as e:
                    logger.error(f"Nudge error: {e}")

            async def send_good_morning():
                try:
                    reply = await call_groq([{"role":"user","content":"Send Chaitu a sweet good morning text. Just woke up. Max 1 sentence with emojis."}])
                    if reply:
                        if random.random() < 0.60:
                            await send_photo(client, YOUR_USERNAME)
                            await asyncio.sleep(random.uniform(1,3))
                        await client.send_message(YOUR_USERNAME, reply)
                        global last_shreya_msg_time
                        last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"Morning error: {e}")

            async def send_good_night():
                try:
                    reply = await call_groq([{"role":"user","content":"Send Chaitu a sweet good night text. About to sleep. Max 1 sentence with emojis."}])
                    if reply:
                        await client.send_message(YOUR_USERNAME, reply)
                        global last_shreya_msg_time
                        last_shreya_msg_time = datetime.now(IST)
                except Exception as e:
                    logger.error(f"Night error: {e}")

            async def send_sleep_message():
                try:
                    if random.random() < 0.50:
                        msg = random.choice(SLEEP_MSGS)
                        await client.send_message(YOUR_USERNAME, msg)
                except Exception as e:
                    logger.error(f"Sleep error: {e}")

            async def check_special_day():
                try:
                    special = get_special_day()
                    if not special: return
                    if special=="chaitu_birthday":  prompt="Today is Chaitu's birthday! Send him the most heartfelt birthday wish. Short and loving."
                    elif special=="your_birthday":   prompt="Today is your birthday 15th August! Text Chaitu excitedly. Short and happy."
                    elif special=="anniversary":     prompt="Today is your anniversary! Send Chaitu a loving message. Short and sweet."
                    else: return
                    reply = await call_groq([{"role":"user","content":prompt}])
                    if reply: await client.send_message(YOUR_USERNAME, reply)
                except Exception as e:
                    logger.error(f"Special day error: {e}")

            async def check_festival():
                try:
                    now = datetime.now(IST)
                    key = (now.month, now.day)
                    if key in FESTIVALS:
                        name, msgs = FESTIVALS[key]
                        msg = random.choice(msgs)
                        await client.send_message(YOUR_USERNAME, msg)
                        logger.info(f"Festival {name}: {msg}")
                except Exception as e:
                    logger.error(f"Festival error: {e}")

            async def check_monthly_anniversary():
                try:
                    # Fire on the same day each month as anniversary
                    ann_day = ANNIVERSARY[1]
                    if datetime.now(IST).day == ann_day:
                        msg = random.choice(MONTHLY_ANNIVERSARY_MSGS)
                        await client.send_message(YOUR_USERNAME, msg)
                        logger.info(f"Monthly anniversary: {msg}")
                except Exception as e:
                    logger.error(f"Anniversary error: {e}")

            async def send_exam_goodluck():
                try:
                    memory = load_memory()
                    today = datetime.now(IST).strftime("%d %b")
                    has_exam = any(("exam" in f.lower() or "test" in f.lower()) and today in f for f in memory.get("facts",[]))
                    if has_exam:
                        msg = random.choice(GOODLUCK_MSGS)
                        await client.send_message(YOUR_USERNAME, msg)
                except Exception as e:
                    logger.error(f"Goodluck error: {e}")

            def schedule_random():
                for job in scheduler.get_jobs():
                    if job.id.startswith("rand_"): job.remove()
                for total_minute in random.sample(range(480, 1380), 12):
                    h, m = total_minute//60, total_minute%60
                    scheduler.add_job(send_random_message,"cron",hour=h,minute=m,id=f"rand_{h}_{m}")

            scheduler = AsyncIOScheduler(timezone=IST)
            if not scheduler.running:
                schedule_random()
                scheduler.add_job(schedule_random,      "cron",     hour=0,  minute=1,                      id="reschedule")
                scheduler.add_job(send_good_morning,    "cron",     hour=8,  minute=0,                      id="morning")
                scheduler.add_job(send_good_night,      "cron",     hour=23, minute=0,                      id="night")
                scheduler.add_job(send_sleep_message,   "cron",     hour=22, minute=30,                     id="sleep_msg")
                scheduler.add_job(update_mood,          "cron",     hour="0,3,6,9,12,15,18,21", minute=0,   id="mood")
                scheduler.add_job(check_if_silent,      "interval", hours=3,                                id="silence")
                scheduler.add_job(check_special_day,    "cron",     hour=8,  minute=1,                      id="special")
                scheduler.add_job(send_exam_goodluck,   "cron",     hour=8,  minute=15,                     id="goodluck")
                scheduler.add_job(send_meal_check,      "cron",     hour=8,  minute=30,                     id="breakfast")
                scheduler.add_job(send_meal_check,      "cron",     hour=13, minute=0,                      id="lunch")
                scheduler.add_job(send_meal_check,      "cron",     hour=20, minute=0,                      id="dinner")
                scheduler.add_job(check_busy_followup,  "interval", minutes=5,                              id="followup")
                scheduler.add_job(check_seen_zone,      "interval", minutes=40,                             id="seen_zone")
                scheduler.add_job(check_no_reply,       "interval", minutes=60,                             id="no_reply")
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
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logger.info(f"Web server on port {port} ✅")

async def start():
    await asyncio.gather(run_web(), run_bot())

if __name__ == "__main__":
    asyncio.run(start())
