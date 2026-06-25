#!/usr/bin/env python3
"""Box 3 — the grader.

Compares the brain's answers to the answer key (1_notes/synthetic_notes.json)
and prints a 0-1 score, broken into the parts that make it up.

Usage:
  python grade.py                 # self-test: grades the answer key vs itself (should be 1.000)
  python grade.py PREDICTIONS.json   # grades real predictions
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scorer as S

GOLD_FILE = os.path.join(HERE, "..", "data", "synthetic_notes.json")

def load_gold():
    data = json.load(open(GOLD_FILE, encoding="utf-8"))
    return [{"note_id": n["id"], "note_text": n["note_text"], "gold": n["gold"]} for n in data]

def normalize_pred(pred, gold):
    # accept items keyed by "id" or "note_id"; or the answer-key shape (has "gold")
    out = []
    for p in pred:
        nid = p.get("note_id") or p.get("id")
        body = p.get("gold", p)
        out.append({"note_id": nid,
                    "suspected_adr_signals": body.get("suspected_adr_signals", []),
                    "unlinked_adverse_events": body.get("unlinked_adverse_events", []),
                    "negative_controls": body.get("negative_controls", [])})
    return out

def main():
    gold = load_gold()
    if len(sys.argv) > 1:
        pred = json.load(open(sys.argv[1], encoding="utf-8"))
        label = os.path.basename(sys.argv[1])
    else:
        pred = json.load(open(GOLD_FILE, encoding="utf-8"))   # self-test
        label = "SELF-TEST (answer key vs itself)"
    r = S.score(gold, S.get_pred_map(normalize_pred(pred, gold)), 0.30)
    print(f"\nGrading: {label}")
    print(f"  TOTAL score        : {r['composite_score']:.3f}   (0 = useless, 1 = perfect)")
    print(f"   - drug+reaction    : {r['pair_f1']:.3f}   (did it name the right drug AND reaction?)")
    print(f"   - reaction only    : {r['reaction_f1']:.3f}   (did it at least spot the reaction?)")
    print(f"   - causality wording: {r['causality_macro_f1']:.3f}   (did it judge the strength of evidence right?)")
    print(f"   - didn't over-call : {r['negative_note_precision']:.3f}   (did it avoid inventing ADRs on clean notes?)")
    print(f"  made-up-ADR rate    : {r['hallucinated_adr_rate']:.3f}   (lower is better)")
    worst = [n for n in sorted(r['per_note'], key=lambda x: x['pair_f1']) if n['pair_fp'] or n['pair_fn']][:5]
    if worst:
        print("  notes it got most wrong:")
        for n in worst:
            print(f"     {n['note_id']}: missed {n['pair_fn']}, invented {n['pair_fp']}")
    print()

if __name__ == "__main__":
    main()
