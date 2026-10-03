<!DOCTYPE html>
<html lang="en" class="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LLM Observability</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
:root { --bg: #fafbfc; --card: #fff; --border: #e2e8f0; --text: #0a0e1a; --muted: #64748b; --subtle: #f1f5f9; }
html.dark { --bg: #05070d; --card: #0f1420; --border: #1e2536; --text: #e6edf3; --muted: #8892a6; --subtle: #121826; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; transition: background 0.3s, color 0.3s; }
.mono { font-family: monospace; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 24px; }
.grad { background: linear-gradient(135deg, #6366f1, #8b5cf6, #ec4899); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.header { padding: 16px 32px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; background: var(--card); }
.btn { padding: 8px 16px; border-radius: 10px; border: 1px solid var(--border); background: var(--card); color: var(--text); cursor: pointer; font-weight: 600; }
.btn-primary { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; border: none; }
.main { max-width: 1280px; margin: 0 auto; padding: 32px; }
.grid4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }
.metric { font-size: 32px; font-weight: 900; margin-top: 8px; }
.label { font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--muted); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 12px 24px; font-size: 11px; text-transform: uppercase; color: var(--muted); background: var(--subtle); border-bottom: 1px solid var(--border); }
td { padding: 14px 24px; border-bottom: 1px solid var(--border); }
.chat-fab { position: fixed; bottom: 28px; right: 28px; width: 60px; height: 60px; border-radius: 50%; background: linear-gradient(135deg, #6366f1, #8b5cf6, #ec4899); border: none; color: white; font-size: 24px; cursor: pointer; z-index: 90; box-shadow: 0 12px 32px -8px rgba(99,102,241,0.6); }
.chat-panel { position: fixed; bottom: 100px; right: 28px; width: 380px; height: 560px; background: var(--card); border: 1px solid var(--border); border-radius: 20px; box-shadow: 0 24px 64px rgba(0,0,0,0.3); z-index: 90; display: none; flex-direction: column; overflow: hidden; }
.chat-panel.active { display: flex; }
.chat-header { padding: 16px; background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; font-weight: 700; }
.chat-msgs { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.msg { max-width: 85%; padding: 10px 14px; border-radius: 14px; font-size: 13px; line-height: 1.5; }
.msg-bot { background: var(--subtle); align-self: flex-start; }
.msg-user { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; align-self: flex-end; }
.chat-input { padding: 12px; border-top: 1px solid var(--border); display: flex; gap: 8px; }
.chat-input input { flex: 1; padding: 10px; border-radius: 10px; border: 1px solid var(--border); background: var(--card); color: var(--text); }
.chat-input button { padding: 10px 18px; border-radius: 10px; background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; border: none; cursor: pointer; font-weight: 600; }
.toast { position: fixed; bottom: 24px; right: 24px; background: #0f172a; color: white; padding: 12px 20px; border-radius: 12px; font-size: 13px; z-index: 200; }
</style>
</head>
<body>

<div class="header">
  <div style="display:flex;align-items:center;gap:12px">
    <div style="width:40px;height:40px;border-radius:12px;background:linear-gradient(135deg,#6366f1,#8b5cf6);display:flex;align-items:center;justify-content:center;color:white;font-weight:900">L</div>
    <div>
      <div style="font-weight:700">LLM Observability</div>
      <div style="font-size:11px;color:var(--muted)" id="liveStatus">Live</div>
    </div>
  </div>
  <div style="display:flex;gap:8px">
    <button class="btn" onclick="toggleTheme()" id="themeBtn">Dark</button>
    <button class="btn btn-primary" onclick="gen()">Generate</button>
  </div>
</div>

<div class="main">
  <h1 style="font-size:44px;font-weight:900;letter-spacing:-1px;margin-bottom:8px"><span class="grad">Real-time insights</span></h1>
  <p style="color:var(--muted);margin-bottom:24px">Powered by Groq (llama-3.3-70b)</p>

  <div class="grid4">
    <div class="card"><div class="label">Total Requests</div><div class="metric" id="mReq">0</div></div>
    <div class="card"><div class="label">Total Cost</div><div class="metric" id="mCost">$0.00</div></div>
    <div class="card"><div class="label">Total Tokens</div><div class="metric" id="mTok">0</div></div>
    <div class="card"><div class="label">Avg Latency</div><div class="metric" id="mLat">0ms</div></div>
  </div>

  <div class="grid2">
    <div class="card"><h3 style="margin-bottom:16px">Cost by Feature</h3><canvas id="c1" style="max-height:260px"></canvas></div>
    <div class="card"><h3 style="margin-bottom:16px">Cost by Model</h3><canvas id="c2" style="max-height:260px"></canvas></div>
  </div>

  <div class="card" style="padding:0;overflow:hidden">
    <div style="padding:20px 24px;border-bottom:1px solid var(--border)"><h3>Recent Traces</h3></div>
    <table><thead><tr><th>Trace ID</th><th>Model</th><th>Feature</th><th>Tokens</th><th>Cost</th><th>Latency</th></tr></thead><tbody id="tbody"></tbody></table>
    <div id="empty" style="padding:60px;text-align:center;color:var(--muted)">No traces yet. Click Generate.</div>
  </div>
</div>

<button class="chat-fab" onclick="toggleChat()">💬</button>
<div class="chat-panel" id="chatPanel">
  <div class="chat-header">Observability Copilot</div>
  <div class="chat-msgs" id="chatMsgs"><div class="msg msg-bot">Hi! Ask me about your traces.</div></div>
  <div class="chat-input">
    <input id="chatInput" placeholder="Ask..." onkeydown="if(event.key==='Enter')sendChat()">
    <button onclick="sendChat()">Send</button>
  </div>
</div>

<script>
var c1, c2, palette = ['#6366f1','#8b5cf6','#ec4899','#14b8a6','#f59e0b','#ef4444'];
function initTheme() { var s = localStorage.getItem('theme') || 'light'; document.documentElement.className = s; document.getElementById('themeBtn').textContent = s === 'dark' ? 'Light' : 'Dark'; }
function toggleTheme() { var c = document.documentElement.className === 'dark' ? 'light' : 'dark'; document.documentElement.className = c; localStorage.setItem('theme', c); document.getElementById('themeBtn').textContent = c === 'dark' ? 'Light' : 'Dark'; load(); }
function toast(m) { var el = document.createElement('div'); el.className = 'toast'; el.textContent = m; document.body.appendChild(el); setTimeout(function(){ el.remove(); }, 4000); }

async function load() {
  try {
    var r = await Promise.all([fetch('/api/costs').then(function(x){ return x.json(); }), fetch('/api/spans').then(function(x){ return x.json(); })]);
    var costs = r[0], sp = r[1].spans || [];
    var cf = {}, cm = {};
    sp.forEach(function(x){ cf[x.feature||'?'] = (cf[x.feature||'?']||0) + (x.cost_usd||0); cm[x.model||'?'] = (cm[x.model||'?']||0) + (x.cost_usd||0); });
    var tc = 0; for (var k in cf) tc += cf[k];
    var tt = 0; sp.forEach(function(x){ tt += (x.input_tokens||0) + (x.output_tokens||0); });
    var al = sp.length ? sp.reduce(function(a,x){ return a + (x.duration_ms||0); }, 0) / sp.length : 0;
    document.getElementById('mReq').textContent = sp.length;
    document.getElementById('mCost').textContent = '$' + tc.toFixed(4);
    document.getElementById('mTok').textContent = tt;
    document.getElementById('mLat').textContent = al.toFixed(0) + 'ms';
    document.getElementById('liveStatus').textContent = 'Live · ' + sp.length + ' traces';
    document.getElementById('empty').style.display = sp.length === 0 ? 'block' : 'none';
    var dark = document.documentElement.className === 'dark';
    if (c1) c1.destroy();
    c1 = new Chart(document.getElementById('c1'), { type: 'bar', data: { labels: Object.keys(cf), datasets: [{ data: Object.values(cf), backgroundColor: palette, borderRadius: 6 }] }, options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: dark ? '#8892a6' : '#64748b' } }, y: { ticks: { color: dark ? '#c9d1d9' : '#334155' } } } } });
    if (c2) c2.destroy();
    c2 = new Chart(document.getElementById('c2'), { type: 'doughnut', data: { labels: Object.keys(cm), datasets: [{ data: Object.values(cm), backgroundColor: palette, borderWidth: 3, borderColor: dark ? '#0f1420' : '#fff' }] }, options: { responsive: true, maintainAspectRatio: false, cutout: '60%', plugins: { legend: { position: 'bottom', labels: { color: dark ? '#c9d1d9' : '#334155' } } } } });
    var h = '';
    sp.slice(-15).reverse().forEach(function(x){
      h += '<tr><td class="mono" style="color:var(--muted)">' + (x.trace_id||'').slice(0,14) + '</td><td style="font-weight:600">' + (x.model||'?') + '</td><td>' + (x.feature||'-') + '</td><td>' + ((x.input_tokens||0)+(x.output_tokens||0)) + '</td><td class="mono">$' + (x.cost_usd||0).toFixed(6) + '</td><td>' + (x.duration_ms||0).toFixed(0) + 'ms</td></tr>';
    });
    document.getElementById('tbody').innerHTML = h;
  } catch (e) { console.error(e); }
}

async function gen() {
  toast('Generating 10 real traces via Groq...');
  try {
    var res = await fetch('/api/seed-real', { method: 'POST' });
    var data = await res.json();
    toast(data.generated + ' traces generated');
    load();
  } catch (e) { toast('Error: ' + e.message); }
}

function toggleChat() { document.getElementById('chatPanel').classList.toggle('active'); }
function addMsg(text, user) { var c = document.getElementById('chatMsgs'); var d = document.createElement('div'); d.className = 'msg ' + (user ? 'msg-user' : 'msg-bot'); d.innerHTML = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>'); c.appendChild(d); c.scrollTop = c.scrollHeight; }
async function sendChat() {
  var i = document.getElementById('chatInput'), m = i.value.trim();
  if (!m) return;
  addMsg(m, true); i.value = '';
  addMsg('...', false);
  try {
    var r = await fetch('/api/chat', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({message: m}) });
    var d = await r.json();
    document.getElementById('chatMsgs').lastChild.remove();
    addMsg(d.reply, false);
  } catch (e) { addMsg('Error', false); }
}

initTheme();
load();
setInterval(load, 3000);
</script>
</body>
</html>
