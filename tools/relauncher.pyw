"""
tools/relauncher.pyw
Tiny detached helper for the tray "Restart" action: wait for the current instance
to exit (releasing the single-instance lock), then launch a fresh Voice Notes.
Runs via pythonw (no console window).
"""
import subprocess
import time
from pathlib import Path

time.sleep(2)                                  # let the old instance fully exit
root = Path(__file__).resolve().parent.parent
pyw = root / ".venv" / "Scripts" / "pythonw.exe"
try:
    subprocess.Popen([str(pyw), str(root / "main.py")], cwd=str(root),
                     creationflags=0x00000008)  # DETACHED_PROCESS
except Exception:
    pass
