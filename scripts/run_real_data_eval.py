#!/usr/bin/env python3
"""Run ADR prediction/scoring on the real-data split without training."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_predictions(out_root: Path) -> list[dict]:
    predictions = []
    pred_root = out_root / "predictions"
    if not pred_root.exists():
        return predictions
    for pred_path in sorted(pred_root.glob("*/prediction.json")):
        predictions.append(load_json(pred_path, {"note_id": pred_path.parent.name}))
    return predictions


def fmt_seconds(seconds: float) -> str:
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run eval-only ADR extraction on real notes.")
    parser.add_argument("--skill", required=True)
    parser.add_argument("--split-dir", required=True)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--target-model", default="claude-sonnet-4-6")
    parser.add_argument("--target-backend", default="claude_chat")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    skillopt_root = Path.cwd().resolve()
    sys.path.insert(0, str(skillopt_root))

    from skillopt.envs.adr.adapter import ADRAdapter
    from skillopt.model import (
        get_token_summary,
        reset_token_tracker,
        set_backend,
        set_optimizer_deployment,
        set_target_deployment,
    )
    from skillopt.utils import compute_score

    split_dir = Path(args.split_dir).resolve()
    out_root = Path(args.out_root).resolve()
    skill_path = Path(args.skill).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    set_backend(args.target_backend)
    set_target_deployment(args.target_model)
    set_optimizer_deployment(args.target_model)
    reset_token_tracker()

    skill_content = skill_path.read_text(encoding="utf-8")
    adapter = ADRAdapter(
        split_dir=str(split_dir),
        split_mode="split_dir",
        workers=args.workers,
    )
    adapter.setup({
        "env": "adr",
        "split_dir": str(split_dir),
        "split_mode": "split_dir",
        "out_root": str(out_root),
        "workers": args.workers,
    })

    items = adapter.build_eval_env(0, "valid_unseen", args.seed)
    labeled_count = sum(1 for item in items if isinstance(item.get("gold"), dict))
    print(f"real-data eval: notes={len(items)} labeled={labeled_count} unlabeled={len(items) - labeled_count}")
    print(f"skill={skill_path}")
    print(f"out_root={out_root}")

    started = time.time()
    results = adapter.rollout(items, skill_content, str(out_root))
    wall_time_s = round(time.time() - started, 1)
    scored_results = [row for row in results if row.get("scored", True) is not False]
    if scored_results:
        hard, soft = compute_score(scored_results)
    else:
        hard = None
        soft = None

    predictions = collect_predictions(out_root)
    write_json(out_root / "predictions.json", predictions)

    token_summary = get_token_summary()
    summary = {
        "skill": str(skill_path),
        "split_dir": str(split_dir),
        "target_backend": args.target_backend,
        "target_model": args.target_model,
        "n_items": len(items),
        "labeled_items": labeled_count,
        "unlabeled_items": len(items) - labeled_count,
        "scored_items": len(scored_results),
        "hard": hard,
        "soft": soft,
        "wall_time_s": wall_time_s,
        "token_summary": token_summary,
    }
    write_json(out_root / "real_eval_summary.json", summary)

    total = token_summary.get("_total", {}) if isinstance(token_summary, dict) else {}
    lines = [
        "# Real Data Evaluation",
        "",
        f"- Notes: {len(items)}",
        f"- Labeled notes: {labeled_count}",
        f"- Unlabeled notes: {len(items) - labeled_count}",
        f"- Skill: `{skill_path.name}`",
        f"- Model: `{args.target_model}`",
        f"- Time spent: {fmt_seconds(wall_time_s)}",
    ]
    if hard is not None and soft is not None:
        lines.append(f"- Hard score: {hard:.4f}")
        lines.append(f"- Soft score: {soft:.4f}")
    else:
        lines.append("- Scores: not computed because no gold labels were provided.")
    if total:
        lines.append(
            f"- Tokens consumed: {total.get('total_tokens', 0):,} "
            f"(prompt={total.get('prompt_tokens', 0):,}, "
            f"completion={total.get('completion_tokens', 0):,}, "
            f"calls={total.get('calls', 0):,})"
        )
    lines.extend([
        "",
        "Outputs:",
        "- `predictions.json`",
        "- `real_eval_summary.json`",
        "- `results.jsonl`",
        "- `predictions/<note_id>/prediction.json`",
    ])
    (out_root / "REAL_DATA_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
