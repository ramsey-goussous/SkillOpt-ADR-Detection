#!/usr/bin/env python3
"""Create SkillOpt train/validation/test split files for the ADR task.

Input:
  data/synthetic_notes.json

Output:
  data_split/{train,val,test}/items.json

The test split is generated for completeness. The runner does not evaluate it
unless RUN_TEST_EVAL=1 is set.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "synthetic_notes.json"
OUT = ROOT / "data_split"


def item(note: dict) -> dict:
    return {
        "id": note["id"],
        "note_text": note["note_text"],
        "gold": note["gold"],
        "task_type": "adr",
    }


def write_split(name: str, notes: list[dict]) -> None:
    split_dir = OUT / name
    split_dir.mkdir(parents=True, exist_ok=True)
    (split_dir / "items.json").write_text(
        json.dumps([item(n) for n in notes], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    notes = json.loads(SRC.read_text(encoding="utf-8"))
    by_density: dict[int, list[dict]] = {}
    for note in notes:
        adr_count = int(note.get("adr_count", len(note["gold"].get("suspected_adr_signals", []))))
        by_density.setdefault(adr_count, []).append(note)

    rng = random.Random(42)
    train: list[dict] = []
    val: list[dict] = []
    test: list[dict] = []

    for group in by_density.values():
        rng.shuffle(group)
        n = len(group)
        n_val = max(1, round(n * 0.2))
        n_test = max(1, round(n * 0.2))
        val.extend(group[:n_val])
        test.extend(group[n_val:n_val + n_test])
        train.extend(group[n_val + n_test:])

    write_split("train", train)
    write_split("val", val)
    write_split("test", test)
    (OUT / "test" / "_README.txt").write_text(
        "Generated synthetic test split. Use RUN_TEST_EVAL=1 only when you intentionally want to spend calls on it.\n",
        encoding="utf-8",
    )
    print(f"train={len(train)} val={len(val)} test={len(test)}")


if __name__ == "__main__":
    main()
