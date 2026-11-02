"""
tools/overlay_done_test.py
Headless logic test for the overlay's two modes: recording (click-through dot+
timer) vs done (clickable 'Open' folder button that auto-hides). Verifies mode
switches, click-through toggling, the folder_clicked signal, and auto-hide.
Run: .venv\\Scripts\\python.exe tools\\overlay_done_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PySide6.QtCore import Qt, QPointF, QEvent          # noqa: E402
from PySide6.QtGui import QMouseEvent                     # noqa: E402
from PySide6.QtWidgets import QApplication                # noqa: E402

from ui.recording_overlay import RecordingOverlay         # noqa: E402

app = QApplication(sys.argv)
ov = RecordingOverlay()
clicks = []
ov.folder_clicked.connect(lambda: clicks.append(1))

results = []


def ck(name, cond):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


ov.start(); app.processEvents()
ck("start -> recording mode", ov._mode == "recording")
ck("start -> visible", ov.isVisible())
ck("recording mode is click-through", ov.testAttribute(Qt.WA_TransparentForMouseEvents))

ov.show_done(); app.processEvents()
ck("show_done -> done mode", ov._mode == "done")
ck("done -> still visible", ov.isVisible())
ck("done -> clickable (NOT click-through)", not ov.testAttribute(Qt.WA_TransparentForMouseEvents))
ck("done -> auto-hide timer armed", ov._done_timer.isActive())

ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(48, 14), QPointF(48, 14),
                 Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                 Qt.KeyboardModifier.NoModifier)
ov.mousePressEvent(ev); app.processEvents()
ck("click emits folder_clicked once", len(clicks) == 1)
ck("click hides the widget", not ov.isVisible())
ck("click resets to recording mode", ov._mode == "recording")
ck("click cancels auto-hide timer", not ov._done_timer.isActive())

ov.start(); app.processEvents(); ov.show_done(); app.processEvents()
ck("auto-hide timer re-armed", ov._done_timer.isActive())
ov._finish_done()                                       # simulate the 3 s timeout
ck("auto-hide hides widget", not ov.isVisible())
ck("auto-hide fired no extra click", len(clicks) == 1)

passed = sum(results)
print(f"\n{passed}/{len(results)} checks passed.")
sys.exit(0 if passed == len(results) else 1)
