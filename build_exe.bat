@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Runtime is not installed. Run setup_runtime.bat first.
  pause
  exit /b 1
)

call .venv\Scripts\python.exe -m PyInstaller ^
  --noconfirm ^
  --clean ^
  UniSpeechRuntime.spec

if errorlevel 1 (
  echo.
  echo EXE build failed.
  pause
  exit /b 1
)

echo.
echo Build complete. Output folder: dist\UniSpeechRuntime
echo CLI: dist\UniSpeechRuntime\UniSpeechRuntime.exe
echo GUI: dist\UniSpeechRuntime\UniSpeechRuntimeUI.exe
pause
