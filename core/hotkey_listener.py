"""
core/hotkey_listener.py
Global triple-tap hotkey. Runs a non-suppressing pynput keyboard listener on its
own thread (so normal typing is never swallowed) and emits `toggled` when the
trigger key is tapped N times within a rolling window.

Auto-repeat immunity: a tap counts only on a press that follows a release, so
holding the key down generates exactly one tap, never a burst.
"""
import time

from PySide6.QtCore import QObject, Signal
from pynput import keyboard


class TapDetector:
    """Pure, headless-testable triple-tap state machine. Feed it press/release."""

    def __init__(self, taps=3, window_s=0.45, cooldown_s=1.5, clock=time.monotonic):
        self.taps = taps
        self.window = window_s
        self.cooldown = cooldown_s
        self._clock = clock
        self._down = False            # is the trigger key physically held?
        self._times = []              # timestamps of genuine taps
        self._last_fire = -1e9

    def on_trigger_press(self) -> bool:
        """True iff this press completes a triple-tap that should fire."""
        if self._down:
            return False              # auto-repeat: press with no release between
        self._down = True
        now = self._clock()
        if now - self._last_fire < self.cooldown:
            return False              # still cooling down from the last fire
        self._times = [t for t in self._times if now - t <= self.window]
        self._times.append(now)
        if len(self._times) >= self.taps:
            self._times.clear()
            self._last_fire = now
            return True
        return False

    def on_trigger_release(self):
        self._down = False

    def on_other_key(self):
        """Any non-trigger key breaks the in-progress sequence."""
        self._times.clear()


_SPECIAL = {
    "ctrl_r": keyboard.Key.ctrl_r,
    "ctrl_l": keyboard.Key.ctrl_l,
    "scroll_lock": getattr(keyboard.Key, "scroll_lock", None),
    "pause": getattr(keyboard.Key, "pause", None),
}


class HotkeyListener(QObject):
    """One global pynput listener driving several independent triple-tap triggers.
    Emits `triggered(name)` with the logical binding name (e.g. "record" |
    "dictate")."""
    triggered = Signal(str)

    def __init__(self, bindings, parent=None):
        """bindings: list of {name, key, taps, window_ms, cooldown_ms}."""
        super().__init__(parent)
        self._binds = []
        for b in bindings:
            det = TapDetector(taps=b.get("taps", 3),
                              window_s=b.get("window_ms", 450) / 1000.0,
                              cooldown_s=b.get("cooldown_ms", 1500) / 1000.0)
            self._binds.append({"name": b["name"], "key": b["key"],
                                "trigger": self._resolve_key(b["key"]), "det": det})
        self._listener = None

    @staticmethod
    def _resolve_key(key):
        if key in _SPECIAL and _SPECIAL[key] is not None:
            return _SPECIAL[key]
        return keyboard.KeyCode.from_char((key or "r")[0])

    @staticmethod
    def _match(k, key_name, trigger) -> bool:
        if isinstance(trigger, keyboard.Key):
            return k == trigger
        return (getattr(k, "char", None) or "").lower() == key_name.lower()

    def start(self):
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release, suppress=False)
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    # ── pynput callbacks (listener thread) ────────────────────────────────
    def _on_press(self, k):
        for b in self._binds:
            if self._match(k, b["key"], b["trigger"]):
                if b["det"].on_trigger_press():
                    self.triggered.emit(b["name"])    # queued to GUI thread
            else:
                b["det"].on_other_key()               # another key breaks this sequence

    def _on_release(self, k):
        for b in self._binds:
            if self._match(k, b["key"], b["trigger"]):
                b["det"].on_trigger_release()
