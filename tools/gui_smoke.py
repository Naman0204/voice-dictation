"""
tools/gui_smoke.py
End-to-end GUI integration test. Builds the real QApplication + controller +
tray + overlay and drives a record->stop cycle programmatically (no global
keypress needed), then verifies: the overlay was visible while recording and
hidden after, a FLAC bundle was produced, the final state is IDLE, and the
process opens NO TCP listeners (the no-network-surface guarantee). Exits 0 on
PASS. Run: .venv\\Scripts\\python.exe tools\\gui_smoke.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from PySide6.QtCore import QTimer                       # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from core import security                               # noqa: E402
from core.app_controller import AppController, State    # noqa: E402
from core.config import config                          # noqa: E402
from ui.recording_overlay import RecordingOverlay       # noqa: E402
from ui.tray import TrayIcon                            # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
print("tray available:", QSystemTrayIcon.isSystemTrayAvailable())

tray = TrayIcon()
overlay = RecordingOverlay()
ctrl = AppController(tray, overlay)
ctrl.start()

st = {"overlay_during": None}


def start():
    print("[t=0.5s] toggle -> start recording")
    ctrl.request_toggle()


def midcheck():
    st["overlay_during"] = overlay.isVisible()
    print(f"[t=2.5s] state={ctrl._state.value} overlay_visible={overlay.isVisible()}")


def stop():
    print("[t=3.0s] toggle -> stop recording")
    ctrl.request_toggle()


def finish():
    flacs = sorted(config.notes_dir.rglob("audio.flac"), key=lambda p: p.stat().st_mtime)
    flac = flacs[-1] if flacs else None
    ports = security.listening_sockets()
    print(f"[t=7.5s] state={ctrl._state.value} overlay_visible={overlay.isVisible()} "
          "(should be hidden — 3s 'Open' window has elapsed)")
    print("listening TCP ports:", ports or "none")
    if flac:
        print("newest FLAC:", flac, f"({flac.stat().st_size} bytes)")
    ok = (st["overlay_during"] is True
          and not overlay.isVisible()
          and flac is not None
          and ctrl._state is State.IDLE
          and not ports)
    print("\nRESULT:", "PASS" if ok else "FAIL")
    app.exit(0 if ok else 1)


QTimer.singleShot(500, start)
QTimer.singleShot(2500, midcheck)
QTimer.singleShot(3000, stop)
QTimer.singleShot(7500, finish)   # after the 3s 'Open' folder window + transcription
sys.exit(app.exec())
