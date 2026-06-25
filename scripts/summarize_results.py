#!/usr/bin/env python3
"""Summarize the ADR SkillOpt run into results/results.json and Markdown."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RUN_DIR = ROOT / "external" / "SkillOpt" / "outputs" / "adr_run"
RUN_STATUS = RESULTS / "run_status.json"
RUN_SUMMARY = RUN_DIR / "summary.json"

FATAL_PATTERNS = (
    "api_error_status",
    "session limit",
    "rate limit",
    "invalid api key",
    "authentication",
    "not logged in",
    "unknown model",
    "invalid model",
    "fatal model backend error",
    "timed out",
    "timeout",
    "winerror 206",
)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def clean_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return " ".join(text.split())


def is_fatal(text: object) -> bool:
    lowered = str(text or "").lower()
    return any(pattern in lowered for pattern in FATAL_PATTERNS)


def compact_reason(reason: object) -> str:
    raw = str(reason or "")
    idx = raw.find("{")
    if idx >= 0:
        try:
            payload = json.loads(raw[idx:])
        except Exception:
            payload = None
        if isinstance(payload, dict):
            result = clean_text(payload.get("result", ""))
            status = payload.get("api_error_status")
            if result:
                if "session limit" in result.lower():
                    return f"Claude session limit: {result}"
                if status:
                    return f"Claude API status {status}: {result}"
                return result
            if status:
                return f"Claude API status {status}"
    text = clean_text(raw)
    return text[:177].rstrip() + "..." if len(text) > 180 else text


def dataset_summary() -> dict:
    notes = load_json(ROOT / "data" / "synthetic_notes.json", [])
    pairs = sum(len(n.get("gold", {}).get("suspected_adr_signals", [])) for n in notes)
    out = {"total_notes": len(notes), "drug_reaction_pairs": pairs, "train": 0, "val": 0, "test": 0}
    for split in ("train", "val", "test"):
        items = load_json(ROOT / "data_split" / split / "items.json", [])
        out[split] = len(items) if isinstance(items, list) else 0
    return out


def scan_errors() -> list[dict]:
    errors = []
    if not RUN_DIR.exists():
        return errors
    for path in RUN_DIR.rglob("results.jsonl"):
        rel = str(path.relative_to(RUN_DIR))
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            reason = str(row.get("fail_reason", ""))
            if row.get("agent_ok") is False and reason:
                errors.append({
                    "path": rel,
                    "line": line_no,
                    "id": row.get("id", ""),
                    "fatal": is_fatal(reason),
                    "reason": compact_reason(reason),
                })
    return errors


def read_log_reason(path: object, exit_code: object) -> str:
    base = f"train.py exited with code {exit_code}."
    if not path:
        return base
    log_path = Path(str(path))
    if not log_path.exists():
        return f"{base} See {path}."
    text = log_path.read_text(encoding="utf-8", errors="replace")
    lowered = text.lower()
    if "session limit" in lowered:
        match = re.search(r'"result"\s*:\s*"([^"]+)"', text)
        detail = clean_text(match.group(1)) if match else "Claude session limit"
        return f"Claude session limit: {detail}. {base}"
    if "api_error_status" in lowered:
        status = re.search(r'"api_error_status"\s*:\s*(\d+)', text)
        label = f"Claude API status {status.group(1)}" if status else "Claude API error"
        return f"{label}. {base}"
    for line in text.splitlines():
        if is_fatal(line):
            return f"{compact_reason(line)}. {base}"
    return f"{base} See {path}."


def rollout_scores(path: Path) -> tuple[float | None, float | None]:
    if not path.exists():
        return None, None
    hard_values = []
    soft_values = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row.get("hard"), (int, float)):
            hard_values.append(float(row["hard"]))
        if isinstance(row.get("soft"), (int, float)):
            soft_values.append(float(row["soft"]))
    hard = sum(hard_values) / len(hard_values) if hard_values else None
    soft = sum(soft_values) / len(soft_values) if soft_values else None
    return hard, soft


def gate_score(hard: float | None, soft: float | None, cfg: dict) -> float | None:
    if hard is None and soft is None:
        return None
    metric = str(cfg.get("gate_metric") or "hard").lower()
    if metric == "soft":
        return soft if soft is not None else hard
    return hard if hard is not None else soft


def score_summary() -> tuple[float | None, float | None, float | None, float | None]:
    runtime = load_json(RUN_DIR / "runtime_state.json", {})
    config = load_json(RUN_DIR / "config.json", {})
    base_hard, base_soft = rollout_scores(RUN_DIR / "selection_eval_baseline" / "results.jsonl")
    start = gate_score(base_hard, base_soft, config if isinstance(config, dict) else {})
    best = runtime.get("best_score") if isinstance(runtime, dict) else None
    end = runtime.get("current_score") if isinstance(runtime, dict) else None
    start = float(start) if isinstance(start, (int, float)) else None
    best = float(best) if isinstance(best, (int, float)) else None
    end = float(end) if isinstance(end, (int, float)) else None
    improvement = best - start if start is not None and best is not None else None
    return start, best, end, improvement


def token_estimate(path: Path) -> int | None:
    if not path.exists():
        return None
    return int(len(path.read_text(encoding="utf-8", errors="replace").split()) * 1.3)


def fmt_seconds(seconds: object) -> str | None:
    if not isinstance(seconds, (int, float)):
        return None
    total = int(round(float(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def token_total(token_summary: dict) -> dict | None:
    if not isinstance(token_summary, dict):
        return None
    total = token_summary.get("_total")
    return total if isinstance(total, dict) else None


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    run_status = load_json(RUN_STATUS, {})
    skillopt_summary = load_json(RUN_SUMMARY, {})
    if not isinstance(skillopt_summary, dict):
        skillopt_summary = {}
    token_summary = skillopt_summary.get("token_summary", {})
    if not isinstance(token_summary, dict):
        token_summary = {}
    total_tokens = token_total(token_summary)
    training_wall_time_s = skillopt_summary.get("total_wall_time_s")
    runner_elapsed_s = (
        run_status.get("runner_elapsed_seconds")
        if isinstance(run_status, dict)
        else None
    )
    errors = scan_errors()
    if isinstance(run_status, dict) and run_status.get("train_exit_code") not in (None, 0):
        errors.insert(0, {
            "path": os.path.basename(str(run_status.get("train_log", "train.log"))),
            "line": 0,
            "id": "",
            "fatal": True,
            "reason": read_log_reason(run_status.get("train_log"), run_status.get("train_exit_code")),
        })

    fatal_errors = [err for err in errors if err["fatal"]]
    ran = RUN_DIR.exists() or bool(run_status.get("ran"))
    valid = ran and not fatal_errors and run_status.get("train_exit_code") in (None, 0)
    start, best, end, improvement = score_summary()

    result = {
        "ran": ran,
        "valid": valid,
        "status": "valid" if valid else ("invalid" if ran else "not_run"),
        "starting_score": round(start, 4) if valid and start is not None else None,
        "best_score": round(best, 4) if valid and best is not None else None,
        "ending_score": round(end, 4) if valid and end is not None else None,
        "improvement": round(improvement, 4) if valid and improvement is not None else None,
        "checkpoint_starting_score": round(start, 4) if start is not None else None,
        "checkpoint_best_score": round(best, 4) if best is not None else None,
        "checkpoint_ending_score": round(end, 4) if end is not None else None,
        "dataset": dataset_summary(),
        "skill_source": run_status.get("skill_source") if isinstance(run_status, dict) else None,
        "best_skill_tokens": token_estimate(RUN_DIR / "best_skill.md") if valid else None,
        "training_wall_time_s": training_wall_time_s,
        "runner_elapsed_seconds": runner_elapsed_s,
        "token_summary": token_summary,
        "total_tokens": total_tokens,
        "errors": errors[:20],
        "run_status": run_status,
    }
    (RESULTS / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    dataset = result["dataset"]
    lines = ["# ADR SkillOpt Results", ""]
    if not ran:
        lines.append("_No run has been collected yet._")
    elif not valid:
        lines.extend([
            "**RUN INVALID - do not report these scores as model performance.**",
            "",
            f"- Fatal operational errors found: {len(fatal_errors)}",
        ])
        if fmt_seconds(training_wall_time_s) or fmt_seconds(runner_elapsed_s):
            lines.append(
                f"- Time spent: training={fmt_seconds(training_wall_time_s) or 'n/a'}, "
                f"runner={fmt_seconds(runner_elapsed_s) or 'n/a'}."
            )
        if total_tokens:
            lines.append(
                f"- Tokens consumed before failure: {total_tokens.get('total_tokens', 0):,} "
                f"(prompt={total_tokens.get('prompt_tokens', 0):,}, "
                f"completion={total_tokens.get('completion_tokens', 0):,}, "
                f"calls={total_tokens.get('calls', 0):,})."
            )
        for err in fatal_errors[:3]:
            lines.append(f"- `{err['path']}` note `{err['id']}`: {err['reason']}")
        if start is not None or best is not None or end is not None:
            lines.append("")
            lines.append(
                "Checkpoint only: "
                f"start={start if start is not None else 'n/a'}, "
                f"best={best if best is not None else 'n/a'}, "
                f"end={end if end is not None else 'n/a'}."
            )
    else:
        lines.append(
            f"- Data: {dataset['train']} train + {dataset['val']} validation notes "
            f"({dataset['drug_reaction_pairs']} gold drug-reaction pairs total)."
        )
        lines.append(f"- Starting score: {result['starting_score']}")
        lines.append(f"- Best score: {result['best_score']}")
        lines.append(f"- Ending score: {result['ending_score']}")
        lines.append(f"- Improvement: {result['improvement']:+.4f}")
        if fmt_seconds(training_wall_time_s) or fmt_seconds(runner_elapsed_s):
            lines.append(
                f"- Time spent: training={fmt_seconds(training_wall_time_s) or 'n/a'}, "
                f"runner={fmt_seconds(runner_elapsed_s) or 'n/a'}."
            )
        if total_tokens:
            lines.append(
                f"- Tokens consumed: {total_tokens.get('total_tokens', 0):,} "
                f"(prompt={total_tokens.get('prompt_tokens', 0):,}, "
                f"completion={total_tokens.get('completion_tokens', 0):,}, "
                f"calls={total_tokens.get('calls', 0):,})."
            )
        if result["best_skill_tokens"]:
            lines.append(f"- Best skill length: about {result['best_skill_tokens']} tokens.")

    (RESULTS / "RESULTS_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote results/results.json")
    print("wrote results/RESULTS_SUMMARY.md")
    print("")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
