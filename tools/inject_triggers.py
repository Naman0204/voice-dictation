"""tools/inject_triggers.py — inject synthetic triple-R and triple-D to exercise
the running app's hotkeys (then read app.log to see what fired)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pynput.keyboard import Controller   # noqa: E402

kb = Controller()


def triple(c):
    for _ in range(3):
        kb.press(c); kb.release(c)
        time.sleep(0.09)


time.sleep(0.5)
print("inject triple-R (start recording)"); triple("r"); time.sleep(2.5)
print("inject triple-R (stop)"); triple("r"); time.sleep(3.5)
print("inject triple-D (start dictation)"); triple("d"); time.sleep(3.0)
print("inject triple-D (stop)"); triple("d"); time.sleep(2.5)
print("done")
