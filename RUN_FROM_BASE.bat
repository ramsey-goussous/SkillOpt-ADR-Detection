@echo off
setlocal
cd /d "%~dp0"

set "ADR_RUN_MODE=base"
set "TARGET_MODEL=claude-sonnet-4-6"
set "OPTIMIZER_MODEL=claude-sonnet-4-6"
set "NUM_EPOCHS=1"
set "ADR_EXEC_TIMEOUT=240"
set "ADR_MODEL_RETRIES=2"
set "RUN_TEST_EVAL=0"
set "SKILL_SOURCE="

echo Running ADR SkillOpt from the committed base skill.
echo Folder: %CD%
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_adr_skillopt.ps1"
set "RC=%ERRORLEVEL%"
echo.
echo Finished with exit code %RC%.
echo Results are in: %~dp0results
pause
exit /b %RC%
