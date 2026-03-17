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
  --name RuspeechRuntime ^
  --onedir ^
  --console ^
  --collect-submodules sherpa_onnx ^
  --hidden-import soundcard ^
  --hidden-import keyboard ^
  --hidden-import tkinter ^
  --add-data "models\sherpa-onnx-ru-streaming;models\sherpa-onnx-ru-streaming" ^
  main.py

if errorlevel 1 (
  echo.
  echo EXE build failed.
  pause
  exit /b 1
)

echo.
echo Build complete. Output folder: dist\RuspeechRuntime
pause
