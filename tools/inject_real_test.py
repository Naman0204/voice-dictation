"""
tools/inject_real_test.py
Diagnose real keystroke injection: force a text box to the foreground, confirm
it IS the foreground window, check SendInput's return count, then type + read back.
Run: .venv\\Scripts\\python.exe tools\\inject_real_test.py
"""
import ctypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PySide6.QtCore import Qt, QTimer                  # noqa: E402
from PySide6.QtWidgets import QApplication, QTextEdit    # noqa: E402

import core.text_injector as ti                        # noqa: E402

u = ctypes.windll.user32
u.SetForegroundWindow.argtypes = [ctypes.c_void_p]
u.SetForegroundWindow.restype = ctypes.c_int
u.GetForegroundWindow.restype = ctypes.c_void_p
u.GetFocus.restype = ctypes.c_void_p

app = QApplication(sys.argv)
te = QTextEdit()
te.setWindowFlag(Qt.WindowStaysOnTopHint, True)
te.resize(420, 120)
te.show(); te.raise_(); te.activateWindow(); te.setFocus()


def run():
    hwnd = int(te.winId())
    u.SetForegroundWindow(hwnd)
    fg = u.GetForegroundWindow() or 0
    print(f"our hwnd      = {hwnd}")
    print(f"foreground    = {fg}  (match={fg == hwnd})")
    one = ti.unicode_inputs("X")
    n = ti._send(one)
    print(f"SendInput     = sent {n}/{len(one)} events for one char")
    ti.type_text("HELLO café 123")
    QTimer.singleShot(600, check)


def check():
    print("box contents  =", repr(te.toPlainText()))
    ok = "HELLO" in te.toPlainText()
    print("\nRESULT:", "PASS — injection works" if ok else
          "no text in box (see foreground/SendInput lines above)")
    app.exit(0 if ok else 1)


QTimer.singleShot(1000, run)
sys.exit(app.exec())
