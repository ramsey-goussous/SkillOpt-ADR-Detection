#!/usr/bin/env python3
"""Validate real_data/real_notes.json and materialize a SkillOpt split."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_items(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(raw, dict) and isinstance(raw.get("data"), list):
        raw = raw["data"]
    if not isinstance(raw, list):
        raise ValueError("Real data file must be a JSON array, or an object with a 'data' array.")
    return raw


def normalize_gold(gold: object) -> dict:
    if not isinstance(gold, dict):
        return {}
    return {
        "suspected_adr_signals": gold.get("suspected_adr_signals", []) or [],
        "unlinked_adverse_events": gold.get("unlinked_adverse_events", []) or [],
        "negative_controls": gold.get("negative_controls", []) or [],
    }


def normalize_item(raw: dict, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"Item {index} is not an object.")
    note_id = raw.get("id") or raw.get("note_id") or raw.get("record_id")
    note_text = raw.get("note_text") or raw.get("text") or raw.get("note")
    if not note_id:
        raise ValueError(f"Item {index} is missing id/note_id/record_id.")
    if not isinstance(note_text, str) or not note_text.strip():
        raise ValueError(f"Item {index} ({note_id}) is missing note_text/text/note.")

    item = {
        "id": str(note_id),
        "note_text": note_text,
        "task_type": "adr",
    }
    if "gold" in raw:
        item["gold"] = normalize_gold(raw.get("gold"))
    return item


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare real ADR notes for eval-only SkillOpt runs.")
    parser.add_argument("--input", required=True, help="Path to real_notes.json")
    parser.add_argument("--out", required=True, help="Output split directory")
    args = parser.parse_args()

    src = Path(args.input).resolve()
    out = Path(args.out).resolve()
    if not src.exists():
        raise FileNotFoundError(f"Real data file not found: {src}")

    items = [normalize_item(item, idx) for idx, item in enumerate(load_items(src), 1)]
    ids = [item["id"] for item in items]
    duplicates = sorted({note_id for note_id in ids if ids.count(note_id) > 1})
    if duplicates:
        raise ValueError(f"Duplicate note ids in real data: {duplicates[:10]}")

    labeled = sum(1 for item in items if isinstance(item.get("gold"), dict))
    write_json(out / "train" / "items.json", [])
    write_json(out / "val" / "items.json", [])
    write_json(out / "test" / "items.json", items)
    write_json(out / "manifest.json", {
        "source": str(src),
        "total_notes": len(items),
        "labeled_notes": labeled,
        "unlabeled_notes": len(items) - labeled,
    })
    print(f"real data prepared: total={len(items)} labeled={labeled} unlabeled={len(items) - labeled}")
    print(f"split_dir={out}")


if __name__ == "__main__":
    main()
