import os
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

# Groq client config (works on cloud)
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"


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
        client = OpenAI(base_url=GROQ_BASE_URL, api_key=os.getenv("GROQ_API_KEY"))
        response = client.chat.completions.create(
            model=GROQ_MODEL,
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
                        "name": "groq.chat",
                        "startTimeUnixNano": str(int((time.time() - latency_ms/1000) * 1e9)),
                        "endTimeUnixNano": str(int(time.time() * 1e9)),
                        "attributes": [
                            {"key": "gen_ai.system", "value": {"stringValue": "groq"}},
                            {"key": "gen_ai.request.model", "value": {"stringValue": GROQ_MODEL}},
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

    except Exception as e:
        if costs_f:
            top_f = max(costs_f.items(), key=lambda x: x[1])
            return {"reply": f"**Summary**\n- Traces: {len(spans)}\n- Cost: ${total_cost:.4f}\n- Avg latency: {avg_lat:.0f}ms\n- Top feature: **{top_f[0]}**\n\n(Error: {type(e).__name__})"}
        return {"reply": f"Error: {type(e).__name__} - {str(e)[:100]}"}


@app.post("/api/seed-real")
def seed_real_data():
    """Generate 10 REAL traces via Groq."""
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

    client = OpenAI(base_url=GROQ_BASE_URL, api_key=os.getenv("GROQ_API_KEY"))
    count = 0

    for prompt, feature in prompts:
        try:
            start = time.time()
            response = client.chat.completions.create(
                model=GROQ_MODEL,
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
                            "name": "groq.chat",
                            "startTimeUnixNano": str(int((time.time() - latency_ms/1000) * 1e9)),
                            "endTimeUnixNano": str(int(time.time() * 1e9)),
                            "attributes": [
                                {"key": "gen_ai.system", "value": {"stringValue": "groq"}},
                                {"key": "gen_ai.request.model", "value": {"stringValue": GROQ_MODEL}},
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
      <p class="text-base mt-3 max-w-xl" style="color: var(--muted);">Track every prompt, token, and dollar across your LLM applications. Powered by Groq (llama-3.3-70b).</p>
    </div>
    <div class="flex gap-2">
      <button onclick="exportData('csv')" class="btn-ghost px-4 py-2.5 rounded-xl text-xs font-semibold">Export CSV</button>
      <button onclick="exportData('json')" class="btn-ghost px-4 py-2.5 rounded-xl text-xs font-semibold">Export JSON</button>
    </div>
  </div>

  <div class="flex flex-wrap items-center gap-3 mb-8">
    <div class="chip"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M3 6h18M3 12h18M3 18h18"/
