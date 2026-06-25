"""Turn one model prediction into hard/soft scores.

The project-level scorer is corpus-based, but SkillOpt asks the environment for
one reward per note. Clean negative notes need special handling here: if a note
has no gold ADR pairs and the model predicts none, that is a success, not a
0.10 partial score from the corpus composite's negative-note component.
"""
from __future__ import annotations
from . import scorer as S   # bundled scorer, copied here by run_skillopt.ps1

def evaluate(prediction: dict, gold_item: dict) -> dict:
    nid = str(gold_item["id"])
    gold_signals = gold_item["gold"].get("suspected_adr_signals", [])
    pred = dict(prediction or {})
    pred["note_id"] = nid
    pred_signals = pred.get("suspected_adr_signals", []) or []

    if not gold_signals:
        clean = len(pred_signals) == 0
        return {
            "soft": 1.0 if clean else 0.0,
            "hard": 1 if clean else 0,
            "pair_f1": 1.0 if clean else 0.0,
            "reaction_f1": 1.0 if clean else 0.0,
            "causality_macro_f1": 1.0 if clean else 0.0,
            "negative_note_precision": 1.0 if clean else 0.0,
        }

    gold_data = [{"note_id": nid, "note_text": gold_item.get("note_text", ""),
                  "gold": gold_item["gold"]}]
    r = S.score(gold_data, S.get_pred_map([pred]), 0.30)
    return {
        "soft": float(r["composite_score"]),
        "hard": 1 if r["pair_f1"] >= 0.999 else 0,
        "pair_f1": r["pair_f1"], "reaction_f1": r["reaction_f1"],
        "causality_macro_f1": r["causality_macro_f1"],
        "negative_note_precision": r["negative_note_precision"],
    }
