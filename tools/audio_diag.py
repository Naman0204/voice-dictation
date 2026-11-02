"""
tools/audio_diag.py
Diagnose microphone input: list host APIs + input devices, then capture 2 s from
the default device and from each input device and report peak/RMS so we can tell
which device actually delivers a signal (a real mic shows a noise floor > 0;
exactly 0.0 means silence/gated/blocked).
Run: .venv\\Scripts\\python.exe tools\\audio_diag.py
"""
import sys

import numpy as np
import sounddevice as sd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("=== host APIs ===")
for i, h in enumerate(sd.query_hostapis()):
    print(f"{i}: {h['name']:<24} default_input={h['default_input_device']}")

print("\n=== input devices ===")
devs = sd.query_devices()
inputs = []
for i, d in enumerate(devs):
    if d["max_input_channels"] > 0:
        inputs.append(i)
        api = sd.query_hostapis(d["hostapi"])["name"]
        print(f"{i:2d}  ch={d['max_input_channels']}  sr={int(d['default_samplerate'])}"
              f"  [{api}]  {d['name']}")

print("\ndefault input/output index:", sd.default.device)


def grab(dev, secs=2.0, sr=16000):
    rec = sd.rec(int(secs * sr), samplerate=sr, channels=1, dtype="float32", device=dev)
    sd.wait()
    return float(np.abs(rec).max()), float(np.sqrt(np.mean(rec ** 2))), len(rec)


print("\n=== 2 s capture per device (peak / rms) ===")
print(f"{'dev':>4}  {'peak':>9}  {'rms':>9}  name")
for dev in [None] + inputs:
    label = "def" if dev is None else str(dev)
    try:
        peak, rms, n = grab(dev)
        name = "system default" if dev is None else devs[dev]["name"]
        flag = "  <-- SIGNAL" if peak > 1e-4 else "  (silence)"
        print(f"{label:>4}  {peak:9.5f}  {rms:9.5f}  {name}{flag}")
    except Exception as e:
        print(f"{label:>4}  ERROR: {e}")
