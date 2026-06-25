"""ADR task dataloader. Each split dir (train/ val/ test/) holds items.json:
   a JSON array of {"id": str, "note_text": str, "gold": {...}} objects.
"""
from __future__ import annotations
import json
from skillopt.datasets.base import SplitDataLoader

def _load_items(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return []
    data = json.loads(content)
    return data if isinstance(data, list) else (data.get("data") or list(data.values()))

class ADRDataLoader(SplitDataLoader):
    # data_path is a single JSON/JSONL file (used only when split_mode=ratio)
    def load_raw_items(self, data_path: str) -> list[dict]:
        return _load_items(data_path)
