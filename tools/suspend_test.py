"""
tools/suspend_test.py
Validate sleep handling WITHOUT actually sleeping the machine:
  1. PowerNotifier registers with the OS power service.
  2. A simulated suspend dispatch invokes the handler.
  3. With a live recording active, the suspend handler finalizes the WAV.
Run: .venv\\Scripts\\python.exe tools\\suspend_test.py
"""
import sys
import tempfile
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PySide6.QtWidgets import QApplication                  # noqa: E402

from core.audio_recorder import AudioRecorder               # noqa: E402
from core.power_notify import PowerNotifier, PBT_APMSUSPEND  # noqa: E402

app = QApplication(sys.argv)
results = []


def ck(name, cond):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


# 1. OS registration
fired = {"n": 0}
pn = PowerNotifier(on_suspend=lambda: fired.__setitem__("n", fired["n"] + 1))
pn.register()
ck("PowerNotifier registered with the OS", pn.is_registered())

# 2. simulated suspend dispatch calls the handler
pn._dispatch(None, PBT_APMSUSPEND, None)
ck("suspend dispatch invokes the handler", fired["n"] == 1)
pn.unregister()
ck("unregister clears registration", not pn.is_registered())

# 3. live recording is finalized on suspend
rec = AudioRecorder(samplerate=16000, channels=1, blocksize=1600)
tmp = Path(tempfile.mkdtemp()) / "susp.wav"
rec.start_recording(str(tmp))
time.sleep(0.9)
ck("recording is active", rec.is_recording)


def on_suspend():
    if rec.is_recording:
        rec.stop_recording()


PowerNotifier(on_suspend=on_suspend)._dispatch(None, PBT_APMSUSPEND, None)
app.processEvents()
ck("recording stopped on suspend", not rec.is_recording)
frames = 0
if tmp.exists():
    with wave.open(str(tmp)) as w:
        frames = w.getnframes()
ck("WAV finalized with captured frames", frames > 0)
print(f"   (captured {frames} frames = {frames / 16000:.2f}s before 'sleep')")
try:
    tmp.unlink()
except Exception:
    pass

print(f"\n{sum(results)}/{len(results)} checks passed.")
sys.exit(0 if all(results) else 1)
