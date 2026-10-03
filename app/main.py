from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from app.ingest.otlp_endpoint import router as ingest_router
from app.api.routes_traces import router as traces_router
from app.storage.memory_store import MemoryStore

app = FastAPI(title="LLM Observability Platform")
app.include_router(ingest_router)
app.include_router(traces_router, prefix="/api")

store = MemoryStore()


class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
def chat(req: ChatRequest):
    import time
    import uuid
    import requests as http_requests
    from openai import OpenAI

    msg = req.message.strip()
    spans = store.get_all_spans()
    costs_f = store.get_cost_by_feature()
    costs_m = store.get_cost_by_model()

    if not spans:
        return {"reply": "No traces yet. Click 'Generate' to populate, then ask me anything."}

    total_cost = sum(costs_f.values())
    total_tokens = sum((s.get("input_tokens", 0) + s.get("output_tokens", 0)) for s in spans)
    avg_lat = sum(s.get("duration_ms", 0) for s in spans) / len(spans)

    top_features = sorted(costs_f.items(), key=lambda x: -x[1])[:5]
    top_models = sorted(costs_m.items(), key=lambda x: -x[1])[:5]

    model_lat = {}
    for s in spans:
        m = s.get("model", "?")
        model_lat.setdefault(m, []).append(s.get("duration_ms", 0))
    lat_by_model = sorted(
        [(m, sum(v) / len(v)) for m, v in model_lat.items()],
        key=lambda x: -x[1],
    )

    recent = spans[-10:]
    recent_lines = "\n".join([
        f"- {s.get('trace_id','')[:12]} | {s.get('model','?')} | {s.get('feature','-')} | "
        f"{s.get('input_tokens',0)+s.get('output_tokens',0)} tokens | "
        f"${s.get('cost_usd',0):.6f} | {s.get('duration_ms',0):.0f}ms"
        for s in recent
    ])

    context = f"""You are an observability copilot for an LLM tracing platform.

LIVE DATA:
- Total traces: {len(spans)}
- Total cost: ${total_cost:.4f}
- Total tokens: {total_tokens:,}
- Avg latency: {avg_lat:.0f}ms

Top features by cost:
{chr(10).join(f'  {f}: ${c:.4f}' for f, c in top_features)}

Models by cost:
{chr(10).join(f'  {m}: ${c:.4f}' for m, c in top_models)}

Latency by model:
{chr(10).join(f'  {m}: {l:.0f}ms' for m, l in lat_by_model)}

Recent traces:
{recent_lines}

INSTRUCTIONS:
- Answer using live data above.
- Be concise (2-4 sentences).
- Use markdown bold (**text**) for numbers.
- If asked for optimization, base on actual data."""

    start = time.time()
    try:
        client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
        response = client.chat.completions.create(
            model="llama3.2",
            messages=[
                {"role": "system", "content": context},
                {"role": "user", "content": msg},
            ],
            temperature=0.3,
            max_tokens=250,
        )
        reply = response.choices[0].message.content.strip()

        # Self-observability: log this chat as a trace
        latency_ms = (time.time() - start) * 1000
        usage = response.usage
        in_tok = usage.prompt_tokens if usage else 0
        out_tok = usage.completion_tokens if usage else 0

        trace_payload = {
            "resourceSpans": [{
                "scopeSpans": [{
                    "spans": [{
                        "traceId": "trace-" + uuid.uuid4().hex[:12],
                        "spanId": "span-" + uuid.uuid4().hex[:8],
                        "name": "ollama.chat",
                        "startTimeUnixNano": str(int((time.time() - latency_ms/1000) * 1e9)),
                        "endTimeUnixNano": str(int(time.time() * 1e9)),
                        "attributes": [
                            {"key": "gen_ai.system", "value": {"stringValue": "ollama"}},
                            {"key": "gen_ai.request.model", "value": {"stringValue": "llama3.2"}},
                            {"key": "gen_ai.usage.input_tokens", "value": {"intValue": str(in_tok)}},
                            {"key": "gen_ai.usage.output_tokens", "value": {"intValue": str(out_tok)}},
                            {"key": "feature", "value": {"stringValue": "copilot-chat"}},
                            {"key": "llm.prompts", "value": {"stringValue": msg[:500]}},
                            {"key": "llm.completions", "value": {"stringValue": reply[:500]}},
                        ]
                    }]
                }]
            }]
        }
        try:
            http_requests.post("http://localhost:8000/v1/traces", json=trace_payload, timeout=3)
        except Exception:
            pass

        return {"reply": reply}

    except Exception:
        if costs_f:
            top_f = max(costs_f.items(), key=lambda x: x[1])
            return {"reply": f"**Summary**\n- Traces: {len(spans)}\n- Cost: ${total_cost:.4f}\n- Avg latency: {avg_lat:.0f}ms\n- Top feature: **{top_f[0]}**\n\n(Ollama offline)"}
        return {"reply": "Error connecting to Ollama."}


@app.post("/api/seed-real")
def seed_real_data():
    """Generate 10 REAL Ollama traces with varied prompts."""
    import time
    import uuid
    import requests as http_requests
    from openai import OpenAI

    prompts = [
        ("What is observability in LLMs?", "customer-support"),
        ("Explain RAG in one sentence.", "summarization"),
        ("What is a token in LLMs?", "chat"),
        ("How does OpenTelemetry work?", "code-review"),
        ("What is prompt injection?", "search"),
        ("Difference between GPT-4 and Claude?", "chat"),
        ("What are embeddings?", "summarization"),
        ("Explain fine-tuning briefly.", "code-review"),
        ("What is an AI agent?", "chat"),
        ("How does vector search work?", "search"),
    ]

    client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
    count = 0

    for prompt, feature in prompts:
        try:
            start = time.time()
            response = client.chat.completions.create(
                model="llama3.2",
                messages=[
                    {"role": "system", "content": "Answer in 1-2 sentences."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=100,
            )
            latency_ms = (time.time() - start) * 1000
            completion = response.choices[0].message.content.strip()
            usage = response.usage

            trace_payload = {
                "resourceSpans": [{
                    "scopeSpans": [{
                        "spans": [{
                            "traceId": "trace-" + uuid.uuid4().hex[:12],
                            "spanId": "span-" + uuid.uuid4().hex[:8],
                            "name": "ollama.chat",
                            "startTimeUnixNano": str(int((time.time() - latency_ms/1000) * 1e9)),
                            "endTimeUnixNano": str(int(time.time() * 1e9)),
                            "attributes": [
                                {"key": "gen_ai.system", "value": {"stringValue": "ollama"}},
                                {"key": "gen_ai.request.model", "value": {"stringValue": "llama3.2"}},
                                {"key": "gen_ai.usage.input_tokens", "value": {"intValue": str(usage.prompt_tokens if usage else 0)}},
                                {"key": "gen_ai.usage.output_tokens", "value": {"intValue": str(usage.completion_tokens if usage else 0)}},
                                {"key": "feature", "value": {"stringValue": feature}},
                                {"key": "llm.prompts", "value": {"stringValue": prompt}},
                                {"key": "llm.completions", "value": {"stringValue": completion[:500]}},
                            ]
                        }]
                    }]
                }]
            }

            http_requests.post("http://localhost:8000/v1/traces", json=trace_payload, timeout=3)
            count += 1
        except Exception as e:
            print(f"[seed] error: {e}")

    return {"status": "ok", "generated": count}


@app.get("/api/health")
def health():
    return {"status": "healthy"}


HTML_PAGE = """<!DOCTYPE html>
<html lang="en" class="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LLM Observability</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  :root { --bg: #fafbfc; --card: rgba(255,255,255,0.85); --card-solid: #ffffff; --border: rgba(226,232,240,0.9); --text: #0a0e1a; --muted: #64748b; --subtle: #f1f5f9; --shadow: 0 1px 3px rgba(0,0,0,0.04), 0 8px 24px -8px rgba(15,23,42,0.08); }
  html.dark { --bg: #05070d; --card: rgba(15,20,32,0.7); --card-solid: #0f1420; --border: rgba(30,37,54,0.9); --text: #e6edf3; --muted: #8892a6; --subtle: #121826; --shadow: 0 1px 3px rgba(0,0,0,0.3), 0 8px 32px -8px rgba(0,0,0,0.5); }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); transition: background 0.4s, color 0.4s; min-height: 100vh; -webkit-font-smoothing: antialiased; }
  .mono { font-family: 'JetBrains Mono', monospace; }
  .orb { position: fixed; border-radius: 50%; filter: blur(100px); opacity: 0.35; pointer-events: none; z-index: 0; }
  .orb-1 { width: 500px; height: 500px; background: radial-gradient(circle, #6366f1, transparent 70%); top: -200px; left: -100px; animation: float1 20s ease-in-out infinite; }
  .orb-2 { width: 400px; height: 400px; background: radial-gradient(circle, #ec4899, transparent 70%); top: 40%; right: -150px; animation: float2 25s ease-in-out infinite; }
  .orb-3 { width: 450px; height: 450px; background: radial-gradient(circle, #14b8a6, transparent 70%); bottom: -200px; left: 30%; animation: float3 30s ease-in-out infinite; }
  @keyframes float1 { 0%,100% { transform: translate(0,0); } 50% { transform: translate(80px, 60px); } }
  @keyframes float2 { 0%,100% { transform: translate(0,0); } 50% { transform: translate(-100px, 80px); } }
  @keyframes float3 { 0%,100% { transform: translate(0,0); } 50% { transform: translate(60px, -80px); } }
  html.dark .orb { opacity: 0.15; }
  .grid-bg { position: fixed; inset: 0; z-index: 0; pointer-events: none; background-image: linear-gradient(rgba(99,102,241,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(99,102,241,0.04) 1px, transparent 1px); background-size: 48px 48px; mask-image: radial-gradient(ellipse at center, black 20%, transparent 80%); }
  header, main { position: relative; z-index: 1; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 20px; backdrop-filter: blur(20px) saturate(180%); box-shadow: var(--shadow); transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); position: relative; overflow: hidden; }
  .card:hover { transform: translateY(-3px); box-shadow: 0 4px 6px rgba(0,0,0,0.04), 0 20px 48px -12px rgba(99,102,241,0.25); border-color: rgba(99,102,241,0.3); }
  .grad-text { background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #ec4899 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; background-size: 200% auto; animation: gradShift 6s ease infinite; }
  @keyframes gradShift { 0%,100% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } }
  .pulse-dot { animation: pulse 2s infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(16,185,129,0.7); } 50% { opacity: 0.9; box-shadow: 0 0 0 6px rgba(16,185,129,0); } }
  .btn-primary { background: linear-gradient(135deg, #6366f1, #8b5cf6); background-size: 200% 200%; transition: all 0.3s; position: relative; overflow: hidden; }
  .btn-primary::before { content: ''; position: absolute; top: 0; left: -100%; width: 100%; height: 100%; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent); transition: left 0.5s; }
  .btn-primary:hover { background-position: 100% 0; box-shadow: 0 8px 24px -4px rgba(99,102,241,0.5); transform: translateY(-1px); }
  .btn-primary:hover::before { left: 100%; }
  .btn-ghost { background: var(--card-solid); border: 1px solid var(--border); transition: all 0.2s; }
  .btn-ghost:hover { border-color: #6366f1; color: #6366f1; transform: translateY(-1px); }
  select, input { background: var(--card-solid); color: var(--text); border: 1px solid var(--border); transition: all 0.2s; }
  select:focus, input:focus { outline: none; border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,0.1); }
  .table-header { background: var(--subtle); }
  .row-hover { cursor: pointer; transition: background 0.15s; }
  .row-hover:hover { background: var(--subtle); }
  .metric-value { background: linear-gradient(180deg, var(--text) 0%, var(--muted) 130%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; font-variant-numeric: tabular-nums; }
  .modal-backdrop { position: fixed; inset: 0; background: rgba(5,7,13,0.7); backdrop-filter: blur(8px); z-index: 100; display: none; align-items: center; justify-content: center; padding: 20px; animation: fadeIn 0.2s; }
  .modal-backdrop.active { display: flex; }
  .modal-content { background: var(--card-solid); border: 1px solid var(--border); border-radius: 20px; max-width: 720px; width: 100%; max-height: 90vh; overflow-y: auto; box-shadow: 0 24px 64px -12px rgba(0,0,0,0.4); animation: modalIn 0.3s cubic-bezier(0.4, 0, 0.2, 1); }
  @keyframes modalIn { from { opacity: 0; transform: scale(0.94) translateY(20px); } to { opacity: 1; transform: scale(1) translateY(0); } }
  @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
  .sparkline { height: 44px; width: 100%; overflow: visible; }
  .badge-alert { position: absolute; top: -3px; right: -3px; min-width: 18px; height: 18px; padding: 0 4px; border-radius: 9px; background: #ef4444; color: white; font-size: 10px; font-weight: 700; display: flex; align-items: center; justify-content: center; border: 2px solid var(--card-solid); }
  .toast { position: fixed; bottom: 24px; right: 24px; background: linear-gradient(135deg, #0f172a, #1e293b); color: white; padding: 14px 22px; border-radius: 14px; font-size: 14px; font-weight: 500; z-index: 200; animation: slideIn 0.4s cubic-bezier(0.4, 0, 0.2, 1); box-shadow: 0 16px 48px -8px rgba(0,0,0,0.5); border: 1px solid rgba(99,102,241,0.3); }
  @keyframes slideIn { from { transform: translateX(400px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
  .key-hint { display: inline-flex; align-items: center; justify-content: center; min-width: 22px; height: 22px; padding: 0 6px; border-radius: 6px; background: var(--subtle); border: 1px solid var(--border); font-size: 11px; font-weight: 600; font-family: 'JetBrains Mono', monospace; }
  .header-blur { background: rgba(255,255,255,0.75); backdrop-filter: blur(24px) saturate(180%); border-bottom: 1px solid var(--border); }
  html.dark .header-blur { background: rgba(5,7,13,0.75); }
  .fade-in { animation: fadeInUp 0.5s cubic-bezier(0.4, 0, 0.2, 1); }
  @keyframes fadeInUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
  .chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 20px; background: rgba(99,102,241,0.1); border: 1px solid rgba(99,102,241,0.2); font-size: 11px; font-weight: 600; color: #6366f1; }
  .chat-fab { position: fixed; bottom: 28px; right: 28px; width: 60px; height: 60px; border-radius: 50%; background: linear-gradient(135deg, #6366f1, #8b5cf6, #ec4899); display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 90; box-shadow: 0 12px 32px -8px rgba(99,102,241,0.6), 0 0 0 0 rgba(99,102,241,0.5); transition: all 0.3s; animation: fabPulse 2.5s infinite; border: none; }
  .chat-fab:hover { transform: scale(1.1) rotate(-5deg); }
  .chat-fab.active { transform: scale(0.9) rotate(90deg); animation: none; }
  @keyframes fabPulse { 0%,100% { box-shadow: 0 12px 32px -8px rgba(99,102,241,0.6), 0 0 0 0 rgba(99,102,241,0.5); } 50% { box-shadow: 0 12px 32px -8px rgba(99,102,241,0.6), 0 0 0 14px rgba(99,102,241,0); } }
  .chat-panel { position: fixed; bottom: 100px; right: 28px; width: 400px; height: 600px; max-height: calc(100vh - 140px); background: var(--card-solid); border: 1px solid var(--border); border-radius: 22px; box-shadow: 0 32px 80px -12px rgba(0,0,0,0.4); z-index: 90; display: flex; flex-direction: column; overflow: hidden; transform: translateY(20px) scale(0.95); opacity: 0; pointer-events: none; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); }
  .chat-panel.active { transform: translateY(0) scale(1); opacity: 1; pointer-events: all; }
  .chat-header { padding: 18px 20px; background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; display: flex; align-items: center; gap: 12px; position: relative; overflow: hidden; }
  .chat-avatar { width: 38px; height: 38px; border-radius: 12px; background: rgba(255,255,255,0.2); display: flex; align-items: center; justify-content: center; position: relative; z-index: 1; }
  .chat-messages { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 12px; }
  .chat-messages::-webkit-scrollbar { width: 6px; }
  .chat-messages::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
  .msg { max-width: 85%; padding: 12px 16px; border-radius: 16px; font-size: 13.5px; line-height: 1.5; animation: msgIn 0.3s ease; word-wrap: break-word; }
  @keyframes msgIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
  .msg-bot { background: var(--subtle); color: var(--text); border-bottom-left-radius: 4px; align-self: flex-start; }
  .msg-user { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; border-bottom-right-radius: 4px; align-self: flex-end; }
  .msg strong { font-weight: 700; }
  .msg code { background: rgba(99,102,241,0.15); padding: 1px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace; font-size: 12px; }
  .chat-suggestions { padding: 0 20px 12px; display: flex; flex-wrap: wrap; gap: 6px; }
  .suggestion { padding: 6px 12px; border-radius: 20px; background: rgba(99,102,241,0.1); border: 1px solid rgba(99,102,241,0.2); color: #6366f1; font-size: 11.5px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
  .suggestion:hover { background: rgba(99,102,241,0.2); transform: translateY(-1px); }
  .chat-input-bar { padding: 14px 16px; border-top: 1px solid var(--border); display: flex; gap: 8px; align-items: center; }
  .chat-input-bar input { flex: 1; padding: 10px 14px; border-radius: 12px; font-size: 13.5px; }
  .chat-send { width: 38px; height: 38px; border-radius: 12px; background: linear-gradient(135deg, #6366f1, #8b5cf6); border: none; color: white; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.2s; }
  .chat-send:hover { transform: scale(1.05); box-shadow: 0 4px 16px -2px rgba(99,102,241,0.5); }
  .typing { display: flex; gap: 4px; padding: 12px 16px; align-self: flex-start; background: var(--subtle); border-radius: 16px; border-bottom-left-radius: 4px; }
  .typing span { width: 6px; height: 6px; border-radius: 50%; background: var(--muted); animation: typing 1.4s infinite; }
  .typing span:nth-child(2) { animation-delay: 0.2s; }
  .typing span:nth-child(3) { animation-delay: 0.4s; }
  @keyframes typing { 0%,60%,100% { transform: translateY(0); opacity: 0.4; } 30% { transform: translateY(-4px); opacity: 1; } }
  @media (max-width: 480px) {
    .chat-panel { right: 12px; left: 12px; width: auto; bottom: 92px; height: calc(100vh - 140px); }
    .chat-fab { bottom: 20px; right: 20px; width: 54px; height: 54px; }
  }
</style>
<script>tailwind.config = { darkMode: 'class', theme: { extend: { fontFamily: { sans: ['Inter','sans-serif'], mono: ['JetBrains Mono','monospace'] } } } }</script>
</head>
<body>

<div class="orb orb-1"></div>
<div class="orb orb-2"></div>
<div class="orb orb-3"></div>
<div class="grid-bg"></div>

<header class="header-blur sticky top-0 z-40">
  <div class="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between gap-4">
    <div class="flex items-center gap-3 shrink-0">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 flex items-center justify-center text-white shadow-lg shadow-indigo-500/40">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
      </div>
      <div class="hidden md:block">
        <h1 class="text-base font-bold tracking-tight">LLM Observability</h1>
        <p class="text-xs" style="color: var(--muted);">Real-time tracing</p>
      </div>
    </div>
    <div class="flex-1 max-w-md hidden lg:block">
      <div class="relative">
        <svg class="absolute left-3 top-1/2 -translate-y-1/2" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="color: var(--muted);"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
        <input id="searchInput" type="text" placeholder="Search traces, models, features..." class="w-full pl-10 pr-4 py-2 rounded-xl text-sm" oninput="load()">
      </div>
    </div>
    <div class="flex items-center gap-2 shrink-0">
      <div class="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-full" style="background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.25);">
        <div class="w-2 h-2 rounded-full bg-emerald-500 pulse-dot"></div>
        <span class="text-xs font-bold text-emerald-600" id="liveStatus">Live</span>
      </div>
      <button onclick="openBudgetModal()" class="btn-ghost w-9 h-9 rounded-xl flex items-center justify-center relative" title="Budget">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
        <span id="bellBadge" class="badge-alert" style="display:none;">!</span>
      </button>
      <button onclick="toggleTheme()" class="btn-ghost w-9 h-9 rounded-xl flex items-center justify-center" title="Theme (T)">
        <svg id="iconSun" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="display:none;"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>
        <svg id="iconMoon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
      </button>
      <button onclick="gen()" class="btn-primary px-4 h-9 rounded-xl text-white text-sm font-bold"><span class="relative z-10">Generate</span></button>
    </div>
  </div>
</header>

<main class="max-w-7xl mx-auto px-6 py-10 fade-in">

  <div class="flex flex-wrap items-end justify-between gap-4 mb-8">
    <div>
      <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full mb-4" style="background: rgba(99,102,241,0.1); border: 1px solid rgba(99,102,241,0.2);">
        <div class="w-1.5 h-1.5 rounded-full bg-indigo-500 pulse-dot"></div>
        <span class="text-xs font-bold tracking-wider" style="color: #6366f1;">LIVE MONITORING</span>
      </div>
      <h2 class="text-4xl md:text-5xl font-black tracking-tighter leading-none"><span class="grad-text">Real-time insights</span></h2>
      <p class="text-base mt-3 max-w-xl" style="color: var(--muted);">Track every prompt, token, and dollar across your LLM applications. Powered by local Llama 3.2 via Ollama.</p>
    </div>
    <div class="flex gap-2">
      <button onclick="exportData('csv')" class="btn-ghost px-4 py-2.5 rounded-xl text-xs font-semibold">Export CSV</button>
      <button onclick="exportData('json')" class="btn-ghost px-4 py-2.5 rounded-xl text-xs font-semibold">Export JSON</button>
    </div>
  </div>

  <div class="flex flex-wrap items-center gap-3 mb-8">
    <div class="chip"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M3 6h18M3 12h18M3 18h18"/></svg>FILTERS</div>
    <select id="filterModel" onchange="load()" class="px-3 py-1.5 rounded-xl text-sm font-medium">
      <option value="all">All models</option>
      <option value="llama3.2">Llama 3.2</option>
      <option value="gpt-4o">GPT-4o</option>
      <option value="claude-3-5-sonnet">Claude 3.5 Sonnet</option>
    </select>
    <select id="filterFeature" onchange="load()" class="px-3 py-1.5 rounded-xl text-sm font-medium">
      <option value="all">All features</option>
      <option value="customer-support">Customer Support</option>
      <option value="code-review">Code Review</option>
      <option value="summarization">Summarization</option>
      <option value="chat">Chat</option>
      <option value="search">Search</option>
      <option value="copilot-chat">Copilot Chat</option>
    </select>
    <select id="filterTime" onchange="load()" class="px-3 py-1.5 rounded-xl text-sm font-medium">
      <option value="all">All time</option>
      <option value="1h">Last hour</option>
      <option value="24h">Last 24 hours</option>
      <option value="7d">Last 7 days</option>
    </select>
    <div class="ml-auto text-xs font-semibold mono" style="color: var(--muted);" id="filterInfo">-</div>
  </div>

  <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5 mb-8">
    <div class="card p-6">
      <div class="flex items-center justify-between mb-4">
        <div class="w-12 h-12 rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
        </div>
        <span class="text-xs font-bold px-2.5 py-1 rounded-full" id="trendReq" style="color: var(--muted); background: var(--subtle);">-</span>
      </div>
      <p class="text-xs font-bold uppercase tracking-widest mb-2" style="color: var(--muted);">Total Requests</p>
      <p class="text-4xl font-black metric-value" id="mReq">0</p>
      <svg class="sparkline mt-4" id="spark1" viewBox="0 0 100 44" preserveAspectRatio="none"></svg>
    </div>
    <div class="card p-6">
      <div class="flex items-center justify-between mb-4">
        <div class="w-12 h-12 rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
        </div>
        <span class="text-xs font-bold px-2.5 py-1 rounded-full" id="trendCost" style="color: var(--muted); background: var(--subtle);">-</span>
      </div>
      <p class="text-xs font-bold uppercase tracking-widest mb-2" style="color: var(--muted);">Total Cost</p>
      <p class="text-4xl font-black metric-value" id="mCost">$0.00</p>
      <svg class="sparkline mt-4" id="spark2" viewBox="0 0 100 44" preserveAspectRatio="none"></svg>
    </div>
    <div class="card p-6">
      <div class="flex items-center justify-between mb-4">
        <div class="w-12 h-12 rounded-2xl bg-gradient-to-br from-purple-500 to-pink-600 flex items-center justify-center">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        </div>
        <span class="text-xs font-bold px-2.5 py-1 rounded-full" id="trendTok" style="color: var(--muted); background: var(--subtle);">-</span>
      </div>
      <p class="text-xs font-bold uppercase tracking-widest mb-2" style="color: var(--muted);">Total Tokens</p>
      <p class="text-4xl font-black metric-value" id="mTok">0</p>
      <svg class="sparkline mt-4" id="spark3" viewBox="0 0 100 44" preserveAspectRatio="none"></svg>
    </div>
    <div class="card p-6">
      <div class="flex items-center justify-between mb-4">
        <div class="w-12 h-12 rounded-2xl bg-gradient-to-br from-orange-500 to-red-600 flex items-center justify-center">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
        </div>
        <span class="text-xs font-bold px-2.5 py-1 rounded-full" id="trendLat" style="color: var(--muted); background: var(--subtle);">-</span>
      </div>
      <p class="text-xs font-bold uppercase tracking-widest mb-2" style="color: var(--muted);">Avg Latency</p>
      <p class="text-4xl font-black metric-value" id="mLat">0ms</p>
      <svg class="sparkline mt-4" id="spark4" viewBox="0 0 100 44" preserveAspectRatio="none"></svg>
    </div>
  </div>

  <div class="grid grid-cols-1 lg:grid-cols-2 gap-5 mb-8">
    <div class="card p-6">
      <h3 class="font-bold text-lg mb-1">Cost by Feature</h3>
      <p class="text-xs mb-5" style="color: var(--muted);">Which features drive spend</p>
      <div style="height: 280px;"><canvas id="c1"></canvas></div>
    </div>
    <div class="card p-6">
      <h3 class="font-bold text-lg mb-1">Cost by Model</h3>
      <p class="text-xs mb-5" style="color: var(--muted);">Distribution across providers</p>
      <div style="height: 280px;"><canvas id="c2"></canvas></div>
    </div>
  </div>

  <div class="grid grid-cols-1 lg:grid-cols-2 gap-5 mb-8">
    <div class="card p-6">
      <h3 class="font-bold text-lg mb-1">Top Expensive Traces</h3>
      <p class="text-xs mb-5" style="color: var(--muted);">Highest cost calls</p>
      <div id="topExpensive" class="space-y-2"></div>
    </div>
    <div class="card p-6">
      <h3 class="font-bold text-lg mb-1">Latency Distribution</h3>
      <p class="text-xs mb-5" style="color: var(--muted);">Average by model</p>
      <div style="height: 240px;"><canvas id="c3"></canvas></div>
    </div>
  </div>

  <div class="card overflow-hidden">
    <div class="px-6 py-5 border-b flex items-center justify-between" style="border-color: var(--border);">
      <div>
        <h3 class="font-bold text-lg">Recent Traces</h3>
        <p class="text-xs mt-0.5" style="color: var(--muted);">Click any row for full details</p>
      </div>
      <button onclick="load()" class="btn-ghost px-3 py-1.5 rounded-lg text-xs font-semibold">Refresh</button>
    </div>
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead class="table-header"><tr>
          <th class="text-left px-6 py-3 text-xs font-bold uppercase tracking-widest" style="color: var(--muted);">Trace ID</th>
          <th class="text-left px-6 py-3 text-xs font-bold uppercase tracking-widest" style="color: var(--muted);">Model</th>
          <th class="text-left px-6 py-3 text-xs font-bold uppercase tracking-widest" style="color: var(--muted);">Feature</th>
          <th class="text-left px-6 py-3 text-xs font-bold uppercase tracking-widest" style="color: var(--muted);">Tokens</th>
          <th class="text-left px-6 py-3 text-xs font-bold uppercase tracking-widest" style="color: var(--muted);">Cost</th>
          <th class="text-left px-6 py-3 text-xs font-bold uppercase tracking-widest" style="color: var(--muted);">Latency</th>
        </tr></thead>
        <tbody id="tbody" class="divide-y" style="border-color: var(--border);"></tbody>
      </table>
    </div>
    <div id="empty" class="py-20 text-center">
      <div class="w-16 h-16 rounded-2xl mx-auto mb-4 flex items-center justify-center" style="background: var(--subtle);">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="color: var(--muted);"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
      </div>
      <p class="font-bold">No traces yet</p>
      <p class="text-xs mt-1" style="color: var(--muted);">Click "Generate" to populate via Ollama</p>
    </div>
  </div>

  <div class="mt-10 flex flex-wrap items-center justify-center gap-6 text-xs" style="color: var(--muted);">
    <span class="font-semibold">SHORTCUTS</span>
    <span><span class="key-hint">G</span> Seed</span>
    <span><span class="key-hint">R</span> Refresh</span>
    <span><span class="key-hint">T</span> Theme</span>
    <span><span class="key-hint">C</span> Chat</span>
    <span><span class="key-hint">Esc</span> Close</span>
  </div>

</main>

<button class="chat-fab" id="chatFab" onclick="toggleChat()" title="AI Copilot (C)">
  <svg id="chatIcon" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
</button>

<div class="chat-panel" id="chatPanel">
  <div class="chat-header">
    <div class="chat-avatar">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a2 2 0 0 1 2 2v1a2 2 0 0 1-2 2 2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><rect x="4" y="8" width="16" height="12" rx="3"/><circle cx="9" cy="14" r="1" fill="white"/><circle cx="15" cy="14" r="1" fill="white"/></svg>
    </div>
    <div class="flex-1 relative z-10">
      <p class="font-bold text-sm">Observability Copilot</p>
      <p class="text-xs opacity-80">Powered by Llama 3.2</p>
    </div>
    <button onclick="toggleChat()" class="relative z-10 w-8 h-8 rounded-lg hover:bg-white/10 flex items-center justify-center transition-colors" style="background: transparent; border: none; cursor: pointer;">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
    </button>
  </div>
  <div class="chat-messages" id="chatMessages">
    <div class="msg msg-bot">Hi! I'm your observability copilot. Ask me anything about your LLM traces.</div>
  </div>
  <div class="chat-suggestions" id="chatSuggestions">
    <span class="suggestion" onclick="askSuggestion('What is observability?')">What is observability?</span>
    <span class="suggestion" onclick="askSuggestion('Which feature costs most?')">Top feature</span>
    <span class="suggestion" onclick="askSuggestion('How can I reduce cost?')">Optimize cost</span>
    <span class="suggestion" onclick="askSuggestion('What is the slowest model?')">Slowest model</span>
  </div>
  <div class="chat-input-bar">
    <input id="chatInput" type="text" placeholder="Ask anything..." onkeydown="if(event.key==='Enter')sendChat()">
    <button class="chat-send" onclick="sendChat()">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
    </button>
  </div>
</div>

<div class="modal-backdrop" id="traceModal" onclick="if(event.target===this)closeModal()">
  <div class="modal-content p-6">
    <div class="flex items-center justify-between mb-4">
      <h3 class="text-lg font-bold">Trace Details</h3>
      <button onclick="closeModal()" class="btn-ghost w-8 h-8 rounded-lg flex items-center justify-center">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
      </button>
    </div>
    <div id="modalBody"></div>
  </div>
</div>

<div class="modal-backdrop" id="budgetModal" onclick="if(event.target===this)closeBudgetModal()">
  <div class="modal-content p-6" style="max-width: 480px;">
    <div class="flex items-center justify-between mb-4">
      <h3 class="text-lg font-bold">Budget Alerts</h3>
      <button onclick="closeBudgetModal()" class="btn-ghost w-8 h-8 rounded-lg flex items-center justify-center">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
      </button>
    </div>
    <p class="text-sm mb-4" style="color: var(--muted);">Alert when total cost exceeds threshold.</p>
    <label class="text-xs font-bold block mb-2" style="color: var(--muted);">DAILY BUDGET (USD)</label>
    <input id="budgetInput" type="number" step="0.01" value="1.00" class="w-full px-3 py-2.5 rounded-xl text-sm mb-4">
    <button onclick="saveBudget()" class="btn-primary w-full py-3 rounded-xl text-white text-sm font-bold"><span class="relative z-10">Save</span></button>
  </div>
</div>

<script>
var c1, c2, c3;
var palette = ['#6366f1', '#8b5cf6', '#ec4899', '#14b8a6', '#f59e0b', '#ef4444'];
var currentTraces = [];

function isDark() { return document.documentElement.className === 'dark'; }
function initTheme() { var s = localStorage.getItem('theme') || 'light'; document.documentElement.className = s; updateIcon(s); }
function toggleTheme() { var c = document.documentElement.className === 'dark' ? 'light' : 'dark'; document.documentElement.className = c; localStorage.setItem('theme', c); updateIcon(c); load(); }
function updateIcon(t) { document.getElementById('iconSun').style.display = t === 'dark' ? 'block' : 'none'; document.getElementById('iconMoon').style.display = t === 'dark' ? 'none' : 'block'; }

function toast(msg) { var el = document.createElement('div'); el.className = 'toast'; el.textContent = msg; document.body.appendChild(el); setTimeout(function(){ el.remove(); }, 4000); }

function sparkline(id, data, color) {
  var svg = document.getElementById(id);
  if (!data.length) { svg.innerHTML = ''; return; }
  var max = Math.max.apply(null, data) || 1, min = Math.min.apply(null, data), range = max - min || 1;
  var pts = data.map(function(v, i) { var x = (i / (data.length - 1)) * 100; var y = 40 - ((v - min) / range) * 30 - 5; return x + ',' + y; }).join(' ');
  var areaPts = '0,44 ' + pts + ' 100,44';
  svg.innerHTML = '<defs><linearGradient id="grad' + id + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="' + color + '" stop-opacity="0.3"/><stop offset="100%" stop-color="' + color + '" stop-opacity="0"/></linearGradient></defs><polygon points="' + areaPts + '" fill="url(#grad' + id + ')"/><polyline points="' + pts + '" fill="none" stroke="' + color + '" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>';
}

function computeTrends(traces) {
  var half = Math.floor(traces.length / 2);
  var older = traces.slice(0, half), newer = traces.slice(half);
  if (!older.length || !newer.length) return { req: 0, cost: 0, tok: 0, lat: 0 };
  var oldCost = older.reduce(function(a, x){ return a + (x.cost_usd || 0); }, 0);
  var newCost = newer.reduce(function(a, x){ return a + (x.cost_usd || 0); }, 0);
  var costTrend = oldCost > 0 ? ((newCost - oldCost) / oldCost * 100) : 0;
  var oldLat = older.reduce(function(a, x){ return a + (x.duration_ms || 0); }, 0) / older.length;
  var newLat = newer.reduce(function(a, x){ return a + (x.duration_ms || 0); }, 0) / newer.length;
  var latTrend = oldLat > 0 ? ((newLat - oldLat) / oldLat * 100) : 0;
  return { req: (newer.length - older.length) / (older.length || 1) * 100, cost: costTrend, tok: costTrend, lat: latTrend };
}

function setTrend(id, value, invert) {
  var el = document.getElementById(id);
  var positive = invert ? value < 0 : value > 0;
  var color = positive ? '#10b981' : '#ef4444';
  el.textContent = (value > 0 ? '↑ ' : '↓ ') + Math.abs(value).toFixed(1) + '%';
  el.style.color = color;
  el.style.background = positive ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)';
}

async function load() {
  try {
    var r = await Promise.all([fetch('/api/costs').then(function(x){ return x.json(); }), fetch('/api/spans').then(function(x){ return x.json(); })]);
    var costs = r[0], spansRes = r[1];
    var sp = spansRes.spans || [];
    currentTraces = sp;

    var fm = document.getElementById('filterModel').value;
    var ff = document.getElementById('filterFeature').value;
    var search = (document.getElementById('searchInput').value || '').toLowerCase();

    var filtered = sp;
    if (fm !== 'all') filtered = filtered.filter(function(x){ return x.model === fm; });
    if (ff !== 'all') filtered = filtered.filter(function(x){ return x.feature === ff; });
    if (search) filtered = filtered.filter(function(x){ return (x.trace_id || '').toLowerCase().indexOf(search) >= 0 || (x.model || '').toLowerCase().indexOf(search) >= 0 || (x.feature || '').toLowerCase().indexOf(search) >= 0; });

    document.getElementById('filterInfo').textContent = filtered.length + ' / ' + sp.length;

    var cf = {}, cm = {};
    filtered.forEach(function(x){ cf[x.feature || 'unknown'] = (cf[x.feature || 'unknown'] || 0) + (x.cost_usd || 0); cm[x.model || 'unknown'] = (cm[x.model || 'unknown'] || 0) + (x.cost_usd || 0); });

    var tc = 0; for (var k in cf) tc += cf[k];
    var tt = 0; filtered.forEach(function(x){ tt += (x.input_tokens || 0) + (x.output_tokens || 0); });
    var al = filtered.length ? filtered.reduce(function(a, x){ return a + (x.duration_ms || 0); }, 0) / filtered.length : 0;

    document.getElementById('mReq').textContent = filtered.length.toLocaleString();
    document.getElementById('mCost').textContent = '$' + tc.toFixed(4);
    document.getElementById('mTok').textContent = tt.toLocaleString();
    document.getElementById('mLat').textContent = al.toFixed(0) + 'ms';
    document.getElementById('liveStatus').textContent = 'Live · ' + filtered.length;

    var budget = parseFloat(localStorage.getItem('budget') || '1.00');
    document.getElementById('bellBadge').style.display = tc > budget ? 'flex' : 'none';

    var tr = computeTrends(filtered);
    setTrend('trendReq', tr.req, false); setTrend('trendCost', tr.cost, true); setTrend('trendTok', tr.tok, true); setTrend('trendLat', tr.lat, true);

    var last20 = filtered.slice(-20);
    sparkline('spark1', last20.map(function(_, i){ return i + 1; }), '#3b82f6');
    sparkline('spark2', last20.map(function(x){ return x.cost_usd || 0; }), '#10b981');
    sparkline('spark3', last20.map(function(x){ return (x.input_tokens || 0) + (x.output_tokens || 0); }), '#a855f7');
    sparkline('spark4', last20.map(function(x){ return x.duration_ms || 0; }), '#f97316');

    var empty = document.getElementById('empty'), tbody = document.getElementById('tbody');
    if (filtered.length === 0) { empty.style.display = 'block'; tbody.innerHTML = ''; } else { empty.style.display = 'none'; }

    var gridColor = isDark() ? 'rgba(255,255,255,0.06)' : '#f1f5f9';
    var tickColor = isDark() ? '#8892a6' : '#94a3b8';
    var labelColor = isDark() ? '#c9d1d9' : '#334155';
    var borderColor = isDark() ? '#0f1420' : '#ffffff';

    if (c1) c1.destroy();
    c1 = new Chart(document.getElementById('c1'), { type: 'bar', data: { labels: Object.keys(cf), datasets: [{ data: Object.values(cf), backgroundColor: Object.keys(cf).map(function(_, i){ return palette[i % palette.length]; }), borderRadius: 10, borderSkipped: false, barThickness: 28 }] }, options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { backgroundColor: '#0f172a', padding: 14, borderRadius: 10, callbacks: { label: function(ctx){ return '$' + ctx.parsed.x.toFixed(6); } } } }, scales: { x: { grid: { color: gridColor }, ticks: { color: tickColor, font: { size: 11 } } }, y: { grid: { display: false }, ticks: { color: labelColor, font: { size: 12, weight: '600' } } } } } });

    if (c2) c2.destroy();
    c2 = new Chart(document.getElementById('c2'), { type: 'doughnut', data: { labels: Object.keys(cm), datasets: [{ data: Object.values(cm), backgroundColor: Object.keys(cm).map(function(_, i){ return palette[i % palette.length]; }), borderWidth: 4, borderColor: borderColor, hoverOffset: 10 }] }, options: { responsive: true, maintainAspectRatio: false, cutout: '68%', plugins: { legend: { position: 'bottom', labels: { color: labelColor, padding: 18, boxWidth: 12, boxHeight: 12, usePointStyle: true, pointStyle: 'circle', font: { size: 12, weight: '500' } } }, tooltip: { backgroundColor: '#0f172a', padding: 14, borderRadius: 10, callbacks: { label: function(ctx){ return ctx.label + ': $' + ctx.parsed.toFixed(6); } } } } } });

    var modelLat = {};
    filtered.forEach(function(x){ if (!modelLat[x.model]) modelLat[x.model] = []; modelLat[x.model].push(x.duration_ms || 0); });
    var latModels = Object.keys(modelLat);
    var latAvgs = latModels.map(function(m){ return modelLat[m].reduce(function(a,b){ return a+b; }, 0) / modelLat[m].length; });

    if (c3) c3.destroy();
    c3 = new Chart(document.getElementById('c3'), { type: 'bar', data: { labels: latModels, datasets: [{ data: latAvgs, backgroundColor: latModels.map(function(_, i){ return palette[i % palette.length]; }), borderRadius: 10, borderSkipped: false, barThickness: 36 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { backgroundColor: '#0f172a', padding: 14, borderRadius: 10, callbacks: { label: function(ctx){ return ctx.parsed.y.toFixed(0) + 'ms'; } } } }, scales: { x: { grid: { display: false }, ticks: { color: labelColor, font: { size: 11, weight: '600' } } }, y: { grid: { color: gridColor }, ticks: { color: tickColor, font: { size: 11 } } } } } });

    var sorted = filtered.slice().sort(function(a, b){ return (b.cost_usd || 0) - (a.cost_usd || 0); }).slice(0, 5);
    var topHtml = '';
    sorted.forEach(function(x){
      topHtml += '<div class="flex items-center justify-between p-3 rounded-xl row-hover" style="background: var(--subtle);" onclick="openTrace(\\'' + x.trace_id + '\\')">';
      topHtml += '<div class="flex items-center gap-3"><span class="mono text-xs font-semibold" style="color: var(--muted);">' + (x.trace_id || '').slice(0, 10) + '</span><span class="text-xs font-bold">' + (x.feature || '-') + '</span></div>';
      topHtml += '<span class="mono text-xs font-bold text-emerald-600">$' + (x.cost_usd || 0).toFixed(6) + '</span></div>';
    });
    document.getElementById('topExpensive').innerHTML = topHtml || '<p class="text-xs" style="color: var(--muted);">No data yet</p>';

    var h = '';
    filtered.slice(-15).reverse().forEach(function(x){
      var mc = { 'llama3.2': 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/20', 'gpt-4o': 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-500/10 dark:text-blue-300 dark:border-blue-500/20', 'claude-3-5-sonnet': 'bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-500/10 dark:text-purple-300 dark:border-purple-500/20' };
      var cls = mc[x.model] || 'bg-slate-100 text-slate-700 border-slate-200';
      h += '<tr class="row-hover" onclick="openTrace(\\'' + x.trace_id + '\\')">';
      h += '<td class="px-6 py-4 mono text-xs" style="color: var(--muted);">' + (x.trace_id || '').slice(0, 14) + '</td>';
      h += '<td class="px-6 py-4"><span class="inline-flex px-2.5 py-1 rounded-lg text-xs font-bold border ' + cls + '">' + (x.model || '?') + '</span></td>';
      h += '<td class="px-6 py-4 font-semibold">' + (x.feature || '-') + '</td>';
      h += '<td class="px-6 py-4">' + ((x.input_tokens || 0) + (x.output_tokens || 0)).toLocaleString() + '</td>';
      h += '<td class="px-6 py-4 mono text-xs font-semibold">$' + (x.cost_usd || 0).toFixed(6) + '</td>';
      h += '<td class="px-6 py-4"><span class="inline-flex items-center gap-1.5 text-xs font-semibold"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>' + (x.duration_ms || 0).toFixed(0) + 'ms</span></td></tr>';
    });
    tbody.innerHTML = h;
  } catch (e) { console.error(e); document.getElementById('liveStatus').textContent = 'Offline'; }
}

function openTrace(traceId) {
  var x = currentTraces.find(function(t){ return t.trace_id === traceId; });
  if (!x) return;
  var html = '<div class="space-y-4"><div><span class="text-xs font-bold uppercase tracking-widest" style="color: var(--muted);">Trace ID</span><p class="mono text-sm mt-1 font-semibold">' + (x.trace_id || '-') + '</p></div><div class="grid grid-cols-2 gap-3">';
  [['Model', x.model || '-'], ['Feature', x.feature || '-'], ['Input Tokens', x.input_tokens || 0], ['Output Tokens', x.output_tokens || 0], ['Cost', '$' + (x.cost_usd || 0).toFixed(6)], ['Latency', (x.duration_ms || 0).toFixed(0) + 'ms']].forEach(function(p){
    html += '<div class="p-4 rounded-xl" style="background: var(--subtle);"><p class="text-xs font-semibold" style="color: var(--muted);">' + p[0] + '</p><p class="font-bold mt-1">' + p[1] + '</p></div>';
  });
  html += '</div></div>';
  document.getElementById('modalBody').innerHTML = html;
  document.getElementById('traceModal').classList.add('active');
}
function closeModal() { document.getElementById('traceModal').classList.remove('active'); }
function openBudgetModal() { document.getElementById('budgetModal').classList.add('active'); document.getElementById('budgetInput').value = localStorage.getItem('budget') || '1.00'; }
function closeBudgetModal() { document.getElementById('budgetModal').classList.remove('active'); }
function saveBudget() { localStorage.setItem('budget', document.getElementById('budgetInput').value); closeBudgetModal(); toast('Budget saved'); load(); }

function exportData(fmt) {
  var content, mime, ext;
  if (fmt === 'csv') {
    content = 'trace_id,model,feature,input_tokens,output_tokens,cost_usd,duration_ms\\n';
    currentTraces.forEach(function(x){ content += [x.trace_id, x.model, x.feature, x.input_tokens, x.output_tokens, x.cost_usd, x.duration_ms].join(',') + '\\n'; });
    mime = 'text/csv'; ext = 'csv';
  } else { content = JSON.stringify(currentTraces, null, 2); mime = 'application/json'; ext = 'json'; }
  var a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([content], { type: mime })); a.download = 'llm-traces.' + ext; a.click();
  toast('Exported ' + currentTraces.length + ' traces');
}

async function gen() {
  toast('Generating 10 real traces via Ollama... (~30 sec)');
  try {
    var res = await fetch('/api/seed-real', { method: 'POST' });
    var data = await res.json();
    toast(data.generated + ' real traces generated');
    load();
  } catch (e) {
    toast('Error generating real traces');
  }
}

function toggleChat() {
  var panel = document.getElementById('chatPanel');
  var fab = document.getElementById('chatFab');
  var icon = document.getElementById('chatIcon');
  var isActive = panel.classList.toggle('active');
  fab.classList.toggle('active', isActive);
  if (isActive) {
    icon.innerHTML = '<path d="M18 6 6 18M6 6l12 12"/>';
    setTimeout(function(){ document.getElementById('chatInput').focus(); }, 300);
  } else {
    icon.innerHTML = '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>';
  }
}

function addMessage(text, isUser) {
  var container = document.getElementById('chatMessages');
  var div = document.createElement('div');
  div.className = 'msg ' + (isUser ? 'msg-user' : 'msg-bot');
  var html = text.replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>')
    .replace(/`(.+?)`/g, '<code>$1</code>');
  div.innerHTML = html;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function showTyping() {
  var container = document.getElementById('chatMessages');
  var div = document.createElement('div');
  div.className = 'typing';
  div.id = 'typingIndicator';
  div.innerHTML = '<span></span><span></span><span></span>';
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function hideTyping() {
  var t = document.getElementById('typingIndicator');
  if (t) t.remove();
}

async function sendChat() {
  var input = document.getElementById('chatInput');
  var msg = input.value.trim();
  if (!msg) return;
  addMessage(msg, true);
  input.value = '';
  document.getElementById('chatSuggestions').style.display = 'none';
  showTyping();
  try {
    var res = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: msg }) });
    var data = await res.json();
    hideTyping();
    addMessage(data.reply, false);
  } catch (e) {
    hideTyping();
    addMessage('Sorry, something went wrong. Try again.', false);
  }
}

function askSuggestion(text) {
  document.getElementById('chatInput').value = text;
  sendChat();
}

document.addEventListener('keydown', function(e){
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
  if (e.key === 'g' || e.key === 'G') gen();
  if (e.key === 'r' || e.key === 'R') load();
  if (e.key === 't' || e.key === 'T') toggleTheme();
  if (e.key === 'c' || e.key === 'C') toggleChat();
  if (e.key === 'Escape') { closeModal(); closeBudgetModal(); }
});

initTheme();
load();
setInterval(load, 3000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def root():
    return HTML_PAGE