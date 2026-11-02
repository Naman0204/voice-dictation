"""
tools/record_probe.py
Measure CPU while in the RECORDING state (mic capture + writer thread + overlay
repaint) for a few seconds, using whole-process CPU time. No hotkey/tray needed.
Run: .venv\\Scripts\\python.exe tools\\record_probe.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PySide6.QtCore import QTimer                  # noqa: E402
from PySide6.QtWidgets import QApplication         # noqa: E402

from core.audio_recorder import AudioRecorder      # noqa: E402
from core.config import config                     # noqa: E402
from ui.recording_overlay import RecordingOverlay  # noqa: E402

DUR = 12
app = QApplication(sys.argv)
rec = AudioRecorder(samplerate=16000, channels=1, blocksize=1600)
ov = RecordingOverlay()
tmp = Path(tempfile.mkdtemp()) / "probe.wav"
cores = os.cpu_count() or 1

ov.start(corner=config.get("overlay.corner", "top_right"),
         margin=config.get("overlay.margin", 16))
rec.start_recording(str(tmp))
c0, w0 = time.process_time(), time.perf_counter()


def done():
    cpu, wall = time.process_time() - c0, time.perf_counter() - w0
    rec.stop_recording()
    ov.stop()
    pct = cpu / (wall * cores) * 100
    print(f"RECORDING state: {pct:.2f}% of total CPU over {wall:.1f}s "
          f"({cores} cores), captured peak={rec.last_peak:.4f}")
    sys.stdout.flush()
    try:
        os.remove(tmp)
    except Exception:
        pass
    app.quit()


QTimer.singleShot(DUR * 1000, done)
sys.exit(app.exec())
