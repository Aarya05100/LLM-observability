from pydantic import BaseModel
from typing import Any

class SpanSchema(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: str = ""
    name: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    prompt: str = ""
    completion: str = ""
    duration_ms: float = 0.0
    user_id: str = ""
    feature: str = "unknown"
