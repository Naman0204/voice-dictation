"""
tools/integration_test.py
Full Phase-2 wiring test: drive the controller's post-recording flow
(encode -> transcribe -> prune) on a real synthesized-speech clip and confirm a
correct transcript bundle is produced. Proves the controller wiring, not just the
individual stages. Uses Windows TTS so no mic/voice is needed.
Run: .venv\\Scripts\\python.exe tools\\integration_test.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PySide6.QtWidgets import QApplication            # noqa: E402

from core import audio_store                          # noqa: E402
from core.app_controller import AppController         # noqa: E402
from core.config import config                        # noqa: E402
from ui.recording_overlay import RecordingOverlay     # noqa: E402
from ui.tray import TrayIcon                           # noqa: E402

PHRASE = ("Phase two test. The prototype booted at twenty two point eight "
          "volts and entered standby mode.")

tmpwav = Path(tempfile.gettempdir()) / "vn_integ_tts.wav"
ps = ('Add-Type -AssemblyName System.Speech; '
      '$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Rate = -1; '
      f'$s.SetOutputToWaveFile("{tmpwav}"); $s.Speak("{PHRASE}"); $s.Dispose()')
subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True,
               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

app = QApplication(sys.argv)
tray, overlay = TrayIcon(), RecordingOverlay()
ctrl = AppController(tray, overlay)              # does NOT start the global hook
ctrl._transcriber.load()
print("model ready:", ctrl._transcriber.is_ready())

bundle = audio_store.new_bundle(config.notes_dir)
wav = audio_store.wav_path(bundle)
shutil.copy(tmpwav, wav)
ctrl._postprocess(bundle, str(wav), 0.5)         # encode -> transcribe -> prune (0.5 = non-silent)

flac = bundle / "audio.flac"
txt = bundle / "transcript.txt"
js = bundle / "transcript.json"
ok = flac.exists() and not wav.exists() and txt.exists() and js.exists()
text = txt.read_text(encoding="utf-8") if txt.exists() else ""
has_jargon = "prototype" in text.lower() and "standby" in text.lower()
print(f"flac={flac.exists()} wav_deleted={not wav.exists()} "
      f"transcript.txt={txt.exists()} transcript.json={js.exists()}")
print("TRANSCRIPT:", repr(text))
print("bundle files:", [p.name for p in bundle.iterdir()])

shutil.rmtree(bundle, ignore_errors=True)
tmpwav.unlink(missing_ok=True)
print("\nRESULT:", "PASS" if (ok and has_jargon) else "FAIL")
sys.exit(0 if (ok and has_jargon) else 1)
