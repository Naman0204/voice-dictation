"""
tools/hotkey_live_test.py
Probe whether the RUNNING app's global hotkey actually fires: inject a synthetic
triple-R (and triple-D) and watch for the app reacting (a new note bundle for R).
This catches whether the multi-key listener works in the live app.
Run: .venv\\Scripts\\python.exe tools\\hotkey_live_test.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config import config            # noqa: E402
from pynput.keyboard import Controller     # noqa: E402

notes = config.notes_dir
kb = Controller()


def bundles():
    if not notes.exists():
        return []
    return sorted([p for p in notes.iterdir() if p.is_dir() and p.name.startswith("note_")],
                  key=lambda p: p.stat().st_mtime)


def triple(ch):
    for _ in range(3):
        kb.press(ch); kb.release(ch)
        time.sleep(0.09)


print("bundles before:", len(bundles()))
time.sleep(0.4)
print("injecting triple-R (should START a recording)...")
triple("r")
time.sleep(2.5)
after_start = len(bundles())
print("bundles after triple-R:", after_start)

print("injecting triple-R again (should STOP it)...")
triple("r")
time.sleep(4)
b = bundles()
print("bundles now:", len(b))
if b:
    newest = b[-1]
    print("newest bundle:", newest.name, "->", [f.name for f in newest.iterdir()])

print("\nHOTKEY VERDICT:", "WORKS (recording triggered)" if after_start > 0 and b else
      "DID NOT FIRE — the app's global hotkey is not catching keys")
