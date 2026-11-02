"""
tools/dictation_test.py
Headless tests for Feature B (no real keystrokes, no mic):
  - hotkey routing: triple-D -> "dictate", triple-R -> "record", no cross-talk
  - text injector: UTF-16 unit splitting (incl. emoji surrogate pairs) + counts
  - dictation engine: silence-segmentation flushes a phrase and "injects" it
    (model + injection are faked, so nothing is typed and it's instant)
Run: .venv\\Scripts\\python.exe tools\\dictation_test.py
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np                                  # noqa: E402
from PySide6.QtCore import QCoreApplication          # noqa: E402
from pynput import keyboard                          # noqa: E402

import core.text_injector as ti                      # noqa: E402
from core.hotkey_listener import HotkeyListener       # noqa: E402

app = QCoreApplication(sys.argv)
results = []


def ck(n, c):
    results.append(bool(c))
    print(f"[{'PASS' if c else 'FAIL'}] {n}")


# ── B: hotkey routing ────────────────────────────────────────────────────────
fired = []
hl = HotkeyListener([
    {"name": "record", "key": "r", "taps": 3, "window_ms": 450, "cooldown_ms": 1500},
    {"name": "dictate", "key": "d", "taps": 3, "window_ms": 450, "cooldown_ms": 1500},
])
hl.triggered.connect(lambda n: fired.append(n))
D = keyboard.KeyCode.from_char("d")
R = keyboard.KeyCode.from_char("r")
X = keyboard.KeyCode.from_char("x")


def triple(key):
    for _ in range(3):
        hl._on_press(key); hl._on_release(key)


triple(D)
ck("triple-D fires 'dictate'", fired == ["dictate"])
time.sleep(1.6)                                      # clear cooldown
triple(R)
ck("triple-R fires 'record'", fired == ["dictate", "record"])
time.sleep(1.6)
fired.clear()
for k in (D, R, D, R, D):                            # interleaved -> nothing
    hl._on_press(k); hl._on_release(k)
ck("interleaved D/R fires nothing", fired == [])

# ── C: text injector unicode ─────────────────────────────────────────────────
ck("ascii utf16 unit", ti._utf16_units("a") == [97])
ck("emoji is surrogate pair (2 units)", len(ti._utf16_units("😀")) == 2)
ck("unicode_inputs = 2 events/codeunit", len(ti.unicode_inputs("hi")) == 4)
ck("emoji unicode_inputs = 4 events", len(ti.unicode_inputs("😀")) == 4)

# ── D: dictation segmentation + injection (faked model/injection) ────────────
from core.dictation import Dictation                 # noqa: E402

captured = []
ti.insert = lambda text, method="type": captured.append(text)
ti.foreground_window = lambda: 4242
ti.backspace = lambda n: None


class _FakeSeg:
    def __init__(self, t): self.text = t


class _FakeModel:
    def transcribe(self, audio, **kw):
        return ([_FakeSeg(" hello world")], None)


d = Dictation()
d._model = _FakeModel()
d._target_hwnd = 4242
d._active = True
d._stop.clear()
w = threading.Thread(target=d._loop, daemon=True)
w.start()
voiced = np.full((1600, 1), 0.05, dtype=np.float32)   # RMS 0.05 > threshold
silent = np.zeros((1600, 1), dtype=np.float32)
for _ in range(10):                                   # ~1s of speech
    d._q.put(voiced.copy())
for _ in range(9):                                    # ~0.9s silence -> flush at 0.6s
    d._q.put(silent.copy())
time.sleep(1.2)
d._stop.set()
w.join(timeout=3)
ck("dictation flushes + injects a phrase on silence", any("hello world" in c for c in captured))
print("   captured:", captured)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
