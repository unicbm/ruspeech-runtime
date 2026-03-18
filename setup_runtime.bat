@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
)

echo Installing runtime dependencies...
call .venv\Scripts\python.exe -m pip install --upgrade pip
call .venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :fail

if exist "models\sherpa-onnx-ru-streaming\model.onnx" (
  echo Russian streaming model already present, skipping download.
) else (
  if not exist "scripts\download_russian_model.ps1" (
    echo Model is missing and scripts\download_russian_model.ps1 was not found.
    goto :fail
  )

  echo Downloading Russian streaming model...
  powershell -ExecutionPolicy Bypass -File scripts\download_russian_model.ps1
  if errorlevel 1 goto :fail
)

echo.
echo Setup complete.
echo Use run_dictation.bat or run_subtitles.bat to start.
pause
exit /b 0

:fail
echo.
echo Setup failed.
pause
exit /b 1
