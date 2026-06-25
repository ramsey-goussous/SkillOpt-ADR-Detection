@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if not exist ".git" (
  echo This folder is not a Git repository:
  echo %CD%
  pause
  exit /b 1
)

if not exist "run_adr_skillopt.ps1" (
  echo Refusing to push: run_adr_skillopt.ps1 is missing.
  echo You are probably in the wrong folder.
  pause
  exit /b 1
)

if not exist "skills\base_skill.md" (
  echo Refusing to push: skills\base_skill.md is missing.
  echo You are probably in the wrong folder.
  pause
  exit /b 1
)

echo About to push this repository only:
echo %CD%
echo.
git status --short
echo.

git remote get-url origin >nul 2>nul
if errorlevel 1 (
  echo No origin remote is configured.
  set /p "REMOTE_URL=Paste the empty GitHub/GitLab repository URL, then press Enter: "
  if "!REMOTE_URL!"=="" (
    echo No remote URL entered. Nothing was pushed.
    pause
    exit /b 1
  )
  git remote add origin "!REMOTE_URL!"
) else (
  echo Current origin:
  git remote get-url origin
)

git branch -M main
git push -u origin main
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo Push complete.
) else (
  echo Push failed. Check the message above.
)
pause
exit /b %RC%
