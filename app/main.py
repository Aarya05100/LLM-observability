import os
from pathlib import Path
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

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"

DASHBOARD_FILE = Path(__file__).parent / "dashboard.html"


def _save_trace(trace_id, model, feature, prompt, completion,
                in_tok, out_tok, latency_ms, system="groq"):
    """Save trace directly to store — no HTTP needed."""
    cost = 0.0
    pricing = {
        "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
        "llama3.2": {"input": 0.05, "output": 0.10},
        "gpt-4o": {"input": 2.50, "output": 10.00},
    }
    p = pricing.get(model)
    if p:
        cost = (in_tok / 1_000_000) * p["input"] + (out_tok / 1_000_000) * p["output"]

    store.insert_spans([{
        "trace_id": trace_id,
        "span_id": "span-" + trace_id[-6:],
        "parent_span_id": "",
        "name": "groq.chat",
        "start_time": "",
        "end_time": "",
        "duration_ms": latency_ms,
        "gen_ai_system": system,
        "model": model,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": round(cost, 6),
        "prompt": prompt[:500],
        "completion": completion[:500],
        "user_id": "",
        "session_id": "",
        "feature": feature,
        "environment": "production",
        "status_code": "OK",
        "error_message": "",
    }])


class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
def chat(req: ChatRequest):
    import time
    import uuid
    from openai import OpenAI

    msg = req.message.strip()
    spans = store.get_all_spans()
    costs_f = store.get_cost_by_feature()
    costs_m = store.get_cost_by_model()

    if not spans:
        return {"reply": "No traces yet. Click Generate to populate."}

    total_cost = sum(costs_f.values())
    total_tokens = sum((s.get("input_tokens", 0) + s.get("output_tokens", 0)) for s in spans)
    avg_lat = sum(s.get("duration_ms", 0) for s in spans) / len(spans)

    top_features = sorted(costs_f.items(), key=lambda x: -x[1])[:5]
    top_models = sorted(costs_m.items(), key=lambda x: -x[1])[:5]

    model_lat = {}
    for s in spans:
        m = s.get("model", "?")
        model_lat.setdefault(m, []).append(s.get("duration_ms", 0))
    lat_by_model = sorted([(m, sum(v) / len(v)) for m, v in model_lat.items()], key=lambda x: -x[1])

    recent = spans[-10:]
    recent_lines = "\n".join([
        f"- {s.get('trace_id','')[:12]} | {s.get('model','?')} | {s.get('feature','-')} | "
        f"{s.get('input_tokens',0)+s.get('output_tokens',0)} tokens | "
        f"${s.get('cost_usd',0):.6f} | {s.get('duration_ms',0):.0f}ms"
        for s in recent
    ])

    context = f"""You are an observability copilot.

LIVE DATA:
- Total traces: {len(spans)}
- Total cost: ${total_cost:.4f}
- Total tokens: {total_tokens:,}
- Avg latency: {avg_lat:.0f}ms

Top features: {chr(10).join(f'  {f}: ${c:.4f}' for f, c in top_features)}
Models: {chr(10).join(f'  {m}: ${c:.4f}' for m, c in top_models)}
Latency: {chr(10).join(f'  {m}: {l:.0f}ms' for m, l in lat_by_model)}

Recent:
{recent_lines}

Answer concisely (2-4 sentences). Use **bold** for numbers."""

    start = time.time()
    try:
        client = OpenAI(base_url=GROQ_BASE_URL, api_key=os.getenv("GROQ_API_KEY"))
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "system", "content": context}, {"role": "user", "content": msg}],
            temperature=0.3,
            max_tokens=250,
        )
        reply = response.choices[0].message.content.strip()
        latency_ms = (time.time() - start) * 1000
        usage = response.usage
        _save_trace(
            trace_id="trace-" + uuid.uuid4().hex[:12],
            model=GROQ_MODEL,
            feature="copilot-chat",
            prompt=msg,
            completion=reply,
            in_tok=usage.prompt_tokens if usage else 0,
            out_tok=usage.completion_tokens if usage else 0,
            latency_ms=latency_ms,
        )
        return {"reply": reply}
    except Exception as e:
        return {"reply": f"Error: {type(e).__name__}: {str(e)[:150]}"}


@app.post("/api/seed-real")
def seed_real_data():
    import time
    import uuid
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
                messages=[{"role": "system", "content": "Answer in 1-2 sentences."}, {"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=100,
            )
            latency_ms = (time.time() - start) * 1000
            completion = response.choices[0].message.content.strip()
            usage = response.usage
            _save_trace(
                trace_id="trace-" + uuid.uuid4().hex[:12],
                model=GROQ_MODEL,
                feature=feature,
                prompt=prompt,
                completion=completion,
                in_tok=usage.prompt_tokens if usage else 0,
                out_tok=usage.completion_tokens if usage else 0,
                latency_ms=latency_ms,
            )
            count += 1
        except Exception as e:
            print(f"[seed] error: {e}")

    return {"status": "ok", "generated": count}


@app.get("/api/health")
def health():
    return {"status": "healthy"}


@app.get("/", response_class=HTMLResponse)
def root():
    return DASHBOARD_FILE.read_text(encoding="utf-8")
