#!/usr/bin/env python3
"""Apply the local patches needed for the ADR SkillOpt run.

This script is intentionally narrow:
  1. Register skillopt.envs.adr in SkillOpt's hard-coded environment registry.
  2. Make the Claude CLI backend pass long prompts through stdin/system-prompt
     files so Windows command-line length limits do not break optimization.

It is safe to run repeatedly.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ADR_MARK = '_ENV_REGISTRY["adr"]'
ADR_BLOCK = (
    "    try:\n"
    "        from skillopt.envs.adr.adapter import ADRAdapter\n"
    '        _ENV_REGISTRY["adr"] = ADRAdapter\n'
    "    except ImportError:\n"
    "        pass\n"
)

OLD_SYSTEM = (
    '        if system:\n'
    '            cmd.extend(["--append-system-prompt", system])\n'
)
NEW_SYSTEM = (
    '        if system:\n'
    '            _sys_file = os.path.join(temp_dir, "system_prompt.txt")\n'
    '            with open(_sys_file, "w", encoding="utf-8") as _sf:\n'
    '                _sf.write(system)\n'
    '            cmd.extend(["--append-system-prompt-file", _sys_file])\n'
)

OLD_RUNS = (
    (
        '        proc = subprocess.run(cmd + [prompt_for_cli], capture_output=True, '
        'text=True, timeout=timeout or 300, cwd=temp_dir)\n'
    ),
    (
        '        proc = subprocess.run(cmd + [prompt_for_cli], capture_output=True, '
        'text=True, encoding="utf-8", timeout=timeout or 300, cwd=temp_dir)\n'
    ),
)
NEW_RUN = (
    '        proc = subprocess.run(cmd, input=prompt_for_cli, capture_output=True, '
    'text=True, encoding="utf-8", errors="replace", timeout=timeout or 300, cwd=temp_dir)\n'
)

OLD_ERROR_CHECK = (
    '    if result_event is None:\n'
    '        raise RuntimeError("Claude backend did not return a result event.")\n'
    '    content = result_event.get("result") or result_event.get("content") or ""\n'
    '    return str(content), result_event\n'
)

REFLECT_UTF8_REPLACEMENTS = (
    ('with open(conv_path) as f:', 'with open(conv_path, encoding="utf-8") as f:'),
    ('with open(prompt_path) as f:', 'with open(prompt_path, encoding="utf-8") as f:'),
    ('with open(user_prompt_path) as f:', 'with open(user_prompt_path, encoding="utf-8") as f:'),
    ('with open(codex_trace_summary_path) as f:', 'with open(codex_trace_summary_path, encoding="utf-8") as f:'),
    ('with open(preview_path) as f:', 'with open(preview_path, encoding="utf-8") as f:'),
    ('with open(path) as f:', 'with open(path, encoding="utf-8") as f:'),
    ('with open(path, "w") as f:', 'with open(path, "w", encoding="utf-8") as f:'),
)
NEW_ERROR_CHECK = (
    '    if result_event is None:\n'
    '        raise RuntimeError("Claude backend did not return a result event.")\n'
    '    if result_event.get("is_error"):\n'
    '        detail = result_event.get("result") or result_event.get("content") or json.dumps(result_event, ensure_ascii=False)\n'
    '        raise RuntimeError(str(detail))\n'
    '    content = result_event.get("result") or result_event.get("content") or ""\n'
    '    return str(content), result_event\n'
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def patch_train(skillopt_root: Path) -> bool:
    train_py = skillopt_root / "scripts" / "train.py"
    if not train_py.exists():
        raise FileNotFoundError(train_py)
    src = read(train_py)
    if ADR_MARK in src:
        print("patch_skillopt: ADR registry already present")
        return False

    anchor = "def _register_builtins() -> None:"
    start = src.find(anchor)
    if start < 0:
        raise RuntimeError("Could not find _register_builtins() in scripts/train.py")
    first_try = src.find("\n    try:", start)
    if first_try < 0:
        raise RuntimeError("Could not find insertion point inside _register_builtins()")

    src = src[: first_try + 1] + ADR_BLOCK + src[first_try + 1:]
    write(train_py, src)
    print("patch_skillopt: inserted ADR registry block")
    return True


def patch_claude_backend(skillopt_root: Path) -> bool:
    backend_py = skillopt_root / "skillopt" / "model" / "claude_backend.py"
    if not backend_py.exists():
        raise FileNotFoundError(backend_py)
    src = read(backend_py)
    changed = False

    if "--append-system-prompt-file" not in src:
        if OLD_SYSTEM not in src:
            raise RuntimeError("Could not find Claude system-prompt command block")
        src = src.replace(OLD_SYSTEM, NEW_SYSTEM, 1)
        changed = True

    if "input=prompt_for_cli" not in src:
        for old_run in OLD_RUNS:
            if old_run in src:
                src = src.replace(old_run, NEW_RUN, 1)
                changed = True
                break
        else:
            raise RuntimeError("Could not find Claude subprocess.run prompt block")

    if 'result_event.get("is_error")' not in src:
        if OLD_ERROR_CHECK not in src:
            raise RuntimeError("Could not find Claude result-event error block")
        src = src.replace(OLD_ERROR_CHECK, NEW_ERROR_CHECK, 1)
        changed = True

    if changed:
        write(backend_py, src)
        print("patch_skillopt: patched Claude backend for Windows-safe prompts")
    else:
        print("patch_skillopt: Claude backend already patched")
    return changed


def patch_reflect_utf8(skillopt_root: Path) -> bool:
    reflect_py = skillopt_root / "skillopt" / "gradient" / "reflect.py"
    if not reflect_py.exists():
        raise FileNotFoundError(reflect_py)
    src = read(reflect_py)
    changed = False
    for old, new in REFLECT_UTF8_REPLACEMENTS:
        if old in src and new not in src:
            src = src.replace(old, new)
            changed = True
    if changed:
        write(reflect_py, src)
        print("patch_skillopt: patched reflection file IO for UTF-8")
    else:
        print("patch_skillopt: reflection UTF-8 file IO already patched")
    return changed


def main() -> int:
    root_arg = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SKILLOPT_ROOT", "")
    root = Path(root_arg).resolve()
    if not root.exists():
        print(f"patch_skillopt: SkillOpt root not found: {root}", file=sys.stderr)
        return 1
    patch_train(root)
    patch_claude_backend(root)
    patch_reflect_utf8(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
