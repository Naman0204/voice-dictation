"""
tools/tasks_app_test.py
Test the EXACT app trigger path for task extraction: build the controller and
emit the same signal the tray menu emits, then wait for tasks.json to appear.
Isolates whether the wiring (signal -> slot -> thread -> extract -> write) works.
Run: .venv\\Scripts\\python.exe tools\\tasks_app_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PySide6.QtCore import QTimer                  # noqa: E402
from PySide6.QtWidgets import QApplication          # noqa: E402

from core.app_controller import AppController       # noqa: E402
from core.config import config                      # noqa: E402
from ui.recording_overlay import RecordingOverlay   # noqa: E402
from ui.tray import TrayIcon                         # noqa: E402

app = QApplication(sys.argv)
tray, overlay = TrayIcon(), RecordingOverlay()
ctrl = AppController(tray, overlay)          # NOT ctrl.start() — no global hook/power

notes = config.notes_dir
bundles = sorted([p for p in notes.iterdir()
                  if p.is_dir() and p.name.startswith("note_") and (p / "transcript.txt").exists()],
                 key=lambda p: p.stat().st_mtime)
if not bundles:
    print("no transcripts; record something first")
    sys.exit(0)
latest = bundles[-1]
tj = latest / "tasks.json"
if tj.exists():
    tj.unlink()
print(f"latest note: {latest.name}; tasks.json present before: {tj.exists()}")

balloons = []
ctrl._tasks_done.connect(lambda m: (balloons.append(m), print("[balloon]", m)))

print("emitting tray.extract_tasks_latest (the menu action)...")
tray.extract_tasks_latest.emit()

ticks = [0]


def poll():
    ticks[0] += 1
    if tj.exists() or ticks[0] > 90:
        print(f"\ntasks.json present after: {tj.exists()}  (waited {ticks[0]}s)")
        print("balloons seen:", balloons)
        print("RESULT:", "PASS — app path produced tasks.json" if tj.exists()
              else "FAIL — app path did not write tasks.json")
        app.exit(0 if tj.exists() else 1)


timer = QTimer(); timer.timeout.connect(poll); timer.start(1000)
sys.exit(app.exec())
