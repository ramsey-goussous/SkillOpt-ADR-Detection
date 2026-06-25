# ADR SkillOpt Run

Portable ADR extraction optimization project for SkillOpt.

This clean copy starts from `skills/base_skill.md` only. It does not include
the optimized skill, previous run logs, paper drafts, communication notes,
debug runs, or quota-limited runner modes from the working folder.

## Project Layout

- `data/synthetic_notes.json` - synthetic ADR notes and gold labels.
- `real_data/` - local-only de-identified real notes for final evaluation.
- `skills/base_skill.md` - the only committed starting skill.
- `skillopt_adr/` - ADR environment copied into `external/SkillOpt/skillopt/envs/adr`.
- `scorer/` - ADR scorer and schema.
- `config/adr_skillopt.yaml` - SkillOpt configuration for this task.
- `scripts/` - data split, SkillOpt patching, and result summary helpers.
- `run_adr_skillopt.ps1` - one command to install, run, and collect results.
- `results/` - generated run outputs; intentionally ignored by Git.
- `real_data_split/` - generated real-data eval split; intentionally ignored by Git.
- `external/SkillOpt/` - cloned automatically; intentionally ignored by Git.

## Requirements

Install these on the machine that will run the experiment:

- Git for Windows
- Python 3.10 or newer
- Claude Code CLI, already logged in

Check Claude before running:

```powershell
claude
```

If the CLI asks you to log in, complete that first.

## Click-To-Run Files

On Windows, double-click one of these files from this folder:

- `RUN_FROM_BASE.bat` - starts from the committed `skills/base_skill.md`.
- `RUN_FROM_BEST.bat` - starts from `results/best_skill.md` after a previous successful run.
- `RUN_REAL_DATA.bat` - runs prediction/scoring on `real_data/real_notes.json` without training.

The run scripts set the usual defaults for you:

- target model: `claude-sonnet-4-6`
- optimizer model: `claude-sonnet-4-6`
- epochs: `1`
- per-note timeout: `240` seconds
- per-note retries: `2`
- test evaluation: off

`RUN_REAL_DATA.bat` uses `results/best_skill.md` when it exists; otherwise it
falls back to `skills/base_skill.md`.

## First Run By Command

From a fresh clone:

```powershell
cd "C:\path\to\ADR study Git"
$env:TARGET_MODEL = "claude-sonnet-4-6"
$env:OPTIMIZER_MODEL = "claude-sonnet-4-6"
$env:NUM_EPOCHS = "1"
$env:ADR_EXEC_TIMEOUT = "240"
$env:ADR_MODEL_RETRIES = "2"
powershell -ExecutionPolicy Bypass -File .\run_adr_skillopt.ps1
```

The runner will create `.venv`, clone Microsoft SkillOpt into
`external/SkillOpt`, check out the known working SkillOpt commit
`6940e46f4e0e537a1d7ca8432f24248d0d3550f5`, install it, copy in the ADR
environment, generate the train/validation/test split, patch SkillOpt for the
ADR environment and Windows Claude prompt handling, and run optimization.

## Continue From A New Best Skill

After a successful run, this repo may contain `results/best_skill.md`. The
easiest continuation is to double-click `RUN_FROM_BEST.bat`.

The equivalent command is:

```powershell
cd "C:\path\to\ADR study Git"
$env:SKILL_SOURCE = (Resolve-Path .\results\best_skill.md).Path
powershell -ExecutionPolicy Bypass -File .\run_adr_skillopt.ps1
```

To start over from the committed base skill:

```powershell
Remove-Item Env:\SKILL_SOURCE -ErrorAction SilentlyContinue
powershell -ExecutionPolicy Bypass -File .\run_adr_skillopt.ps1
```

## Outputs

The runner writes:

- `results/RESULTS_SUMMARY.md`
- `results/results.json`
- `results/best_skill.md`
- `results/history.json`
- `results/run_logs/`
- `results/sessions/`

`results/RESULTS_SUMMARY.md` and `results/results.json` include:

- starting score, ending score, best score, and improvement
- SkillOpt training wall time
- total runner elapsed time
- total prompt, completion, and combined token counts when reported by SkillOpt

The paper is not built by this project. Final paper writing should happen
separately after you decide which run is reportable.

## Real Data Evaluation

Put de-identified real notes in:

```text
real_data/real_notes.json
```

Then double-click:

```text
RUN_REAL_DATA.bat
```

The real data file is ignored by Git. Use this JSON shape:

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

`gold` is optional. If present, the script computes scores. If absent, it saves
predictions only.

Real-data outputs go under:

```text
results/real_data/
```

The latest summary is copied to:

```text
results/real_data/LATEST_REAL_DATA_SUMMARY.md
```
