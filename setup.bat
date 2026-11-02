@echo off
REM ============================================================
REM  Voice Dictation - one-time setup
REM  Creates a local Python virtual environment (.venv) and
REM  installs the dependencies. Run this once after cloning.
REM ============================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  py -3.12 -m venv .venv 2>nul
  if not exist ".venv\Scripts\python.exe" py -m venv .venv 2>nul
  if not exist ".venv\Scripts\python.exe" python -m venv .venv
)

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo ERROR: could not create a virtual environment.
  echo Install Python 3.12 from https://www.python.org/downloads/
  echo and make sure "py" or "python" is on your PATH, then run setup.bat again.
  pause
  exit /b 1
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo ERROR: dependency install failed. See the messages above.
  pause
  exit /b 1
)

echo.
echo Setup complete. Double-click run.bat to start Voice Dictation.
pause
