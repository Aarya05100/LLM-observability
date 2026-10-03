"""Demo LLM app using local Ollama - no API key needed."""
import os
import time
import uuid
import requests
from openai import OpenAI

OBSERVABILITY_URL = "http://localhost:8000/v1/traces"

# Local Ollama - no API key needed
client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.getenv("GROQ_API_KEY"),
)


def send_trace(model, feature, prompt, completion, input_tokens, output_tokens, latency_ms, trace_id):
    payload = {
        "resourceSpans": [{
            "scopeSpans": [{
                "spans": [{
                    "traceId": trace_id,
                    "spanId": "span-" + str(uuid.uuid4())[:8],
                    "name": "ollama.chat",
                    "startTimeUnixNano": str(int((time.time() - latency_ms/1000) * 1e9)),
                    "endTimeUnixNano": str(int(time.time() * 1e9)),
                    "attributes": [
                        {"key": "gen_ai.system", "value": {"stringValue": "ollama"}},
                        {"key": "gen_ai.request.model", "value": {"stringValue": model}},
                        {"key": "gen_ai.usage.input_tokens", "value": {"intValue": str(input_tokens)}},
                        {"key": "gen_ai.usage.output_tokens", "value": {"intValue": str(output_tokens)}},
                        {"key": "feature", "value": {"stringValue": feature}},
                        {"key": "llm.prompts", "value": {"stringValue": prompt[:500]}},
                        {"key": "llm.completions", "value": {"stringValue": completion[:500]}},
                    ]
                }]
            }]
        }]
    }
    try:
        requests.post(OBSERVABILITY_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"[warn] Could not send trace: {e}")


def chat(user_message, model="llama-3.3-70b-versatile", feature="chat"):
    start = time.time()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": user_message},
        ],
    )
    latency_ms = (time.time() - start) * 1000
    completion = response.choices[0].message.content
    usage = response.usage
    trace_id = "trace-" + uuid.uuid4().hex[:12]
    send_trace(
        model=model,
        feature=feature,
        prompt=user_message,
        completion=completion,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
        latency_ms=latency_ms,
        trace_id=trace_id,
    )
    return completion


if __name__ == "__main__":
    print("=== Demo LLM Chat (Ollama + Llama 3.2) ===")
    print("Every message tracked on http://localhost:8000")
    print("Type quit to exit.\n")
    while True:
        msg = input("You: ").strip()
        if msg.lower() in ("quit", "exit", "q"):
            break
        if not msg:
            continue
        try:
            reply = chat(msg)
            print(f"Bot: {reply}\n")
        except Exception as e:
            print(f"[error] {type(e).__name__}: {e}\n")
