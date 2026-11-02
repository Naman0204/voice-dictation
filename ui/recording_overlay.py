"""
ui/recording_overlay.py
A tiny, blended HUD shown only around recording. Two modes:
  • "recording": a click-through pulsing red dot + MM:SS timer (never intercepts
    clicks, no taskbar/Alt-Tab, no focus steal).
  • "done": when a recording ends, the same pill becomes a CLICKABLE folder
    button ("Open") for a few seconds, then disappears. Clicking it emits
    `folder_clicked` (the app opens the notes folder) and dismisses the widget.

Click-through is toggled per mode — on while recording, off in "done" so the
folder is clickable. Placement uses a Win32 SetWindowPos in physical pixels
(Qt's logical move() is unreliable for a translucent layered window on high-DPI).
All Win32 calls declare argtypes so the 64-bit window handle isn't truncated.
"""
import ctypes
import math
import sys

from PySide6.QtCore import Qt, QTimer, QPoint, QRect, Signal
from PySide6.QtGui import QPainter, QColor, QFont, QGuiApplication, QRegion
from PySide6.QtWidgets import QWidget, QApplication, QStyle

W, H = 96, 28
DOT_R = 5
RED = (0xE5, 0x39, 0x3B)
DONE_MS = 3000                       # how long the "Open" folder button lingers

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
WS_EX_LAYERED = 0x80000
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOACTIVATE = 0x0001, 0x0010

_user32 = None
if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    try:
        _get_exstyle = _user32.GetWindowLongPtrW
        _set_exstyle = _user32.SetWindowLongPtrW
    except AttributeError:                       # 32-bit Python fallback
        _get_exstyle = _user32.GetWindowLongW
        _set_exstyle = _user32.SetWindowLongW
    _get_exstyle.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _get_exstyle.restype = ctypes.c_ssize_t
    _set_exstyle.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
    _set_exstyle.restype = ctypes.c_ssize_t
    _user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_ssize_t,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_uint]
    _user32.SetWindowPos.restype = ctypes.c_int


class RecordingOverlay(QWidget):
    folder_clicked = Signal()        # emitted when the "Open" folder button is clicked

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(W, H)
        self.setWindowOpacity(0.88)
        self._apply_pill_mask()

        self._mode = "recording"      # "recording" | "done"
        self._hover = False
        self._seconds = 0
        self._phase = 0.0
        self._corner = "top_right"
        self._screen_index = 0
        self._margin = 16

        self._tick = QTimer(self); self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)
        self._pulse = QTimer(self); self._pulse.setInterval(50)
        self._pulse.timeout.connect(self._on_pulse)
        self._done_timer = QTimer(self); self._done_timer.setSingleShot(True)
        self._done_timer.timeout.connect(self._finish_done)

        self._folder_pix = QApplication.style().standardIcon(
            QStyle.StandardPixmap.SP_DirIcon).pixmap(18, 18)

    # ── public API ────────────────────────────────────────────────────────
    def start(self, corner="top_right", screen_index=0, margin=16):
        self._done_timer.stop()
        self._mode = "recording"
        self._hover = False
        self._seconds = 0
        self._phase = 0.0
        self._corner, self._screen_index, self._margin = corner, screen_index, margin
        self.unsetCursor()
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.show()                              # showEvent applies click-through + placement
        self._tick.start()
        self._pulse.start()

    def show_done(self):
        """Switch the live pill to a clickable 'Open' folder button for DONE_MS,
        then auto-hide."""
        self._tick.stop()
        self._pulse.stop()
        self._mode = "done"
        self._hover = False
        if not self.isVisible():
            self.show()
        self._set_clickthrough(False)            # make it clickable
        self.setWindowOpacity(0.92)              # re-assert blend after ex-style change
        self.setCursor(Qt.PointingHandCursor)
        self.update()
        self._done_timer.start(DONE_MS)

    def start_dictation(self, corner="top_right", screen_index=0, margin=16):
        """Show the dictation indicator (teal dot + 'typing…'), click-through."""
        self._done_timer.stop()
        self._mode = "dictating"
        self._hover = False
        self._phase = 0.0
        self._corner, self._screen_index, self._margin = corner, screen_index, margin
        self.unsetCursor()
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.show()
        self._pulse.start()                      # dot pulse only (no MM:SS tick)

    def stop(self):
        self._tick.stop()
        self._pulse.stop()
        self._done_timer.stop()
        self.hide()

    def _finish_done(self):
        self._done_timer.stop()
        self._mode = "recording"
        self.unsetCursor()
        self.hide()

    # ── click-through toggle ──────────────────────────────────────────────
    def _set_clickthrough(self, enabled: bool):
        self.setAttribute(Qt.WA_TransparentForMouseEvents, enabled)
        if sys.platform == "win32":
            try:
                hwnd = int(self.winId())
                ex = _get_exstyle(hwnd, GWL_EXSTYLE) or 0
                ex = (ex | WS_EX_TRANSPARENT) if enabled else (ex & ~WS_EX_TRANSPARENT)
                _set_exstyle(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)
            except Exception:
                pass

    # ── placement ─────────────────────────────────────────────────────────
    def _target_screen(self):
        screens = QGuiApplication.screens()
        if not screens:
            return QGuiApplication.primaryScreen()
        return screens[min(int(self._screen_index), len(screens) - 1)]

    def _corner_xy(self, left, top, right, bottom, w, h, m):
        x = right - w - m if "right" in self._corner else left + m
        y = top + m if "top" in self._corner else bottom - h - m
        return int(x), int(y)

    def _place_qt(self):
        scr = self._target_screen()
        if scr is None:
            return
        g = scr.availableGeometry()
        x, y = self._corner_xy(g.left(), g.top(), g.right(), g.bottom(), W, H, self._margin)
        self.move(QPoint(x, y))

    def _place_win32(self):
        scr = self._target_screen()
        if scr is None:
            return
        dpr = scr.devicePixelRatio()
        g = scr.availableGeometry()
        x, y = self._corner_xy(
            g.x() * dpr, g.y() * dpr,
            (g.x() + g.width()) * dpr, (g.y() + g.height()) * dpr,
            W * dpr, H * dpr, self._margin * dpr)
        _user32.SetWindowPos(int(self.winId()), HWND_TOPMOST, x, y, 0, 0,
                             SWP_NOSIZE | SWP_NOACTIVATE)

    def _reposition(self):
        try:
            self._place_win32() if sys.platform == "win32" else self._place_qt()
        except Exception:
            pass

    def showEvent(self, e):
        super().showEvent(e)
        self._set_clickthrough(self._mode in ("recording", "dictating"))
        self._reposition()
        QTimer.singleShot(0, self._reposition)

    def _apply_pill_mask(self):
        region = QRegion(H // 2, 0, W - H, H)
        region = region.united(QRegion(0, 0, H, H, QRegion.Ellipse))
        region = region.united(QRegion(W - H, 0, H, H, QRegion.Ellipse))
        self.setMask(region)

    # ── mouse (done mode only) ────────────────────────────────────────────
    def mousePressEvent(self, e):
        if self._mode == "done":
            self.folder_clicked.emit()
            self._finish_done()
        else:
            super().mousePressEvent(e)

    def enterEvent(self, e):
        if self._mode == "done":
            self._hover = True
            self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._hover:
            self._hover = False
            self.update()
        super().leaveEvent(e)

    # ── timers ────────────────────────────────────────────────────────────
    def _on_tick(self):
        self._seconds += 1
        self.update()

    def _on_pulse(self):
        self._phase += 0.16
        self.update(QRect(0, 0, 2 * DOT_R + 18, H))

    # ── paint ─────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        bg = QColor(44, 44, 50) if (self._mode == "done" and self._hover) else QColor(24, 24, 28)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(self.rect(), H / 2, H / 2)

        if self._mode == "recording":
            alpha = int(150 + 105 * (0.5 + 0.5 * math.sin(self._phase)))
            p.setBrush(QColor(RED[0], RED[1], RED[2], alpha))
            p.drawEllipse(QPoint(14, H // 2), DOT_R, DOT_R)
            mm, ss = divmod(self._seconds, 60)
            p.setPen(QColor(255, 255, 255, 222))
            p.setFont(QFont("Consolas", 11))
            p.drawText(QRect(26, 0, W - 30, H),
                       Qt.AlignVCenter | Qt.AlignLeft, f"{mm:02d}:{ss:02d}")
        elif self._mode == "dictating":          # teal dot + "typing…"
            alpha = int(150 + 105 * (0.5 + 0.5 * math.sin(self._phase)))
            p.setBrush(QColor(38, 200, 150, alpha))
            p.drawEllipse(QPoint(14, H // 2), DOT_R, DOT_R)
            p.setPen(QColor(255, 255, 255, 222))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRect(26, 0, W - 30, H), Qt.AlignVCenter | Qt.AlignLeft, "typing…")
        else:                                    # done — clickable folder button
            p.drawPixmap(18, (H - 18) // 2, self._folder_pix)
            p.setPen(QColor(255, 255, 255, 235))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRect(40, 0, W - 44, H), Qt.AlignVCenter | Qt.AlignLeft, "Open")
        p.end()

    def set_seconds(self, s: int):
        self._seconds = int(s)
        self.update()

    # ── diagnostics ───────────────────────────────────────────────────────
    def win_rect(self):
        if sys.platform != "win32":
            return None
        from ctypes import wintypes
        r = wintypes.RECT()
        fn = _user32.GetWindowRect
        fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
        fn(int(self.winId()), ctypes.byref(r))
        return (r.left, r.top, r.right, r.bottom)
