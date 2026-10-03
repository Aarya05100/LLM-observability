from datetime import datetime

class SpanParser:
    @staticmethod
    def parse(span: dict, attrs: dict, resource_attrs: dict) -> dict:
        return {
            "trace_id": span.get("traceId", ""),
            "span_id": span.get("spanId", ""),
            "parent_span_id": span.get("parentSpanId", ""),
            "name": span.get("name", ""),
            "start_time": datetime.utcnow().isoformat(),
            "duration_ms": SpanParser._calc_duration(
                span.get("startTimeUnixNano"), span.get("endTimeUnixNano")
            ),
            "gen_ai_system": attrs.get("gen_ai.system", ""),
            "model": attrs.get("gen_ai.request.model", ""),
            "input_tokens": SpanParser._to_int(attrs.get("gen_ai.usage.input_tokens")),
            "output_tokens": SpanParser._to_int(attrs.get("gen_ai.usage.output_tokens")),
            "prompt": attrs.get("llm.prompts", ""),
            "completion": attrs.get("llm.completions", ""),
            "user_id": attrs.get("user.id", resource_attrs.get("user.id", "")),
            "session_id": attrs.get("session.id", ""),
            "feature": attrs.get("feature", "unknown"),
            "environment": attrs.get("environment", "production"),
            "status_code": span.get("status", {}).get("code", "OK"),
            "error_message": span.get("status", {}).get("message", ""),
        }

    @staticmethod
    def _to_int(val):
        if val is None:
            return 0
        try:
            return int(val)
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _calc_duration(start_ns, end_ns):
        if not start_ns or not end_ns:
            return 0.0
        try:
            return (int(end_ns) - int(start_ns)) / 1_000_000
        except (ValueError, TypeError):
            return 0.0
