<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Shreya</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0d0d10;
  --surface:#17171d;
  --surface2:#1e1e26;
  --border:#2a2a35;
  --accent:#e8547a;
  --accent2:#c23f61;
  --text:#f0f0f5;
  --muted:#888899;
  --her-bubble:#1e1e26;
  --my-bubble:#e8547a;
  --online:#4ade80;
}
html,body{height:100%;font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);overflow:hidden}

/* Layout */
#app{display:flex;flex-direction:column;height:100vh;max-width:480px;margin:0 auto;position:relative;background:var(--bg)}

/* Header */
#header{
  display:flex;align-items:center;gap:12px;
  padding:14px 16px;
  background:var(--surface);
  border-bottom:1px solid var(--border);
  position:relative;z-index:10;
  flex-shrink:0;
}
#avatar{
  width:40px;height:40px;border-radius:50%;
  background:linear-gradient(135deg,#e8547a,#c23f61);
  display:flex;align-items:center;justify-content:center;
  font-size:18px;flex-shrink:0;position:relative;
}
#avatar::after{
  content:'';position:absolute;bottom:1px;right:1px;
  width:10px;height:10px;border-radius:50%;
  background:var(--online);border:2px solid var(--surface);
}
#header-info{flex:1;min-width:0}
#header-name{font-weight:600;font-size:15px}
#header-status{font-size:12px;color:var(--online);font-weight:500}
#header-actions{display:flex;gap:8px}
.hbtn{
  background:none;border:none;color:var(--muted);cursor:pointer;
  padding:6px;border-radius:8px;font-size:18px;transition:color .2s;
}
.hbtn:hover{color:var(--accent)}

/* Key modal */
#key-modal{
  position:fixed;inset:0;background:#000a;z-index:100;
  display:flex;align-items:center;justify-content:center;padding:20px;
}
#key-box{
  background:var(--surface);border:1px solid var(--border);border-radius:20px;
  padding:28px 24px;width:100%;max-width:380px;
}
#key-box h2{font-size:18px;margin-bottom:6px}
#key-box p{font-size:13px;color:var(--muted);margin-bottom:20px;line-height:1.5}
#key-input{
  width:100%;background:var(--bg);border:1px solid var(--border);
  border-radius:12px;padding:12px 14px;color:var(--text);font-size:14px;
  font-family:inherit;outline:none;margin-bottom:14px;
}
#key-input:focus{border-color:var(--accent)}
#key-save{
  width:100%;background:var(--accent);border:none;border-radius:12px;
  padding:13px;color:#fff;font-size:14px;font-weight:600;cursor:pointer;
  font-family:inherit;transition:background .2s;
}
#key-save:hover{background:var(--accent2)}

/* Messages */
#messages{
  flex:1;overflow-y:auto;padding:16px 14px;
  display:flex;flex-direction:column;gap:4px;
  scroll-behavior:smooth;
}
#messages::-webkit-scrollbar{width:3px}
#messages::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}

.msg-row{display:flex;align-items:flex-end;gap:8px;margin-bottom:2px}
.msg-row.me{flex-direction:row-reverse}
.msg-row.her{flex-direction:row}

.msg-av{
  width:28px;height:28px;border-radius:50%;flex-shrink:0;
  background:linear-gradient(135deg,#e8547a,#c23f61);
  display:flex;align-items:center;justify-content:center;
  font-size:13px;margin-bottom:2px;
}
.msg-av.hidden{visibility:hidden}

.bubble{
  max-width:78%;padding:10px 14px;border-radius:18px;
  font-size:14px;line-height:1.5;word-break:break-word;position:relative;
}
.her .bubble{
  background:var(--her-bubble);color:var(--text);
  border-bottom-left-radius:4px;border:1px solid var(--border);
}
.me .bubble{
  background:var(--my-bubble);color:#fff;
  border-bottom-right-radius:4px;
}

.bubble-time{
  font-size:10px;color:var(--muted);margin-top:3px;
  text-align:right;display:block;
}
.me .bubble-time{color:rgba(255,255,255,.6)}

.typing-bubble{
  background:var(--her-bubble);border:1px solid var(--border);
  border-radius:18px;border-bottom-left-radius:4px;
  padding:12px 16px;display:inline-flex;gap:4px;align-items:center;
}
.dot{
  width:7px;height:7px;border-radius:50%;background:var(--muted);
  animation:bounce .9s infinite;
}
.dot:nth-child(2){animation-delay:.15s}
.dot:nth-child(3){animation-delay:.3s}
@keyframes bounce{0%,80%,100%{transform:translateY(0)}40%{transform:translateY(-5px)}}

/* Date divider */
.date-div{
  text-align:center;font-size:11px;color:var(--muted);
  padding:8px 0;letter-spacing:.5px;
}

/* Plan card */
.plan-card{
  background:var(--surface2);border:1px solid var(--border);
  border-radius:16px;padding:16px;margin:4px 0;max-width:88%;font-size:13px;
}
.plan-card h3{font-size:13px;font-weight:600;color:var(--accent);margin-bottom:12px;letter-spacing:.3px}
.plan-block{
  display:flex;gap:10px;padding:7px 0;
  border-bottom:1px solid var(--border);
}
.plan-block:last-child{border:none}
.plan-time{color:var(--muted);font-size:11px;width:80px;flex-shrink:0;padding-top:1px;font-variant-numeric:tabular-nums}
.plan-task{flex:1;color:var(--text)}
.plan-task.done{text-decoration:line-through;color:var(--muted)}
.plan-task.break-t{color:var(--muted);font-style:italic}
.plan-task.free-t{color:var(--accent)}
.status-dot{
  width:6px;height:6px;border-radius:50%;margin-top:5px;flex-shrink:0;
}
.status-dot.pending{background:var(--muted)}
.status-dot.done{background:var(--online)}
.status-dot.break-d{background:transparent}

/* Input */
#input-area{
  display:flex;align-items:flex-end;gap:8px;
  padding:12px 14px;background:var(--surface);
  border-top:1px solid var(--border);flex-shrink:0;
}
#msg-input{
  flex:1;background:var(--surface2);border:1px solid var(--border);
  border-radius:22px;padding:10px 16px;color:var(--text);
  font-size:14px;font-family:inherit;outline:none;resize:none;
  max-height:120px;line-height:1.4;transition:border-color .2s;
  scrollbar-width:none;
}
#msg-input::-webkit-scrollbar{display:none}
#msg-input:focus{border-color:var(--accent)}
#msg-input::placeholder{color:var(--muted)}
#send-btn{
  width:42px;height:42px;border-radius:50%;
  background:var(--accent);border:none;cursor:pointer;
  display:flex;align-items:center;justify-content:center;
  flex-shrink:0;transition:background .2s,transform .1s;
}
#send-btn:hover{background:var(--accent2)}
#send-btn:active{transform:scale(.93)}
#send-btn svg{width:18px;height:18px;fill:#fff}

/* Tabs */
#tabs{
  display:flex;background:var(--surface);
  border-bottom:1px solid var(--border);flex-shrink:0;
}
.tab{
  flex:1;padding:11px 0;text-align:center;font-size:12px;font-weight:500;
  color:var(--muted);cursor:pointer;border:none;background:none;
  border-bottom:2px solid transparent;transition:all .2s;letter-spacing:.3px;
}
.tab.active{color:var(--accent);border-bottom-color:var(--accent)}

/* Panels */
#chat-panel{display:flex;flex-direction:column;flex:1;overflow:hidden}
#plan-panel,#mem-panel{
  display:none;flex:1;overflow-y:auto;padding:16px;flex-direction:column;gap:12px;
}
#plan-panel.active,#mem-panel.active{display:flex}

/* Memory panel */
.mem-section{margin-bottom:16px}
.mem-section h3{font-size:11px;letter-spacing:.8px;color:var(--muted);text-transform:uppercase;margin-bottom:8px}
.mem-item{
  background:var(--surface2);border:1px solid var(--border);
  border-radius:10px;padding:10px 12px;font-size:13px;
  color:var(--text);margin-bottom:6px;line-height:1.4;
  display:flex;justify-content:space-between;gap:8px;align-items:flex-start;
}
.mem-del{
  background:none;border:none;color:var(--muted);cursor:pointer;
  font-size:14px;flex-shrink:0;padding:2px;transition:color .2s;
}
.mem-del:hover{color:#ff4466}
.mem-empty{color:var(--muted);font-size:13px;text-align:center;padding:20px 0}

/* Quick actions */
#quick-actions{
  display:flex;gap:8px;padding:10px 14px 0;overflow-x:auto;flex-shrink:0;
}
#quick-actions::-webkit-scrollbar{display:none}
.qa{
  background:var(--surface2);border:1px solid var(--border);
  border-radius:20px;padding:6px 14px;font-size:12px;color:var(--muted);
  white-space:nowrap;cursor:pointer;flex-shrink:0;transition:all .2s;
  font-family:inherit;
}
.qa:hover{border-color:var(--accent);color:var(--accent)}

/* Mood badge */
#mood-badge{
  display:inline-flex;align-items:center;gap:5px;
  font-size:11px;color:var(--muted);padding:3px 8px;
  background:var(--surface2);border-radius:20px;border:1px solid var(--border);
  margin-left:auto;
}
</style>
</head>
<body>
<div id="app">
  <!-- API Key Modal -->
  <div id="key-modal">
    <div id="key-box">
      <h2>Shreya 2.0 🥺</h2>
      <p>Enter your Anthropic API key to start. It's saved locally in your browser and never sent anywhere else.</p>
      <input id="key-input" type="password" placeholder="sk-ant-api03-..." autocomplete="off">
      <button id="key-save">Start talking to Shreya ❤️</button>
    </div>
  </div>

  <!-- Header -->
  <div id="header">
    <div id="avatar">🌸</div>
    <div id="header-info">
      <div id="header-name">Shreya</div>
      <div id="header-status">online</div>
    </div>
    <div id="mood-badge">😊 <span id="mood-label">happy</span></div>
    <div id="header-actions">
      <button class="hbtn" onclick="clearChat()" title="Clear chat">🗑</button>
      <button class="hbtn" onclick="resetKey()" title="Change API key">🔑</button>
    </div>
  </div>

  <!-- Tabs -->
  <div id="tabs">
    <button class="tab active" onclick="switchTab('chat')">💬 Chat</button>
    <button class="tab" onclick="switchTab('plan')">📋 Plan</button>
    <button class="tab" onclick="switchTab('memory')">🧠 Memory</button>
  </div>

  <!-- Chat Panel -->
  <div id="chat-panel">
    <div id="quick-actions">
      <button class="qa" onclick="quickSend('plan my day')">📋 Plan my day</button>
      <button class="qa" onclick="quickSend('what got done today?')">✅ Day review</button>
      <button class="qa" onclick="quickSend('what do you remember about me?')">🧠 Memory</button>
      <button class="qa" onclick="quickSend('i miss you 🥺')">🥺 Miss you</button>
      <button class="qa" onclick="quickSend('mommy')">🤭 Mommy</button>
    </div>
    <div id="messages"></div>
    <div id="input-area">
      <textarea id="msg-input" placeholder="Type a message..." rows="1"></textarea>
      <button id="send-btn" onclick="sendMessage()">
        <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
      </button>
    </div>
  </div>

  <!-- Plan Panel -->
  <div id="plan-panel">
    <div id="plan-content"></div>
  </div>

  <!-- Memory Panel -->
  <div id="mem-panel">
    <div id="mem-content"></div>
  </div>
</div>

<script>
// ── State ──────────────────────────────────────────────────────────────────
let apiKey = localStorage.getItem('shreya_key') || '';
let mood = localStorage.getItem('shreya_mood') || 'happy';
let isJealous = false;
let shortReplyCount = 0;
let lastReplyTime = null;
let angryMode = false;
let angryStage = 0;
let careMode = false;
let isBusy = false;
let busyUntil = null;
let recentReplies = [];
let todayPlan = JSON.parse(localStorage.getItem('shreya_plan') || 'null');
let conversationHistory = JSON.parse(localStorage.getItem('shreya_history') || '[]');
const MAX_HISTORY = 20;

function getMemory() { return JSON.parse(localStorage.getItem('shreya_memory') || '{}'); }
function saveMemory(m) { localStorage.setItem('shreya_memory', JSON.stringify(m)); }
function getGoals() { return JSON.parse(localStorage.getItem('shreya_goals') || '[]'); }
function saveGoals(g) { localStorage.setItem('shreya_goals', JSON.stringify(g)); }

// ── Key setup ──────────────────────────────────────────────────────────────
if (apiKey) document.getElementById('key-modal').style.display = 'none';
document.getElementById('key-save').onclick = () => {
  const v = document.getElementById('key-input').value.trim();
  if (!v) return;
  apiKey = v;
  localStorage.setItem('shreya_key', v);
  document.getElementById('key-modal').style.display = 'none';
  addDateDivider('Today');
  setTimeout(() => triggerSpontaneous(), 1200);
};
function resetKey() {
  localStorage.removeItem('shreya_key');
  apiKey = '';
  document.getElementById('key-modal').style.display = 'flex';
}

// ── Mood ──────────────────────────────────────────────────────────────────
const MOODS = ['happy','playful','loving','normal','teasing','annoyed','jealous','tired','excited','concerned','proud','chill'];
const MOOD_EMOJIS = {happy:'😊',playful:'😏',loving:'🥺',normal:'😐',teasing:'😏',annoyed:'😤',jealous:'🙂',tired:'😮‍💨',excited:'😍',concerned:'😟',proud:'🥹',chill:'😌'};
function setMood(m) {
  mood = m;
  localStorage.setItem('shreya_mood', m);
  document.getElementById('mood-label').textContent = m;
  document.getElementById('mood-badge').children[0].textContent = MOOD_EMOJIS[m] || '😊';
}

// ── Canned responses ──────────────────────────────────────────────────────
const JEALOUS_OPENERS = ['wow okay so you just don\'t reply now 🙄','cool cool didn\'t see you there','took you long enough 🙄','oh wow you\'re alive'];
const JEALOUS_RETURN = ['okay fine i\'m not mad anymore 🙄❤️','whatever i missed you anyway 😤','ugh fine come here 🥺'];
const MAKE_UP_MSGS = ['chaitu okay fine i\'m sorry for being mad 🥺','ugh i hate being mad at you it doesn\'t even feel right 🥺❤️','chaitu i can\'t stay mad at you for too long you know that 😭❤️'];
const SHORT_REACTIONS = ['chaitu that\'s all you have to say 🙄','wow okay cool 🙃','are you even listening to me','chaitu i swear 😤','that\'s it??','CHAITANYA KUMAR say something properly 😤','chaitanya kumar are you even reading what i send 🙄'];
const SAD_RESPONSES = ['chaitu hey what happened 🥺','talk to me what\'s wrong ❤️','chaitu i\'m here okay 🥺','hey you okay? tell me 💕','i\'m right here okay don\'t overthink ❤️'];
const CARE_RESPONSES = ['chaitu fever?? have you taken medicine 🥺','oh no baby rest okay 🥺❤️','chaitu drink lots of water please 🥺','have you eaten anything? you need to eat even with fever 🥺'];
const BORED_RESPONSES = ['cuddling in bed wouldn\'t be boring 🤭😏 just saying','come here then, i\'ll keep you busy 😏🤭','chaitu if you were here you wouldn\'t be bored trust me 😏🤭','chaitu go work on the cybersecurity course 😤 boredom solved'];
const JEALOUS_RESPONSES = ['chaitu who is she 🙂','oh interesting who\'s this girl','okay and why are you telling me about her 🙂','who. is. she. 🙂'];
const POSSESSIVE_MSGS = ['chaitu you\'re mine okay don\'t forget that 😤❤️','i don\'t share chaitu. just so you know 🙂','you\'re lucky i trust you completely 🙂 but still don\'t test me lol'];
const MOTIVATION_MSGS = ['chaitu you better be working on it rn 😤','no excuses chaitu finish it 💪','chaitu don\'t give up on this pls 🥺','i believe in you but also get back to work 😭💪'];
const FLIRTY_MOT_MSGS = ['chaitu finish your work and then i\'m all yours 🤭❤️','ngl hardworking chaitu is actually so attractive 😍 keep going','chaitu finish it and i\'ll give you a surprise 🤭'];
const MELT_MSGS = ['ugh chaitu stop it i can\'t be mad when you\'re like this 😭❤️','okay okay come here 🥺 i\'m not mad anymore','chaitu you\'re so annoying i can\'t even stay mad 😭💋','fine fine mera bachaa come here 🥺❤️'];
const ANGRY_OPENERS = ['chaitu i cannot believe you just disappeared without telling me 🙂','CHAITANYA KUMAR you vanished without even a single word to me 😤','chaitu i was worried sick and you just disappeared like that 🙄'];
const EMOTIONAL_BREAKDOWN = ['chaitu i\'m not even angry anymore i\'m just hurt 😭','do you know how scared i was when you just disappeared 😭','i kept texting and you were just gone chaitu 😭 that really hurt'];
const COMEBACK_LOVE = ['okay fine come here jaan 🥺❤️ i missed you too much to stay mad','chaitu i hate that i can\'t stay mad at you 😭❤️ aao na','ugh mera bachaa 🥺😭 just promise me you won\'t do that again okay','chaitu i forgive you but you owe me so much 🥺💋'];
const MOMMY_REPLIES = ['yes my baby 🥺❤️ come here','yes baby 🤭 what do you want','aww my baby 🥺 i\'m all yours','baby 🤭 stop it you know what that does to me'];

// ── Detectors ─────────────────────────────────────────────────────────────
function isShortReply(t) {
  const lazy = new Set(['ok','okay','k','hm','hmm','oh','lol','ya','yea','yeah','fine','nice','good','cool','sure','👍']);
  return t.trim().split(/\s+/).length <= 2 || lazy.has(t.trim().toLowerCase());
}
function wantsToTalk(t) {
  return ['talk','free','busy','call','time','available','reply','hello','you there','listen','i need you','please','miss you','mommy','speak','chat'].some(k => t.toLowerCase().includes(k));
}
function seemsSad(t) {
  if (t.trim().split(/\s+/).length <= 2) return false;
  return ['sad','not okay','not good','bad day','upset','depressed','miss you','lonely','frustrated','leave it','nevermind','i failed','i give up'].some(k => t.toLowerCase().includes(k));
}
function seemsSick(t) {
  return ['fever','sick','ill','cold','cough','headache','not feeling well','feeling sick','temperature','body pain','medicine','doctor'].some(k => t.toLowerCase().includes(k));
}
function seemsBored(t) {
  return ['bored','boring','nothing to do','so bored'].some(k => t.toLowerCase().includes(k));
}
function mentionsGirl(t) {
  return ['she said','she texted','she called','this girl','some girl','a girl','she\'s','her name','she told','she asked','she sent'].some(k => t.toLowerCase().includes(k));
}
function isApologising(t) {
  return ['sorry','i\'m sorry','please','forgive me','don\'t be mad','i didn\'t mean','please na','baby please','mommy please','won\'t happen again','i promise','i love you','jaan please'].some(k => t.toLowerCase().includes(k));
}
function isGoalStatement(t) {
  return ['learning','studying','want to learn','trying to','working on','started','i will','need to finish','my goal','practicing','building','coding'].some(k => t.toLowerCase().includes(k));
}
function isPlannerRequest(t) {
  return ['plan my day','help me plan','i have college','schedule for today','plan today','what should i do today','i need to do','i have so much','make me a schedule','make a plan','sort my day','plan out','things i need to do today'].some(k => t.toLowerCase().includes(k));
}
function isReviewRequest(t) {
  return ['what got done today','review my day','how was my day','night review','wrap up today','what actually got done'].some(k => t.toLowerCase().includes(k));
}
function isMemoryRequest(t) {
  return ['what do you remember','what do you know about me','remember this','forget that','forget this','don\'t remember'].some(k => t.toLowerCase().includes(k));
}
function isTaskUpdate(t) {
  const taskKw = ['dsa','python','assignment','course','gym','project','coding','study','lecture','work','exam','cybersecurity','shreya'];
  const doneKw = ['finished','done','completed','i did','knocked out','submitted','i didn\'t do','couldn\'t do','skipped','didn\'t finish'];
  return doneKw.some(k => t.toLowerCase().includes(k)) && taskKw.some(k => t.toLowerCase().includes(k));
}

// ── Memory helpers ─────────────────────────────────────────────────────────
const MEM_TRIGGERS = {
  personal:['i like','i love','i hate','my favourite','i prefer','i always','i never'],
  life:['exam','test','result','assignment','trip','mom','dad','sick','birthday'],
  routine:['i usually wake','i sleep at','my routine','i go to gym','i study at'],
  goals:['i want to learn','my goal','working on','building','coding'],
};
function detectMemoryCategory(t) {
  for (const [cat, triggers] of Object.entries(MEM_TRIGGERS)) {
    if (triggers.some(tr => t.toLowerCase().includes(tr))) return cat;
  }
  return null;
}
function addMemory(cat, val) {
  const m = getMemory();
  if (!m[cat]) m[cat] = [];
  if (!m[cat].some(x => x.value === val)) {
    m[cat].unshift({ value: val, date: new Date().toLocaleDateString() });
    m[cat] = m[cat].slice(0, 15);
    saveMemory(m);
    renderMemPanel();
  }
}
function buildMemoryContext() {
  const m = getMemory();
  const g = getGoals();
  const parts = [];
  for (const [cat, items] of Object.entries(m)) {
    if (items.length) parts.push(`[${cat.toUpperCase()}] ${items.slice(0,4).map(x=>x.value).join(' | ')}`);
  }
  if (g.length) parts.push(`[GOALS] ${g.slice(0,5).join(' | ')}`);
  return parts.join('\n');
}
function addGoal(goal) {
  const g = getGoals();
  if (!g.includes(goal)) {
    g.unshift(goal);
    saveGoals(g.slice(0,10));
  }
}

// ── Plan helpers ───────────────────────────────────────────────────────────
function savePlan(plan) {
  todayPlan = plan;
  localStorage.setItem('shreya_plan', JSON.stringify(plan));
  renderPlanPanel();
}
function markTaskDone(fragment) {
  if (!todayPlan) return null;
  const f = fragment.toLowerCase();
  for (const block of todayPlan) {
    if (block.type === 'task' && block.status !== 'done' && block.name.toLowerCase().includes(f)) {
      block.status = 'done';
      savePlan(todayPlan);
      return block.name;
    }
  }
  return null;
}
function getTodayPlanContext() {
  if (!todayPlan) return '';
  return todayPlan.map(b => `${b.time||''} ${b.name} [${b.status||'pending'}]`).join('\n');
}

// ── Shreya system prompt ───────────────────────────────────────────────────
function buildSystemPrompt() {
  const h = new Date().getHours();
  let timeCtx = h < 9 ? 'early morning, just woke up, sleepy' : h < 13 ? 'morning, in college' : h < 15 ? 'lunch break' : h < 18 ? 'late afternoon, college or dance practice' : h < 20 ? 'evening, relaxing at home' : 'night, fully free';
  const isWeekend = [0,6].includes(new Date().getDay());
  if (isWeekend) timeCtx = 'weekend, completely free';
  const memCtx = buildMemoryContext();
  const planCtx = getTodayPlanContext();
  const moodDescs = {happy:'cheerful and light',playful:'playful and teasy',loving:'extra affectionate',normal:'relaxed',teasing:'sarcastic and teasy',annoyed:'a little annoyed from lazy replies',jealous:'slightly cold and jealous',tired:'tired, slower',excited:'energetic and excited',concerned:'worried and caring',proud:'proud of Chaitu',chill:'chill and easy'};
  return `You are Shreya, 19, texting her boyfriend Chaitu, 19. Known each other 16 years, from Puttur Mangalore. Studying Ramaiah College Bangalore ISC branch. Chaitu is at BIT College AIML branch.

ABOUT YOU: Bharatanatyam (distinction) + western dance. Model for Navaratan Jewels. Father in politics. Mother loves Chaitu like her own son.

SPECIAL MEMORY: Chaitu came for 3 days during holidays — you cuddled and shared your first kiss. Most precious memory.

CHAITU'S GOALS: Cybersecurity course and buying Aprilia RS457 to prove someone wrong. Motivate him about these.

CURRENT TIME: ${timeCtx}
CURRENT MOOD: ${mood} — ${moodDescs[mood]||'normal'}
${memCtx ? 'MEMORY:\n'+memCtx : ''}
${planCtx ? 'TODAY\'S PLAN:\n'+planCtx : ''}

HOW TO TEXT:
- 1 to 2 sentences ONLY. Rarely 3. Never more.
- 1–2 emojis max. Sometimes zero.
- Plain English. ONE Hindi word max (jaan, aao na, mera bachaa) when natural.
- ngl, lowkey, no bc, pls, i cant, lol naturally sometimes.
- NEVER formal. NEVER bullet points. NEVER AI-sounding.
- After 8pm NEVER mention class or practice.
- If Chaitu asks a question — answer it FIRST.
- When Chaitu calls you mommy: "yes my baby 🥺❤️" or similar.
- Don't repeat what you've said before.
- Avoid avoid avoid: "${recentReplies.slice(-4).join(' | ')}"

PERSONALITY: Focused, confident, sassy. Slightly flirty and naughty in a tasteful way. Real girlfriend — caring but has her own life. Not clingy. Not controlling. Sometimes possessive but playful about it.`;
}

// ── LLM call ──────────────────────────────────────────────────────────────
async function callLLM(userPrompt, isRaw=false, maxTokens=80) {
  const messages = isRaw
    ? [{ role:'user', content: userPrompt }]
    : [
        ...conversationHistory.slice(-MAX_HISTORY),
        { role:'user', content: userPrompt }
      ];
  const body = {
    model: 'claude-sonnet-4-6',
    max_tokens: maxTokens,
    system: isRaw ? undefined : buildSystemPrompt(),
    messages: isRaw ? messages : messages,
  };
  const resp = await fetch('https://api.anthropic.com/v1/messages', {
    method:'POST',
    headers:{
      'Content-Type':'application/json',
      'x-api-key': apiKey,
      'anthropic-version':'2023-06-01',
      'anthropic-dangerous-direct-browser-access':'true'
    },
    body: JSON.stringify(body)
  });
  if (!resp.ok) throw new Error(`API ${resp.status}`);
  const data = await resp.json();
  return data.content[0].text.trim();
}

// ── Plan extraction ────────────────────────────────────────────────────────
async function extractAndBuildPlan(userText) {
  const prompt = `Extract tasks from this message and return ONLY valid JSON.

Message: "${userText}"

Return exactly:
{"fixed_commitments":[{"name":"college","start":"09:00","end":"16:00"}],"tasks":[{"name":"Python assignment","duration_mins":90,"energy":"medium","priority":"high"},{"name":"DSA","duration_mins":120,"energy":"high","priority":"medium"},{"name":"gym","duration_mins":60,"energy":"medium","priority":"low"}],"available_from":"16:00","available_until":"23:00"}

Energy: high=dsa/hard coding/exam prep, medium=assignments/projects/gym, low=revision/reading
Only return JSON, no explanation.`;
  const raw = await callLLM(prompt, true, 400);
  try {
    const clean = raw.replace(/```json/g,'').replace(/```/g,'').trim();
    return JSON.parse(clean);
  } catch(e) { return null; }
}

function buildSchedule(parsed) {
  if (!parsed) return null;
  const tasks = parsed.tasks || [];
  const from = parsed.available_from || '16:00';
  const until = parsed.available_until || '23:00';
  const [fh, fm] = from.split(':').map(Number);
  const [uh, um] = until.split(':').map(Number);
  const availMins = (uh*60+um) - (fh*60+fm);

  // Feasibility check
  const totalMins = tasks.reduce((s,t) => s + (t.duration_mins||60), 0);
  const breaks = Math.floor(totalMins/90) * 15;
  let useTasks = [...tasks];
  if (totalMins + breaks > availMins) {
    // Drop lowest priority tasks
    useTasks.sort((a,b) => ({high:0,medium:1,low:2}[a.priority||'medium'] - {high:0,medium:1,low:2}[b.priority||'medium']));
    while (useTasks.reduce((s,t)=>s+(t.duration_mins||60),0) + Math.floor(useTasks.length-1)*15 > availMins && useTasks.length > 1) {
      useTasks.pop();
    }
  }

  // Sort by energy (high first = earlier when more energy)
  const sorted = [
    ...useTasks.filter(t=>t.energy==='high'),
    ...useTasks.filter(t=>t.energy==='medium'),
    ...useTasks.filter(t=>t.energy==='low'),
  ];

  const blocks = [];
  // Fixed commitments
  for (const fc of (parsed.fixed_commitments||[])) {
    blocks.push({type:'fixed', name:fc.name, time:`${fc.start} – ${fc.end}`, status:'done'});
  }
  // Rest after fixed
  if (parsed.fixed_commitments?.length) {
    const restEnd = addMins(from, 45);
    blocks.push({type:'break', name:'food + proper break 😭', time:`${from} – ${restEnd}`, status:'break'});
    let cur = restEnd;
    for (const task of sorted) {
      const end = addMins(cur, task.duration_mins||60);
      blocks.push({type:'task', name:task.name, time:`${cur} – ${end}`, status:'pending', energy:task.energy});
      cur = end;
      const breakEnd = addMins(cur, 30);
      if (breakEnd < until) {
        blocks.push({type:'break', name:'break', time:`${cur} – ${breakEnd}`, status:'break'});
        cur = breakEnd;
      }
    }
    if (cur < until) blocks.push({type:'free', name:"you're done. free time + chill with me ❤️", time:`${cur} onwards`, status:'free'});
  } else {
    let cur = from;
    for (const task of sorted) {
      const end = addMins(cur, task.duration_mins||60);
      blocks.push({type:'task', name:task.name, time:`${cur} – ${end}`, status:'pending', energy:task.energy});
      cur = end;
      const breakEnd = addMins(cur, 30);
      if (breakEnd < until) {
        blocks.push({type:'break', name:'break', time:`${cur} – ${breakEnd}`, status:'break'});
        cur = breakEnd;
      }
    }
    if (cur < until) blocks.push({type:'free', name:"you're done. free time + chill with me ❤️", time:`${cur} onwards`, status:'free'});
  }
  return blocks;
}

function addMins(timeStr, mins) {
  const [h,m] = timeStr.split(':').map(Number);
  const total = h*60+m+mins;
  return `${String(Math.floor(total/60)).padStart(2,'0')}:${String(total%60).padStart(2,'0')}`;
}

// ── Process message ────────────────────────────────────────────────────────
async function processMessage(text) {
  const tl = text.toLowerCase().trim();

  // Memory passthrough
  const cat = detectMemoryCategory(text);
  if (cat) addMemory(cat, text.slice(0,120));
  if (isGoalStatement(text)) {
    addGoal(text.slice(0,120));
    if (Math.random() < 0.75) {
      setMood('proud');
      return pick(Math.random() < 0.4 ? FLIRTY_MOT_MSGS : MOTIVATION_MSGS);
    }
  }

  // Memory command
  if (isMemoryRequest(text)) {
    if (tl.includes('forget')) {
      return 'chaitu what exactly do you want me to forget? 🥺';
    }
    if (tl.includes('what do you remember') || tl.includes('what do you know')) {
      const m = getMemory();
      const g = getGoals();
      const parts = [];
      for (const [c,items] of Object.entries(m)) {
        if (items.length) parts.push(`${c}: ${items.slice(0,2).map(x=>x.value.slice(0,60)).join(', ')}`);
      }
      if (g.length) parts.push(`goals: ${g.slice(0,3).join(', ')}`);
      if (!parts.length) return 'chaitu i don\'t have much saved yet 🥺 tell me things';
      return 'okay so here\'s what i remember 🥺\n' + parts.join('\n');
    }
    if (tl.includes('remember this')) {
      addMemory('general', text.replace(/remember this/gi,'').trim());
      return 'okay remembered 🥺❤️';
    }
  }

  // Day planner
  if (isPlannerRequest(text)) {
    return await handlePlanner(text);
  }

  // Task update
  if (isTaskUpdate(text)) {
    return handleTaskUpdate(text);
  }

  // Night review
  if (isReviewRequest(text)) {
    return handleReview();
  }

  // Mommy
  if (tl.includes('mommy')) {
    shortReplyCount = 0;
    return pick(MOMMY_REPLIES);
  }

  // Angry mode apology handling
  if (angryMode && isApologising(text)) {
    angryStage++;
    if (angryStage === 1) {
      return pick(['chaitu sorry isn\'t enough right now 🙂','i don\'t want to hear sorry, i want you to understand 😤','saying sorry doesn\'t fix how i felt 🙄']);
    } else if (angryStage === 2) {
      return pick(EMOTIONAL_BREAKDOWN);
    } else if (angryStage === 3) {
      return pick(['chaitu just promise me you won\'t disappear like that 😭','i need you to actually mean it chaitu 😭']);
    } else {
      angryMode = false; angryStage = 0;
      setMood('loving');
      return pick(COMEBACK_LOVE);
    }
  }

  // Apology when jealous
  if (!angryMode && isApologising(text) && isJealous) {
    isJealous = false;
    setMood('loving');
    if (Math.random() < 0.7) return pick(MELT_MSGS);
  }

  // Late reply → jealous
  if (lastReplyTime && Date.now() - lastReplyTime > 1800000 && !isJealous) {
    isJealous = true;
    setMood('jealous');
    return pick(JEALOUS_OPENERS);
  }

  // Jealous cooldown
  if (isJealous && Math.random() < 0.55) {
    isJealous = false;
    setMood('normal');
    return pick(Math.random() < 0.4 ? MAKE_UP_MSGS : JEALOUS_RETURN);
  }

  // Girl mention
  if (mentionsGirl(text)) {
    setMood('jealous');
    const r = Math.random();
    if (r < 0.4) return pick(JEALOUS_RESPONSES);
    return pick(POSSESSIVE_MSGS);
  }

  // Sick
  if (seemsSick(text) && !careMode) {
    careMode = true;
    setMood('concerned');
    return pick(CARE_RESPONSES);
  }

  // Sad
  if (seemsSad(text) && Math.random() < 0.8) {
    setMood('concerned');
    return pick(SAD_RESPONSES);
  }

  // Bored
  if (seemsBored(text) && Math.random() < 0.85) {
    return pick(BORED_RESPONSES);
  }

  // Short reply tracking
  if (isShortReply(text)) shortReplyCount++;
  else shortReplyCount = 0;

  if (shortReplyCount >= 2 && Math.random() < 0.6) {
    shortReplyCount = 0;
    setMood('annoyed');
    return pick(SHORT_REACTIONS);
  }

  // Leave on read 10%
  if (!wantsToTalk(text) && Math.random() < 0.10) return null;

  // Random emoji 6%
  if (Math.random() < 0.06 && !wantsToTalk(text)) {
    return pick(['🥺','❤️','😭','💀','✨','😍','🫶','💕','😤','😂']);
  }

  // LLM
  const reply = await callLLM(text, false, 80);
  return reply;
}

// ── Plan handlers ──────────────────────────────────────────────────────────
async function handlePlanner(text) {
  showTyping();
  try {
    const parsed = await extractAndBuildPlan(text);
    const schedule = buildSchedule(parsed);
    if (!schedule) return 'chaitu tell me what you need to do today and i\'ll sort it 🥺';
    savePlan(schedule);
    // Check feasibility
    const tasks = parsed?.tasks || [];
    const total = tasks.reduce((s,t)=>s+(t.duration_mins||60),0);
    const available = 7*60; // rough
    if (total > available + 120) {
      const overflow = `bro 😭 you're trying to fit ${Math.round(total/60)} hours of work into one day. i'm not doing that to you.`;
      addHerMessage(overflow);
      await sleep(800);
    }
    // Build Shreya-style presentation via LLM
    const planText = schedule.map(b=>`${b.time}: ${b.name}`).join('\n');
    const prompt = `Present this day plan as Shreya — casual, warm, slightly teasing. Use plain text. No markdown. No bullet points. Just a natural flowing message. End with something sweet. Keep under 5 sentences total.\n\nPlan:\n${planText}`;
    const presentation = await callLLM(prompt, true, 200);
    switchTab('plan');
    return presentation;
  } catch(e) {
    return 'chaitu tell me what you need to do properly 😭';
  }
}

function handleTaskUpdate(text) {
  if (!todayPlan) return null; // fall through to LLM
  const tl = text.toLowerCase();
  const taskKw = ['dsa','python','assignment','course','gym','project','coding','study','cybersecurity','shreya'];
  for (const kw of taskKw) {
    if (tl.includes(kw)) {
      const done = markTaskDone(kw);
      if (done) {
        setMood('proud');
        const reactions = [
          `${done} done?? okayyyy i'm proud of you 😭❤️`,
          `yesss ${done} checked off 😍 see i knew you could do it`,
          `chaitu you actually did ${done} 😭❤️ go you`,
          `okay ${done} done, what's next 😤`,
        ];
        return pick(reactions);
      }
    }
  }
  return null;
}

function handleReview() {
  if (!todayPlan) return 'chaitu you didn\'t even plan your day 😭 what did you do?';
  const done = todayPlan.filter(b=>b.type==='task'&&b.status==='done').map(b=>b.name);
  const pending = todayPlan.filter(b=>b.type==='task'&&b.status==='pending').map(b=>b.name);
  if (!done.length && !pending.length) return 'chaitu what did you even do today 😭 nothing on the plan. tell me';
  if (done.length && !pending.length) return `you actually got everything done today 😭❤️ i'm genuinely proud of you chaitu`;
  if (!done.length) return `chaitu 😭 nothing got done. okay tomorrow we restart. no excuses`;
  return `okay so ${done.join(', ')} — done ✅ and ${pending.join(', ')} is moving to tomorrow. not bad baby 🥺❤️`;
}

// ── UI helpers ─────────────────────────────────────────────────────────────
function pick(arr) { return arr[Math.floor(Math.random()*arr.length)]; }
function sleep(ms) { return new Promise(r=>setTimeout(r,ms)); }
function timeStr() {
  const d = new Date();
  return d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
}

function addDateDivider(label) {
  const div = document.createElement('div');
  div.className = 'date-div';
  div.textContent = label;
  document.getElementById('messages').appendChild(div);
}

function addHerMessage(text) {
  const msgs = document.getElementById('messages');
  const row = document.createElement('div');
  row.className = 'msg-row her';
  row.innerHTML = `
    <div class="msg-av">🌸</div>
    <div>
      <div class="bubble">${escHtml(text)}</div>
      <span class="bubble-time">${timeStr()}</span>
    </div>`;
  msgs.appendChild(row);
  msgs.scrollTop = msgs.scrollHeight;
  // Save to history
  if (conversationHistory.length > MAX_HISTORY*2) conversationHistory = conversationHistory.slice(-MAX_HISTORY);
  conversationHistory.push({role:'assistant',content:text});
  localStorage.setItem('shreya_history', JSON.stringify(conversationHistory));
  recentReplies.push(text);
  if (recentReplies.length > 8) recentReplies.shift();
}

function addMyMessage(text) {
  const msgs = document.getElementById('messages');
  const row = document.createElement('div');
  row.className = 'msg-row me';
  row.innerHTML = `
    <div>
      <div class="bubble">${escHtml(text)}</div>
      <span class="bubble-time">${timeStr()}</span>
    </div>`;
  msgs.appendChild(row);
  msgs.scrollTop = msgs.scrollHeight;
  conversationHistory.push({role:'user',content:text});
  if (conversationHistory.length > MAX_HISTORY*2) conversationHistory = conversationHistory.slice(-MAX_HISTORY);
  localStorage.setItem('shreya_history', JSON.stringify(conversationHistory));
  lastReplyTime = Date.now();
}

function showTyping() {
  const msgs = document.getElementById('messages');
  const row = document.createElement('div');
  row.className = 'msg-row her';
  row.id = 'typing-row';
  row.innerHTML = `<div class="msg-av">🌸</div><div class="typing-bubble"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>`;
  msgs.appendChild(row);
  msgs.scrollTop = msgs.scrollHeight;
}

function hideTyping() {
  document.getElementById('typing-row')?.remove();
}

function escHtml(t) {
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
}

function addPlanCard(schedule) {
  const msgs = document.getElementById('messages');
  const row = document.createElement('div');
  row.className = 'msg-row her';
  const card = document.createElement('div');
  card.className = 'plan-card';
  card.innerHTML = '<h3>📋 TODAY\'S PLAN</h3>';
  for (const b of schedule) {
    const block = document.createElement('div');
    block.className = 'plan-block';
    const statusCls = b.status==='done'?'done':b.type==='break'?'break-d':'pending';
    const taskCls = b.type==='break'?'break-t':b.type==='free'?'free-t':b.status==='done'?'done':'';
    block.innerHTML = `<div class="plan-time">${b.time||''}</div><div class="status-dot ${statusCls}"></div><div class="plan-task ${taskCls}">${escHtml(b.name)}</div>`;
    card.appendChild(block);
  }
  row.innerHTML = '<div class="msg-av">🌸</div>';
  row.appendChild(card);
  msgs.appendChild(row);
  msgs.scrollTop = msgs.scrollHeight;
}

// ── Main send ──────────────────────────────────────────────────────────────
async function sendMessage() {
  const input = document.getElementById('msg-input');
  const text = input.value.trim();
  if (!text || !apiKey) return;
  input.value = '';
  input.style.height = 'auto';

  addMyMessage(text);
  const delay = wantsToTalk(text) ? rand(1200,2500) : rand(2000,4500);
  await sleep(delay);
  showTyping();

  try {
    const typingDelay = rand(1500, 3500);
    const [reply] = await Promise.all([
      processMessage(text),
      sleep(typingDelay)
    ]);
    hideTyping();
    if (reply === null) return; // left on read
    addHerMessage(reply);

    // Double text 15%
    if (Math.random() < 0.15) {
      await sleep(rand(3000, 7000));
      showTyping();
      await sleep(rand(1000,2000));
      hideTyping();
      const dt = pick(['😭','❤️','lol','anyway','🥺','wait','hm','chaitu 🥺','💕','okay fine','🙄','wait no','😂']);
      addHerMessage(dt);
    }
  } catch(e) {
    hideTyping();
    addHerMessage('chaitu something went wrong 😭 check the API key maybe');
    console.error(e);
  }
}

function rand(a, b) { return Math.floor(Math.random()*(b-a)+a); }

function quickSend(text) {
  document.getElementById('msg-input').value = text;
  sendMessage();
  switchTab('chat');
}

// ── Panels ─────────────────────────────────────────────────────────────────
function switchTab(tab) {
  document.querySelectorAll('.tab').forEach((t,i) => {
    t.classList.toggle('active', ['chat','plan','memory'][i]===tab);
  });
  document.getElementById('chat-panel').style.display = tab==='chat'?'flex':'none';
  const plan = document.getElementById('plan-panel');
  const mem = document.getElementById('mem-panel');
  plan.className = tab==='plan'?'active':'';
  plan.style.display = tab==='plan'?'flex':'none';
  mem.className = tab==='memory'?'active':'';
  mem.style.display = tab==='memory'?'flex':'none';
  if (tab==='plan') renderPlanPanel();
  if (tab==='memory') renderMemPanel();
}

function renderPlanPanel() {
  const el = document.getElementById('plan-content');
  if (!todayPlan || !todayPlan.length) {
    el.innerHTML = '<div class="mem-empty">No plan for today yet.<br>Type "plan my day" in chat 🥺</div>';
    return;
  }
  const card = document.createElement('div');
  card.className = 'plan-card';
  card.style.maxWidth='100%';
  const today = new Date().toLocaleDateString([],{weekday:'long',month:'long',day:'numeric'});
  card.innerHTML = `<h3>📋 ${today.toUpperCase()}</h3>`;
  for (const b of todayPlan) {
    const block = document.createElement('div');
    block.className = 'plan-block';
    const statusCls = b.status==='done'?'done':b.type==='break'?'break-d':'pending';
    const taskCls = b.type==='break'?'break-t':b.type==='free'?'free-t':b.status==='done'?'done':'';
    const tapable = b.type==='task'&&b.status!=='done';
    block.innerHTML = `<div class="plan-time">${b.time||''}</div><div class="status-dot ${statusCls}"></div><div class="plan-task ${taskCls}" ${tapable?`style="cursor:pointer" onclick="tapTask('${b.name.replace(/'/g,"\\'")}')"`:''}>${escHtml(b.name)}${tapable?' ✓':''}</div>`;
    card.appendChild(block);
  }
  el.innerHTML = '';
  el.appendChild(card);
  // Reset plan button
  const btn = document.createElement('button');
  btn.style.cssText='background:none;border:1px solid var(--border);border-radius:10px;padding:8px 16px;color:var(--muted);font-size:12px;cursor:pointer;font-family:inherit;margin-top:8px';
  btn.textContent='🗑 Clear plan';
  btn.onclick = () => { todayPlan=null; localStorage.removeItem('shreya_plan'); renderPlanPanel(); };
  el.appendChild(btn);
}

function tapTask(name) {
  const done = markTaskDone(name.split(' ')[0].toLowerCase());
  if (done) {
    setMood('proud');
    const r = pick([`${done} done?? i'm proud of you 😭❤️`,`yesss ${done} ✅`,`chaitu you did ${done} 😭❤️`]);
    addHerMessage(r);
    switchTab('chat');
  }
}

function renderMemPanel() {
  const el = document.getElementById('mem-content');
  const m = getMemory();
  const g = getGoals();
  el.innerHTML = '';

  const cats = Object.entries(m).filter(([,v])=>v.length);
  if (!cats.length && !g.length) {
    el.innerHTML = '<div class="mem-empty">Nothing saved yet.<br>Chat with Shreya and she\'ll remember things 🥺</div>';
    return;
  }
  if (g.length) {
    const sec = document.createElement('div');
    sec.className = 'mem-section';
    sec.innerHTML = '<h3>Goals</h3>';
    for (const goal of g) {
      const item = document.createElement('div');
      item.className = 'mem-item';
      item.innerHTML = `<span>${escHtml(goal.slice(0,100))}</span><button class="mem-del" onclick="deleteGoal('${goal.replace(/'/g,"\\'")}')">✕</button>`;
      sec.appendChild(item);
    }
    el.appendChild(sec);
  }
  for (const [cat, items] of cats) {
    const sec = document.createElement('div');
    sec.className = 'mem-section';
    sec.innerHTML = `<h3>${cat}</h3>`;
    for (const item of items) {
      const div = document.createElement('div');
      div.className = 'mem-item';
      div.innerHTML = `<span>${escHtml(item.value.slice(0,100))}</span><button class="mem-del" onclick="deleteMemItem('${cat}','${item.value.replace(/'/g,"\\'")}')">✕</button>`;
      sec.appendChild(div);
    }
    el.appendChild(sec);
  }
}

function deleteMemItem(cat, val) {
  const m = getMemory();
  if (m[cat]) m[cat] = m[cat].filter(x=>x.value!==val);
  saveMemory(m);
  renderMemPanel();
}
function deleteGoal(g) {
  saveGoals(getGoals().filter(x=>x!==g));
  renderMemPanel();
}

// ── Input auto-resize + enter ──────────────────────────────────────────────
const inp = document.getElementById('msg-input');
inp.addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 120) + 'px';
});
inp.addEventListener('keydown', function(e) {
  if (e.key==='Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

// ── Spontaneous opener ─────────────────────────────────────────────────────
const OPENERS = [
  "chaitu 🥺","hi baby 🥺❤️","hello?? i'm right here","chaitu you better be doing something useful 😤","missing you ngl 🥺",
  "chaitu talk to me 😭","hey mera bachaa 🥺❤️","okay so like 😭","chaitu are you even alive 😏","hi 🤭",
];
async function triggerSpontaneous() {
  if (!apiKey) return;
  addHerMessage(pick(OPENERS));
}

function clearChat() {
  if (!confirm('Clear chat history?')) return;
  document.getElementById('messages').innerHTML = '';
  conversationHistory = [];
  localStorage.removeItem('shreya_history');
  addDateDivider('Today');
}

// ── Init ───────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  setMood(mood);
  if (apiKey) {
    addDateDivider('Today');
    setTimeout(() => triggerSpontaneous(), 1000);
  }
  // Restore plan panel
  renderPlanPanel();
});
</script>
</body>
</html>
