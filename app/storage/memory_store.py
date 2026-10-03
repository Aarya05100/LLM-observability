from collections import defaultdict

class MemoryStore:
    """
    Singleton in-memory store. All modules share the same instance.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.spans = []
            cls._instance.costs_by_feature = defaultdict(float)
            cls._instance.costs_by_model = defaultdict(float)
        return cls._instance

    def insert_spans(self, spans: list[dict]):
        for s in spans:
            self.spans.append(s)
            self.costs_by_feature[s.get("feature", "unknown")] += s.get("cost_usd", 0)
            self.costs_by_model[s.get("model", "unknown")] += s.get("cost_usd", 0)

    def get_all_spans(self):
        return self.spans

    def get_cost_by_feature(self):
        return dict(self.costs_by_feature)

    def get_cost_by_model(self):
        return dict(self.costs_by_model)