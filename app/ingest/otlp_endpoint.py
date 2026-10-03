from fastapi import APIRouter, Request
from app.ingest.span_parser import SpanParser
from app.storage.memory_store import MemoryStore
from app.services.cost_tracker import CostTracker

router = APIRouter()
store = MemoryStore()
cost_tracker = CostTracker()

@router.post("/v1/traces")
async def ingest_traces(request: Request):
    body = await request.json()
    resource_spans = body.get("resourceSpans", [])
    spans_to_insert = []

    for resource_span in resource_spans:
        resource_attrs = _extract_attrs(resource_span.get("resource", {}))
        for scope_span in resource_span.get("scopeSpans", []):
            for span in scope_span.get("spans", []):
                attrs = _extract_attrs(span)
                parsed = SpanParser.parse(span, attrs, resource_attrs)
                if parsed.get("model") and parsed.get("input_tokens"):
                    parsed["cost_usd"] = cost_tracker.calculate(
                        model=parsed["model"],
                        input_tokens=parsed["input_tokens"],
                        output_tokens=parsed.get("output_tokens", 0),
                    )
                spans_to_insert.append(parsed)

    if spans_to_insert:
        store.insert_spans(spans_to_insert)

    return {"status": "ok", "spans_ingested": len(spans_to_insert)}

def _extract_attrs(obj: dict) -> dict:
    attrs = {}
    for a in obj.get("attributes", []):
        key = a.get("key")
        value = a.get("value", {})
        attrs[key] = (
            value.get("stringValue")
            or value.get("intValue")
            or value.get("doubleValue")
            or value.get("boolValue")
        )
    return attrs
