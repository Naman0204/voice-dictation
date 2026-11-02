@echo off
REM ============================================================
REM  Voice Dictation - start the app (runs in the system tray)
REM  Run setup.bat once first. Close the app from its tray icon.
REM ============================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo Virtual environment not found. Run setup.bat first.
  pause
  exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" main.py
