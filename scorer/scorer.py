#!/usr/bin/env python3
"""Scorer for suspected-ADR-signal extraction.

Computes the four evaluation layers and the single composite scalar that
SkillOpt optimizes against:

    score = 0.50*pair_F1
          + 0.25*reaction_F1
          + 0.15*causality_macroF1
          + 0.10*negative_note_precision

Inputs
------
--gold : dataset JSON. List of notes, each {note_id, note_text, gold:{...}}.
         (synthetic_notes.json has this shape.)
--pred : predictions JSON. Either the same shape (objects with .gold) OR a
         list of bare prediction objects {note_id, suspected_adr_signals,
         unlinked_adverse_events, negative_controls}. Both are accepted.

Matching is intentionally lenient (token-overlap, not exact string) because a
clinician would accept "AKI" for "acute kidney injury". Thresholds are CLI
flags so the matching policy is explicit and auditable. See scorer/README.md.
"""
import argparse, json, re, sys
from collections import defaultdict

STOP = {"the", "a", "an", "of", "to", "and", "or", "with", "for", "in", "on",
        "associated", "induced", "related", "drug", "reaction", "suspected"}


def norm_tokens(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 /]", " ", s)
    s = s.replace("/", " ")
    toks = [t for t in s.split() if len(t) > 2 and t not in STOP]
    return set(toks)


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def drug_match(g, p):
    gt, pt = norm_tokens(g), norm_tokens(p)
    if not gt or not pt:
        return False
    return len(gt & pt) >= 1  # share at least one drug token (handles combos)


def reaction_match(g, p, thr):
    gt, pt = norm_tokens(g), norm_tokens(p)
    if not gt or not pt:
        return False
    if gt <= pt or pt <= gt:  # subset either direction
        return True
    return jaccard(gt, pt) >= thr


def prf(tp, fp, fn):
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def load(path):
    with open(path) as f:
        return json.load(f)


def get_pred_map(pred):
    """Return {note_id: {suspected_adr_signals, unlinked_adverse_events, negative_controls}}."""
    out = {}
    for item in pred:
        body = item.get("gold", item)  # accept dataset-shaped or bare predictions
        out[item["note_id"]] = {
            "suspected_adr_signals": body.get("suspected_adr_signals", []),
            "unlinked_adverse_events": body.get("unlinked_adverse_events", []),
            "negative_controls": body.get("negative_controls", []),
        }
    return out


def match_pairs(gold_sigs, pred_sigs, rthr):
    """Greedy one-to-one matching of pred pairs to gold pairs.
    Returns (matched_list, n_gold, n_pred). matched_list = [(gold, pred)]."""
    used = set()
    matched = []
    for gi, g in enumerate(gold_sigs):
        best = None
        for pi, p in enumerate(pred_sigs):
            if pi in used:
                continue
            if drug_match(g["suspected_drug"], p.get("suspected_drug", "")) and \
               reaction_match(g["normalized_reaction"], p.get("normalized_reaction", ""), rthr):
                best = pi
                break
        if best is not None:
            used.add(best)
            matched.append((g, pred_sigs[best]))
    return matched, len(gold_sigs), len(pred_sigs)


def score(gold_data, pred_map, rthr=0.3):
    # primary: pair F1 ; secondary: reaction-only F1 ; causality macro-F1 ; neg-note precision
    pair_tp = pair_fp = pair_fn = 0
    rx_tp = rx_fp = rx_fn = 0
    caus_gold = defaultdict(int)
    caus_pred_correct = defaultdict(int)
    caus_pred_total = defaultdict(int)
    neg_notes = 0
    neg_clean = 0
    halluc_signals = 0
    total_pred_signals = 0
    per_note = []

    for note in gold_data:
        nid = note["note_id"]
        g = note["gold"]
        p = pred_map.get(nid, {"suspected_adr_signals": [], "unlinked_adverse_events": [], "negative_controls": []})
        gsig = g["suspected_adr_signals"]
        psig = p["suspected_adr_signals"]
        total_pred_signals += len(psig)

        # ---- pair-level ----
        matched, ng, npd = match_pairs(gsig, psig, rthr)
        tp = len(matched)
        pair_tp += tp
        pair_fp += npd - tp
        pair_fn += ng - tp

        # ---- reaction-only (greedy match on normalized reaction, drug ignored) ----
        used_r = set()
        rtp = 0
        for s in gsig:
            for pi, ps in enumerate(psig):
                if pi in used_r:
                    continue
                if reaction_match(s["normalized_reaction"], ps.get("normalized_reaction", ""), rthr):
                    used_r.add(pi)
                    rtp += 1
                    break
        rx_tp += rtp
        rx_fp += len(psig) - rtp
        rx_fn += len(gsig) - rtp

        # ---- causality on matched pairs ----
        for gp, pp in matched:
            gl = gp["causality_assertion"]
            pl = pp.get("causality_assertion", "none")
            caus_gold[gl] += 1
            caus_pred_total[pl] += 1
            if gl == pl:
                caus_pred_correct[gl] += 1

        # ---- negative-note safety ----
        if len(gsig) == 0:
            neg_notes += 1
            if len(psig) == 0:
                neg_clean += 1
            else:
                halluc_signals += len(psig)

        _, _, note_pair_f = prf(tp, npd - tp, ng - tp)
        per_note.append({"note_id": nid, "pair_tp": tp, "pair_fp": npd - tp,
                         "pair_fn": ng - tp, "pair_f1": round(note_pair_f, 3)})

    pair_p, pair_r, pair_f = prf(pair_tp, pair_fp, pair_fn)
    rx_p, rx_r, rx_f = prf(rx_tp, rx_fp, rx_fn)

    # causality macro-F1 across classes present in gold
    classes = set(caus_gold) | set(caus_pred_total)
    f1s = []
    for c in classes:
        tp = caus_pred_correct.get(c, 0)
        fp = caus_pred_total.get(c, 0) - tp
        fn = caus_gold.get(c, 0) - tp
        if caus_gold.get(c, 0) == 0 and caus_pred_total.get(c, 0) == 0:
            continue
        _, _, f = prf(tp, fp, fn)
        # only average over classes that appear in gold (avoid rewarding empty classes)
        if caus_gold.get(c, 0) > 0:
            f1s.append(f)
    caus_macro = sum(f1s) / len(f1s) if f1s else 0.0

    neg_note_prec = neg_clean / neg_notes if neg_notes else 1.0
    halluc_rate = halluc_signals / total_pred_signals if total_pred_signals else 0.0

    composite = (0.50 * pair_f + 0.25 * rx_f + 0.15 * caus_macro + 0.10 * neg_note_prec)

    return {
        "composite_score": round(composite, 4),
        "pair_f1": round(pair_f, 4),
        "pair_precision": round(pair_p, 4),
        "pair_recall": round(pair_r, 4),
        "reaction_f1": round(rx_f, 4),
        "reaction_precision": round(rx_p, 4),
        "reaction_recall": round(rx_r, 4),
        "causality_macro_f1": round(caus_macro, 4),
        "negative_note_precision": round(neg_note_prec, 4),
        "hallucinated_adr_rate": round(halluc_rate, 4),
        "counts": {
            "pair_tp": pair_tp, "pair_fp": pair_fp, "pair_fn": pair_fn,
            "negative_notes": neg_notes, "negative_notes_clean": neg_clean,
        },
        "per_note": per_note,
        "weights": {"pair": 0.50, "reaction": 0.25, "causality": 0.15, "neg_precision": 0.10},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--reaction-threshold", type=float, default=0.3,
                    help="Jaccard threshold for fuzzy reaction matching (default 0.3).")
    ap.add_argument("--json", action="store_true", help="emit full JSON result")
    args = ap.parse_args()

    gold = load(args.gold)
    pred = load(args.pred)
    res = score(gold, get_pred_map(pred), args.reaction_threshold)

    if args.json:
        print(json.dumps(res, indent=2))
        return

    print(f"composite_score            : {res['composite_score']:.4f}")
    print(f"  pair_f1        (w 0.50)  : {res['pair_f1']:.4f}  (P {res['pair_precision']:.3f} / R {res['pair_recall']:.3f})")
    print(f"  reaction_f1    (w 0.25)  : {res['reaction_f1']:.4f}  (P {res['reaction_precision']:.3f} / R {res['reaction_recall']:.3f})")
    print(f"  causality_macroF1 (w0.15): {res['causality_macro_f1']:.4f}")
    print(f"  neg_note_prec  (w 0.10)  : {res['negative_note_precision']:.4f}")
    print(f"hallucinated_adr_rate      : {res['hallucinated_adr_rate']:.4f}")
    print(f"pairs  TP/FP/FN            : {res['counts']['pair_tp']}/{res['counts']['pair_fp']}/{res['counts']['pair_fn']}")
    print(f"negative notes clean       : {res['counts']['negative_notes_clean']}/{res['counts']['negative_notes']}")

if __name__ == "__main__":
    sys.exit(main())
