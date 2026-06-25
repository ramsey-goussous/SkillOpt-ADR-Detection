# Real Data Folder

Put de-identified real notes here as:

```text
real_data/real_notes.json
```

The actual real-data files are ignored by Git and should not be committed.

Expected JSON shape:

```json
[
  {
    "id": "REAL_001",
    "note_text": "De-identified clinical note text...",
    "gold": {
      "suspected_adr_signals": [],
      "unlinked_adverse_events": [],
      "negative_controls": []
    }
  }
]
```

`gold` is optional. If it is present, `RUN_REAL_DATA.bat` will compute scores.
If it is absent, the script will save predictions only.
