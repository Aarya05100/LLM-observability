import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import random

st.set_page_config(
    page_title="LLM Observability",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_URL = "http://localhost:8000"

# ---------- Custom CSS ----------
st.markdown("""
<style>
    /* Hide Streamlit default menu */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Main background */
    .stApp {
        background: linear-gradient(180deg, #0a0e1a 0%, #0f1420 100%);
    }
    
    /* Header banner */
    .hero {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 40px 48px;
        border-radius: 20px;
        margin-bottom: 32px;
        box-shadow: 0 20px 60px rgba(102, 126, 234, 0.3);
    }
    .hero h1 {
        color: white;
        font-size: 2.6em;
        font-weight: 800;
        margin: 0 0 8px 0;
        letter-spacing: -0.02em;
    }
    .hero p {
        color: rgba(255,255,255,0.85);
        font-size: 1.1em;
        margin: 0;
    }
    .hero-badge {
        display: inline-block;
        background: rgba(255,255,255,0.2);
        color: white;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.8em;
        margin-top: 12px;
        margin-right: 8px;
        backdrop-filter: blur(10px);
    }
    
    /* Metric cards */
    .metric-card {
        background: linear-gradient(135deg, #1a1f2e 0%, #161a26 100%);
        padding: 24px;
        border-radius: 16px;
        border: 1px solid rgba(102, 126, 234, 0.2);
        transition: all 0.3s;
        position: relative;
        overflow: hidden;
    }
    .metric-card:hover {
        border-color: rgba(102, 126, 234, 0.6);
        transform: translateY(-4px);
        box-shadow: 0 12px 40px rgba(102, 126, 234, 0.2);
    }
    .metric-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        width: 4px;
        height: 100%;
        background: linear-gradient(180deg, #667eea, #764ba2);
    }
    .metric-label {
        color: #8b95a5;
        font-size: 0.85em;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 12px;
    }
    .metric-value {
        color: #ffffff;
        font-size: 2.2em;
        font-weight: 700;
        line-height: 1;
        margin-bottom: 6px;
    }
    .metric-delta {
        color: #4ade80;
        font-size: 0.85em;
        font-weight: 500;
    }
    
    /* Section headers */
    .section-header {
        color: #ffffff;
        font-size: 1.4em;
        font-weight: 700;
        margin: 32px 0 20px 0;
        padding-bottom: 12px;
        border-bottom: 1px solid rgba(102, 126, 234, 0.15);
    }
    
    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0d1117 0%, #0a0e1a 100%);
        border-right: 1px solid rgba(102, 126, 234, 0.15);
    }
    [data-testid="stSidebar"] .stButton button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        padding: 12px 20px;
        border-radius: 10px;
        font-weight: 600;
        width: 100%;
        transition: all 0.2s;
    }
    [data-testid="stSidebar"] .stButton button:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(102, 126, 234, 0.4);
    }
    
    /* Sidebar links */
    .sidebar-link {
        display: block;
        padding: 10px 14px;
        color: #c9d1d9;
        text-decoration: none;
        border-radius: 8px;
        margin-bottom: 6px;
        transition: all 0.2s;
        font-size: 0.95em;
    }
    .sidebar-link:hover {
        background: rgba(102, 126, 234, 0.15);
        color: #667eea;
    }
    
    /* Hide default metric styling */
    [data-testid="stMetricValue"] { display: none; }
    [data-testid="stMetricLabel"] { display: none; }
</style>
""", unsafe_allow_html=True)


def _send_sample_trace():
    models = ["gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "claude-3-haiku"]
    features = ["customer-support", "code-review", "summarization", "chat", "search"]
    model = random.choice(models)
    feature = random.choice(features)
    input_tokens = random.randint(50, 800)
    output_tokens = random.randint(30, 500)
    payload = {
        "resourceSpans": [{"scopeSpans": [{"spans": [{
            "traceId": f"trace-{random.randint(100000, 999999)}",
            "spanId": f"span-{random.randint(1000, 9999)}",
            "name": "openai.chat",
            "startTimeUnixNano": str(int(datetime.utcnow().timestamp() * 1e9)),
            "endTimeUnixNano": str(int((datetime.utcnow().timestamp() + random.uniform(0.5, 3.5)) * 1e9)),
            "attributes": [
                {"key": "gen_ai.request.model", "value": {"stringValue": model}},
                {"key": "gen_ai.usage.input_tokens", "value": {"intValue": str(input_tokens)}},
                {"key": "gen_ai.usage.output_tokens", "value": {"intValue": str(output_tokens)}},
                {"key": "feature", "value": {"stringValue": feature}},
            ]
        }]}]}]
    }
    try:
        requests.post(f"{API_URL}/v1/traces", json=payload, timeout=5)
    except Exception:
        pass


# ---------- Sidebar ----------
with st.sidebar:
    st.markdown("## ⚙️ Controls")
    st.markdown("")

    if st.button("🎲 Generate 50 Traces", use_container_width=True):
        with st.spinner("Generating..."):
            for i in range(50):
                _send_sample_trace()
        st.success("✅ 50 traces added")
        st.rerun()

    if st.button("🔄 Refresh Data", use_container_width=True):
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 🔗 Quick Links")
    st.markdown(
        '<a href="http://localhost:8000/" class="sidebar-link">🏠 Home</a>'
        '<a href="http://localhost:8000/docs" class="sidebar-link">📖 API Docs</a>'
        '<a href="https://github.com/YOUR-USERNAME/llm-observability" class="sidebar-link">💻 GitHub Repo</a>',
        unsafe_allow_html=True,
    )

    st.markdown("<br>" * 3, unsafe_allow_html=True)
    st.caption("Built with FastAPI + OpenTelemetry")


# ---------- Fetch Data ----------
try:
    costs_resp = requests.get(f"{API_URL}/api/costs", timeout=5).json()
    spans_resp = requests.get(f"{API_URL}/api/spans", timeout=5).json()
except Exception:
    st.error(f"⚠️ Cannot connect to API at {API_URL}")
    st.code("uvicorn app.main:app --reload --reload-dir app")
    st.stop()

spans = spans_resp.get("spans", [])
cost_by_feature = costs_resp.get("cost_by_feature", {})
cost_by_model = costs_resp.get("cost_by_model", {})

# Auto-generate demo data on first load
if not spans:
    with st.spinner("Setting up demo data..."):
        for i in range(60):
            _send_sample_trace()
    st.rerun()


# ---------- Compute Metrics ----------
total_cost = sum(cost_by_feature.values()) if cost_by_feature else 0
total_tokens = sum(s.get("input_tokens", 0) + s.get("output_tokens", 0) for s in spans)
avg_latency = sum(s.get("duration_ms", 0) for s in spans) / len(spans) if spans else 0
total_requests = len(spans)


# ---------- Hero Header ----------
st.markdown(f"""
<div class="hero">
    <h1>🔍 LLM Observability Platform</h1>
    <p>Real-time tracing and cost tracking for LLM applications</p>
    <div>
        <span class="hero-badge">● Live</span>
        <span class="hero-badge">{total_requests} requests tracked</span>
        <span class="hero-badge">OpenTelemetry GenAI</span>
    </div>
</div>
""", unsafe_allow_html=True)


# ---------- Metric Cards ----------
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">📊 Total Requests</div>
        <div class="metric-value">{total_requests:,}</div>
        <div class="metric-delta">↑ tracking all traces</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">💰 Total Cost</div>
        <div class="metric-value">${total_cost:.4f}</div>
        <div class="metric-delta">across {len(cost_by_model)} models</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">🎯 Total Tokens</div>
        <div class="metric-value">{total_tokens:,}</div>
        <div class="metric-delta">input + output</div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">⚡ Avg Latency</div>
        <div class="metric-value">{avg_latency:.0f}ms</div>
        <div class="metric-delta">p50 across models</div>
    </div>
    """, unsafe_allow_html=True)


# ---------- Charts ----------
st.markdown('<div class="section-header">📈 Analytics</div>', unsafe_allow_html=True)

col_left, col_right = st.columns([1, 1])

with col_left:
    if cost_by_feature:
        df = pd.DataFrame(
            list(cost_by_feature.items()),
            columns=["Feature", "Cost"],
        ).sort_values("Cost", ascending=True)

        fig = px.bar(
            df, x="Cost", y="Feature", orientation="h",
            color="Cost",
            color_continuous_scale=["#1a1f2e", "#667eea", "#764ba2"],
            title="💰 Cost by Feature",
        )
        fig.update_layout(
            showlegend=False,
            height=420,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#c9d1d9", size=12),
            title_font=dict(color="#ffffff", size=16, family="Arial Black"),
            xaxis=dict(gridcolor="rgba(102, 126, 234, 0.1)", title=""),
            yaxis=dict(gridcolor="rgba(0,0,0,0)", title=""),
            coloraxis_showscale=False,
            margin=dict(l=0, r=20, t=50, b=0),
        )
        fig.update_traces(marker_line_width=0)
        st.plotly_chart(fig, use_container_width=True)

with col_right:
    if cost_by_model:
        df = pd.DataFrame(
            list(cost_by_model.items()),
            columns=["Model", "Cost"],
        )

        fig = px.pie(
            df, values="Cost", names="Model", hole=0.55,
            title="🤖 Cost by Model",
            color_discrete_sequence=["#667eea", "#764ba2", "#4ade80", "#f59e0b"],
        )
        fig.update_layout(
            height=420,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#c9d1d9", size=12),
            title_font=dict(color="#ffffff", size=16, family="Arial Black"),
            margin=dict(l=0, r=0, t=50, b=0),
            legend=dict(
                font=dict(color="#c9d1d9"),
                bgcolor="rgba(0,0,0,0)",
            ),
        )
        fig.update_traces(
            textposition="outside",
            textinfo="percent+label",
            textfont=dict(color="#ffffff"),
            marker=dict(line=dict(color="#0a0e1a", width=2)),
        )
        st.plotly_chart(fig, use_container_width=True)


# ---------- Latency Distribution ----------
st.markdown('<div class="section-header">⚡ Performance</div>', unsafe_allow_html=True)

latency_df = pd.DataFrame([
    {"Model": s.get("model", "unknown"), "Latency (ms)": s.get("duration_ms", 0)}
    for s in spans if s.get("model")
])

if not latency_df.empty:
    fig = px.box(
        latency_df, x="Model", y="Latency (ms)",
        color="Model",
        color_discrete_sequence=["#667eea", "#764ba2", "#4ade80", "#f59e0b"],
        title="Latency Distribution by Model",
    )
    fig.update_layout(
        height=400,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#c9d1d9", size=12),
        title_font=dict(color="#ffffff", size=16, family="Arial Black"),
        xaxis=dict(gridcolor="rgba(102, 126, 234, 0.1)", title=""),
        yaxis=dict(gridcolor="rgba(102, 126, 234, 0.1)", title=""),
        showlegend=False,
        margin=dict(l=0, r=0, t=50, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------- Recent Traces ----------
st.markdown('<div class="section-header">📋 Recent Traces</div>', unsafe_allow_html=True)

if spans:
    recent = pd.DataFrame([
        {
            "Trace ID": s.get("trace_id", "")[:12],
            "Model": s.get("model", ""),
            "Feature": s.get("feature", ""),
            "Input": s.get("input_tokens", 0),
            "Output": s.get("output_tokens", 0),
            "Cost ($)": round(s.get("cost_usd", 0), 6),
            "Latency (ms)": round(s.get("duration_ms", 0), 1),
            "Status": "✅ OK",
        }
        for s in reversed(spans[-20:])
    ])

    st.dataframe(
        recent,
        use_container_width=True,
        hide_index=True,
        height=400,
    )