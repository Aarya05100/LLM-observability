class CostTracker:
    PRICING = {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
        "claude-3-haiku": {"input": 0.25, "output": 1.25},
    }

    def calculate(self, model: str, input_tokens: int, output_tokens: int) -> float:
        pricing = self._lookup(model)
        if not pricing:
            return 0.0
        return round(
            (input_tokens / 1_000_000) * pricing["input"]
            + (output_tokens / 1_000_000) * pricing["output"],
            6,
        )

    def _lookup(self, model: str):
        m = model.lower()
        for key, pricing in self.PRICING.items():
            if key in m:
                return pricing
        return None
