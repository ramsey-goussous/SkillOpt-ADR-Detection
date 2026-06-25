@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0real_data\real_notes.json" (
  echo No real_data\real_notes.json found.
  echo Put de-identified real notes in that file, then run this again.
  echo See real_data\README.md for the expected JSON shape.
  echo.
  pause
  exit /b 1
)

set "TARGET_MODEL=claude-sonnet-4-6"
set "ADR_EXEC_TIMEOUT=240"
set "ADR_MODEL_RETRIES=2"
set "WORKERS=1"

echo Running ADR extraction on real_data\real_notes.json.
echo Uses results\best_skill.md if it exists, otherwise skills\base_skill.md.
echo Folder: %CD%
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_real_data_eval.ps1"
set "RC=%ERRORLEVEL%"
echo.
echo Finished with exit code %RC%.
echo Results are in: %~dp0results\real_data
pause
exit /b %RC%
