"""
tools/transcribe_test.py
Validate the transcription pipeline on an existing audio file. First run downloads
the base model (~145 MB) once. Prints language, duration, RTF and the text.
Run: .venv\\Scripts\\python.exe tools\\transcribe_test.py <path-to-audio.flac>
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.transcriber import Transcriber  # noqa: E402

audio = sys.argv[1] if len(sys.argv) > 1 else None
if not audio or not Path(audio).exists():
    print("usage: transcribe_test.py <audio.flac>")
    sys.exit(2)
bundle = str(Path(audio).parent)

print("loading model (first run downloads the base model once)...")
t = Transcriber()
t0 = time.time()
t.load()
print(f"model ready={t.is_ready()} (load {time.time() - t0:.1f}s)")

t1 = time.time()
t.transcribe_file(audio, bundle)
print(f"transcribe wall {time.time() - t1:.1f}s")

tj = Path(bundle) / "transcript.json"
tt = Path(bundle) / "transcript.txt"
if tj.exists():
    d = json.loads(tj.read_text(encoding="utf-8"))
    print(f"language={d.get('language')} prob={d.get('language_probability')} "
          f"dur={d.get('duration_s')}s rtf={d.get('rtf')} segments={len(d.get('segments', []))}")
    print("TEXT:", repr(tt.read_text(encoding="utf-8")) if tt.exists() else "(none)")
else:
    print("no transcript.json written")
