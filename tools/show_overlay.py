"""
tools/show_overlay.py
Render the real RecordingOverlay widget on screen for ~14 s (no mic, no hotkey)
so its appearance/placement can be screenshotted. Shows a sample 00:42 timer.
Run: .venv\\Scripts\\python.exe tools\\show_overlay.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer                  # noqa: E402
from PySide6.QtWidgets import QApplication         # noqa: E402

from core.config import config                     # noqa: E402
from ui.recording_overlay import RecordingOverlay  # noqa: E402

from PySide6.QtGui import QGuiApplication           # noqa: E402

app = QApplication(sys.argv)
ov = RecordingOverlay()
ov.start(corner=config.get("overlay.corner", "top_right"),
         screen_index=config.get("overlay.screen_index", 0),
         margin=config.get("overlay.margin", 16))
ov.set_seconds(42)                                 # sample time for the screenshot

for i, s in enumerate(QGuiApplication.screens()):
    g, ag = s.geometry(), s.availableGeometry()
    print(f"screen[{i}] name={s.name()!r} dpr={s.devicePixelRatio()} "
          f"geometry={g.x()},{g.y()},{g.width()}x{g.height()} "
          f"available={ag.x()},{ag.y()},{ag.width()}x{ag.height()}")
print(f"overlay qt-pos={ov.pos().x()},{ov.pos().y()}")
sys.stdout.flush()


def _report():
    print("win_rect (physical L,T,R,B) =", ov.win_rect())
    sys.stdout.flush()


QTimer.singleShot(1500, _report)
QTimer.singleShot(45000, app.quit)
app.exec()
