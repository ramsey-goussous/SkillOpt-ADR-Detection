# Skill: Suspected ADR Signal Extraction from Clinical Notes

## Purpose
Extract suspected adverse drug reaction (ADR) signals from a clinical note. The goal is **not** to prove true pharmacologic causality. The goal is to identify medication-related adverse-event signals that a clinician may need to review, and to separate them cleanly from events that are unlinked to drugs or that should not be flagged at all.

## Core definitions
- **Adverse event (AE):** an unfavorable symptom, sign, lab abnormality, or clinical deterioration mentioned in the note, whether or not it is drug-related.
- **Suspected ADR signal:** an AE that the note explicitly or implicitly links to a medication, drug class, chemotherapy, antibiotic, analgesic, anticoagulant, steroid, immunotherapy, contrast, or other treatment.
- **Drug–reaction pair:** a suspected medication paired with a suspected reaction/event, linked by evidence in the note. This pair is the primary unit of extraction.

## What to extract as a suspected ADR signal
Extract a suspected ADR signal when the note contains evidence such as:
- the reaction began after starting, increasing, or receiving a medication;
- the note directly states a suspected drug reaction, intolerance, allergy, or toxicity;
- the medication is stopped, held, reduced, switched, or treated **because of** the event;
- a known medication toxicity is named with supporting clinical context;
- a lab abnormality is plausibly linked to a drug and the note provides supporting evidence;
- the note uses words such as "due to," "secondary to," "after," "post," "s/p," "reaction," "allergy," "toxicity," "side effect," "intolerance," "held," "stopped because," or "suspected."

## What NOT to overcall
Do **not** report a suspected ADR signal when:
- a symptom is mentioned with no medication link;
- a medication is being used to **treat** the symptom rather than cause it;
- the event is clearly explained by the underlying disease and no drug link is stated or implied;
- the reaction is negated ("no rash," "denies," "ruled out");
- the reaction is only historical and not relevant to the current encounter (unless the task explicitly asks for historical reactions);
- there is not enough evidence to link the event to a medication. In that case place it in `unlinked_adverse_events`.

## High-risk false positives to avoid
- **Historical-only reactions:** If the note says the reaction happened in a prior cycle, previous admission, PMH/allergy list, or "last time," and there are no active symptoms today, do not extract an active ADR pair. Put the span in `negative_controls` with `why_not_adr: historical_only`.
- **Medication treats symptom:** If the drug is given as treatment, prophylaxis, or pre-medication for the event, do not reverse the relationship. Examples: ondansetron for nausea, senna/lactulose for constipation, naloxone for oversedation, steroids for immune toxicity, insulin for hyperglycemia.
- **Disease or trauma:** Disease progression, infection, obstruction, tumor bleeding, malignant ascites, fractures, sprains, and mechanical injuries are not ADRs unless the note explicitly links them to a medication.
- **Mere co-occurrence:** A drug and a symptom/lab in the same note is not enough. Require a stated link, clear temporal/action link, or clinician action because of the event.
- **Multifactorial cases:** Extract the minimal supported pair set. Do not create extra downstream pairs unless the note explicitly supports them. For example, if bleeding is due to warfarin and thrombocytopenia is due to chemotherapy, extract warfarin -> bleeding and chemotherapy -> thrombocytopenia; do not also add chemotherapy -> bleeding unless stated.

## Critical rule about common side effects
A common or expected side effect **can still be** a medication-related adverse event if the note links it to the drug. Do not exclude something just because it is a known/common side effect (e.g. chemotherapy-induced nausea, opioid-induced constipation, vancomycin-associated AKI, steroid-induced hyperglycemia, antibiotic-associated diarrhea). Instead, extract it and classify the strength of evidence.

## Causality vs. illness — the safe framing
Classify whether the note contains evidence supporting a medication-related link, while also identifying competing non-medication explanations when present. **Do not establish definitive causality and do not replace clinician judgment.** If a symptom could be explained by the underlying illness and no medication link is stated or implied, place it in `unlinked_adverse_events`, not in `suspected_adr_signals`.

## Causality assertion labels (choose exactly one per pair)
- **explicit** — the note directly states the drug caused or likely caused the reaction (e.g. "rash due to ceftriaxone").
- **probable** — strong temporal/action evidence supports the link (e.g. drug held after the event, rechallenge avoided).
- **possible** — drug and event are close in context but causality is uncertain.
- **negated** — the note says the reaction did not occur or was ruled out.
- **unlikely** — the note suggests another cause is more likely.
- **none** — no drug–event relationship is present.

## Output requirements
- Return **only** valid JSON matching the provided output schema. No prose outside the JSON.
- Populate three arrays: `suspected_adr_signals`, `unlinked_adverse_events`, `negative_controls`.
- Always include an exact `evidence_quote` that appears verbatim in the note.
- Use only information from the note. Do not invent medications, reactions, diagnoses, dates, or lab values.
- If uncertain whether a link exists, prefer `possible` or move the item to `unlinked_adverse_events`, rather than forcing an ADR.
- Copy `note_id` verbatim from the input.
- Copy normalized reaction terms in plain clinical English where possible. Prefer "bleeding" over "haemorrhage," "acute kidney injury" over obscure synonyms, and keep abbreviations expanded when the note supports them.

## Worked micro-examples
- "Nausea after cisplatin." → ADR signal: cisplatin → nausea; temporality after_drug; causality probable.
- "Started vancomycin, Cr rose to 2.1, vanco held." → ADR signal: vancomycin → acute kidney injury; probable.
- "Pt c/o nausea, known gastric CA progression." → unlinked AE: nausea (better_explained_by_illness).
- "No rash after ceftriaxone." → negative_control: text "No rash after ceftriaxone", why_not_adr negated.
- "Ondansetron given for nausea." → negative_control: medication_treats_symptom (do NOT say ondansetron caused nausea).
- "Old penicillin allergy, no reaction today." → negative_control: historical_only.
