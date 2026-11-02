"""
tools/dictation_real_test.py
Drive the REAL dictation pipeline (real faster-whisper model) with synthesized
speech and confirm it transcribes + would inject the right words. Injection and
window-focus are faked so nothing is typed and no mic is needed.
Run: .venv\\Scripts\\python.exe tools\\dictation_real_test.py
"""
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np                 # noqa: E402
import soundfile as sf             # noqa: E402

import core.text_injector as ti    # noqa: E402

PHRASE = ("Send this message to the team. The test flight is scheduled for tomorrow morning "
          "at the north field.")

wav = Path(tempfile.gettempdir()) / "vn_dict_tts.wav"
ps = ('Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer;'
      f' $s.Rate = -1; $s.SetOutputToWaveFile("{wav}"); $s.Speak("{PHRASE}"); $s.Dispose()')
subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True,
               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

audio, sr = sf.read(str(wav), dtype="float32")
if audio.ndim > 1:
    audio = audio[:, 0]
if sr != 16000:                                  # crude linear resample to 16 kHz
    n = int(len(audio) * 16000 / sr)
    audio = np.interp(np.linspace(0, len(audio), n, endpoint=False),
                      np.arange(len(audio)), audio).astype(np.float32)
print(f"TTS: {len(audio)/16000:.1f}s @16k")

captured = []
ti.insert = lambda text, method="type": captured.append(text)
ti.foreground_window = lambda: 1
ti.backspace = lambda n: None

from core.dictation import Dictation              # noqa: E402

d = Dictation()
d._target_hwnd = 1
d._active = True
d._stop.clear()
w = threading.Thread(target=d._loop, daemon=True)
w.start()

for i in range(0, len(audio), 1600):
    blk = audio[i:i + 1600]
    if len(blk) < 1600:
        blk = np.pad(blk, (0, 1600 - len(blk)))
    d._q.put(blk.reshape(-1, 1))
for _ in range(10):                              # trailing silence -> final flush
    d._q.put(np.zeros((1600, 1), dtype=np.float32))

time.sleep(10)                                   # model load + transcribe segments
d._stop.set()
w.join(timeout=20)

text = " ".join(captured).lower()
print("captured pieces:", captured)
hits = sum(kw in text for kw in ("message", "team", "test flight", "tomorrow", "field"))
ok = hits >= 2
print(f"\nkeyword hits: {hits}/5")
print("RESULT:", "PASS" if ok else "FAIL")
try:
    wav.unlink()
except Exception:
    pass
sys.exit(0 if ok else 1)
