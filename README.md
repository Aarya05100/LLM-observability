# 🔍 LLM Observability Platform

Real-time tracing, cost tracking, and AI copilot for LLM applications.

![Dashboard](docs/dashboard.png)

## Problem

LLM apps are black boxes. Traditional APM tools only show HTTP spans — the internal steps (retrieval, tool calls, sub-agents) stay invisible. Teams don't know:
- Which feature burns the most tokens?
- Which model is slowest?
- Where does the cost come from?

## Solution

A self-hosted observability platform that captures every LLM call as an OpenTelemetry span — with real-time dashboard, cost tracking, and an AI copilot powered by local Llama 3.2.

## Features

- **OTLP trace ingestion** — OpenTelemetry GenAI semantic conventions
- **Real-time dashboard** — cost, latency, tokens per feature/model
- **AI copilot** — natural language Q&A about your traces (Llama 3.2 via Ollama)
- **Self-observability** — the copilot itself is instrumented (`copilot-chat` feature)
- **Live demo app** — instrumented Llama 3.2 chat (`demo_app/chat.py`)
- **Filters, search, export (CSV/JSON), budget alerts**
- **Dark mode** — Stripe/Linear-inspired UI
- **Keyboard shortcuts** — G, R, T, C, Esc

## Architecture

LLM App → OTLP HTTP → FastAPI Ingest → Cost Enrichment → Store → Dashboard
↓
AI Copilot (/api/chat)


## Tech Stack

- **Backend:** FastAPI, Python, async
- **Tracing:** OpenTelemetry GenAI conventions
- **Frontend:** Vanilla JS + Tailwind CSS + Chart.js
- **LLM:** Local Llama 3.2 via Ollama (OpenAI-compatible API)
- **Storage:** In-memory (ClickHouse planned)

## Quick Start

```bash
# 1. Setup
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\Activate.ps1
pip install fastapi uvicorn pydantic-settings httpx openai

# 2. Install Ollama + model (once)
# https://ollama.com/download
ollama pull llama3.2

# 3. Terminal 1 — API server + dashboard
uvicorn app.main:app --reload --reload-dir app

# 4. Terminal 2 — instrumented demo app (optional)
python demo_app/chat.py