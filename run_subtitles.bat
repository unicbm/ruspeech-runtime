@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Runtime is not installed. Run setup_runtime.bat first.
  pause
  exit /b 1
)

call .venv\Scripts\python.exe main.py --mode subtitles --source loopback
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" pause
exit /b %ERR%
