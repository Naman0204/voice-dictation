"""
ui/tray.py
System-tray presence: a small dot icon (muted grey when idle, red when
recording) and a menu (Start/Stop, Open notes folder, Purge audio, Quit). The
icon is drawn programmatically so no image assets are bundled.
"""
from PySide6.QtCore import QObject, Signal, Qt, QPoint
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import QSystemTrayIcon, QMenu


def _dot_icon(rgb) -> QIcon:
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(*rgb))
    p.drawEllipse(QPoint(16, 16), 11, 11)
    p.end()
    return QIcon(pm)


class TrayIcon(QObject):
    toggle_requested      = Signal()
    open_notes_requested  = Signal()
    purge_requested       = Signal()
    restart_requested     = Signal()
    quit_requested        = Signal()
    extract_tasks_latest  = Signal()
    extract_tasks_all     = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._idle_icon = _dot_icon((120, 120, 128))
        self._rec_icon  = _dot_icon((0xE5, 0x39, 0x3B))

        self._tray = QSystemTrayIcon(self._idle_icon, self)
        self._tray.setToolTip("Voice Notes — idle")

        self._menu = QMenu()
        self._act_toggle = self._menu.addAction("Start recording")
        self._act_toggle.triggered.connect(lambda *_: self.toggle_requested.emit())
        self._menu.addSeparator()
        self._menu.addAction("Open notes folder").triggered.connect(
            lambda *_: self.open_notes_requested.emit())
        self._menu.addSeparator()
        self._menu.addAction("Extract tasks (latest note)").triggered.connect(
            lambda *_: self.extract_tasks_latest.emit())
        self._menu.addAction("Extract tasks (all notes)").triggered.connect(
            lambda *_: self.extract_tasks_all.emit())
        self._menu.addSeparator()
        self._menu.addAction("Purge audio").triggered.connect(
            lambda *_: self.purge_requested.emit())
        self._menu.addSeparator()
        self._menu.addAction("Restart").triggered.connect(
            lambda *_: self.restart_requested.emit())
        self._menu.addAction("Quit").triggered.connect(
            lambda *_: self.quit_requested.emit())
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)

    def show(self):
        self._tray.show()

    def hide(self):
        self._tray.hide()

    def set_recording(self, recording: bool, seconds: int = 0):
        if recording:
            self._tray.setIcon(self._rec_icon)
            self._act_toggle.setText("Stop recording")
            self._tray.setToolTip(
                f"Voice Notes — recording {seconds // 60:02d}:{seconds % 60:02d}")
        else:
            self._tray.setIcon(self._idle_icon)
            self._act_toggle.setText("Start recording")
            self._tray.setToolTip("Voice Notes — idle")

    def set_status(self, text: str):
        self._tray.setToolTip(f"Voice Notes — {text}")

    def message(self, title: str, body: str):
        try:
            self._tray.showMessage(
                title, body, QSystemTrayIcon.MessageIcon.Information, 3000)
        except Exception:
            pass

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:   # left click
            self.toggle_requested.emit()
