"""ADR rollout - single-turn extraction + batch execution (mirrors the SearchQA env).

For each note: send (skill + schema + note) to the target model, parse the JSON
prediction, score it with the layered ADR scorer, and return a result row with
the SkillOpt-required fields: id, hard (0/1), soft (0-1).
"""
from __future__ import annotations
import json, os, re, time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from skillopt.model import chat_target
from skillopt.prompts import load_prompt
from skillopt.envs.adr.evaluator import evaluate

_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, "output_schema.json"), encoding="utf-8") as _f:
    _SCHEMA = _f.read()
_FATAL_BACKEND_PATTERNS = (
    "api_error_status\":429",
    "api_error_status': 429",
    "claude backend failed",
    "session limit",
    "rate limit",
    "timed out",
    "timeout",
    "timeoutexpired",
    "invalid api key",
    "authentication",
    "not logged in",
    "run `claude",
    "unknown model",
    "invalid model",
    "not available",
)


def _build_system(skill_content: str) -> str:
    section = f"## Skill\n{skill_content.strip()}\n\n" if skill_content.strip() else ""
    return load_prompt("rollout_system", env="adr").format(skill_section=section)

def _build_user(note_id: str, note_text: str) -> str:
    return (f"## Output schema (return ONLY JSON matching this)\n{_SCHEMA}\n\n"
            f"## Note\nnote_id: {note_id}\n\"\"\"\n{note_text}\n\"\"\"\n\n"
            f"Return only the JSON object. Copy note_id exactly as {note_id}.")


def _empty_prediction(note_id: str) -> dict:
    return {
        "note_id": note_id,
        "suspected_adr_signals": [],
        "unlinked_adverse_events": [],
        "negative_controls": [],
    }


def _parse_json(text: str, note_id: str) -> dict:
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text or ""):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            obj.setdefault("note_id", note_id)
            obj.setdefault("suspected_adr_signals", [])
            obj.setdefault("unlinked_adverse_events", [])
            obj.setdefault("negative_controls", [])
            return obj
    return _empty_prediction(note_id)


def _is_fatal_backend_error(text: str) -> bool:
    lowered = (text or "").lower()
    return any(pat in lowered for pat in _FATAL_BACKEND_PATTERNS)

def process_one(item: dict, out_root: str, skill_content: str, exec_timeout: int = 120) -> dict:
    nid = str(item["id"])
    res = {"id": nid, "task_type": "adr", "hard": 0, "soft": 0.0,
           "response": "", "fail_reason": "", "agent_ok": False}
    try:
        pred_dir = os.path.join(out_root, "predictions", nid)
        os.makedirs(pred_dir, exist_ok=True)
        system = _build_system(skill_content)
        user = _build_user(nid, item.get("note_text", ""))
        retries = int(os.environ.get("ADR_MODEL_RETRIES", "1"))
        resp_text, _ = chat_target(system=system, user=user, max_completion_tokens=2000,
                                   retries=retries, stage="rollout", timeout=exec_timeout)
        prediction = _parse_json(resp_text, nid)
        ev = evaluate(prediction, item)
        res.update({"response": resp_text, "agent_ok": True,
                    "hard": ev["hard"], "soft": ev["soft"],
                    "pair_f1": ev["pair_f1"], "negative_note_precision": ev["negative_note_precision"]})
        if ev["hard"] < 1:
            res["fail_reason"] = (f"pair_f1={ev['pair_f1']:.2f} neg_prec={ev['negative_note_precision']:.2f}")
        with open(os.path.join(pred_dir, "prediction.json"), "w", encoding="utf-8") as f:
            json.dump(prediction, f, ensure_ascii=False, indent=2)
        eval_detail = (f"[EVALUATION]\nnote_id: {nid}\nsoft(composite)={ev['soft']:.4f}  "
                       f"pair_f1={ev['pair_f1']:.4f}  neg_note_precision={ev['negative_note_precision']:.4f}")
        with open(os.path.join(pred_dir, "conversation.json"), "w", encoding="utf-8") as f:
            json.dump([{"role": "system", "content": system}, {"role": "user", "content": user},
                       {"role": "assistant", "content": resp_text}, {"role": "system", "content": eval_detail}],
                      f, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        msg = f"error: {e}"
        if _is_fatal_backend_error(msg):
            raise RuntimeError(msg) from e
        res["fail_reason"] = msg
    return res

def run_batch(items, out_root, skill_content, max_turns=1, exec_timeout=120, workers=8,
              diagnostic_mode=False, diagnostic_instruction="",
              diagnostic_trace_context_by_id=None, task_timeout=600) -> list[dict]:
    os.makedirs(out_root, exist_ok=True)
    results_path = os.path.join(out_root, "results.jsonl")
    done, existing = set(), []
    if os.path.exists(results_path):
        with open(results_path, encoding="utf-8") as _fh:
            for line in _fh:
                try:
                    r = json.loads(line); done.add(str(r["id"])); existing.append(r)
                except Exception:
                    pass
    pending = [it for it in items if str(it["id"]) not in done]
    if not pending:
        return existing
    results = list(existing)
    with open(results_path, "a") as outf:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(process_one, it, out_root, skill_content, exec_timeout): it for it in pending}
            remaining = set(futs)
            while remaining:
                fin, _ = wait(remaining, timeout=5, return_when=FIRST_COMPLETED)
                for fut in fin:
                    remaining.remove(fut)
                    try:
                        r = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        if _is_fatal_backend_error(str(exc)):
                            raise RuntimeError(
                                "Fatal model backend error; stopping run so it is not scored as model failure. "
                                f"Details: {exc}"
                            ) from exc
                        it = futs[fut]; r = {"id": str(it["id"]), "task_type": "adr",
                              "hard": 0, "soft": 0.0, "fail_reason": f"unexpected: {exc}"}
                    results.append(r)
                    outf.write(json.dumps(r, ensure_ascii=False) + "\n"); outf.flush()
                    status = "ok" if r.get("agent_ok") else "failed"
                    print(f"    [adr] {status:6s} id={r['id']} hard={r.get('hard')} soft={r.get('soft',0):.3f}", flush=True)
    return results
