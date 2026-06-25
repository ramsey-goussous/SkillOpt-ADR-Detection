@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0results\best_skill.md" (
  echo No results\best_skill.md found yet.
  echo Run RUN_FROM_BASE.bat first, or copy a chosen best_skill.md into the results folder.
  echo.
  pause
  exit /b 1
)

set "ADR_RUN_MODE=best"
set "TARGET_MODEL=claude-sonnet-4-6"
set "OPTIMIZER_MODEL=claude-sonnet-4-6"
set "NUM_EPOCHS=1"
set "ADR_EXEC_TIMEOUT=240"
set "ADR_MODEL_RETRIES=2"
set "RUN_TEST_EVAL=0"
set "SKILL_SOURCE=%~dp0results\best_skill.md"

echo Running ADR SkillOpt from results\best_skill.md.
echo Folder: %CD%
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_adr_skillopt.ps1"
set "RC=%ERRORLEVEL%"
echo.
echo Finished with exit code %RC%.
echo Results are in: %~dp0results
pause
exit /b %RC%
