"""
core/transcriber.py
Local speech-to-text via faster-whisper (CTranslate2), CPU int8. Strictly CPU-
capped (cpu_threads + a BELOW_NORMAL process-priority window during inference) so
transcription stays within budget. Fully offline after a one-time model download.
The model is loaded once (pre-warmed on app start) behind a lock so the first
real transcription isn't penalised and concurrent calls can't double-load.
"""
import ctypes
import json
import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from core.config import config

_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
_NORMAL_PRIORITY_CLASS = 0x00000020


def _set_priority(priority_class):
    if sys.platform == "win32":
        try:
            k32 = ctypes.windll.kernel32
            k32.SetPriorityClass(k32.GetCurrentProcess(), priority_class)
        except Exception:
            pass


class Transcriber(QObject):
    model_state = Signal(str)        # "loading" | "ready" | "error"
    ready       = Signal(str, str)   # bundle_dir, text
    failed      = Signal(str, str)   # bundle_dir, error

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = None
        self._lock = threading.Lock()
        # Post-processing no longer blocks the hotkey, so two notes can be in
        # flight at once. A single CTranslate2 model with num_workers=1 is not
        # safe to call concurrently, so inference is serialised here.
        self._infer_lock = threading.Lock()

    def is_ready(self) -> bool:
        return self._model is not None

    # ── model load (idempotent, lock-serialised) ──────────────────────────
    def load(self):
        """Load the model, downloading once on first run. Safe to call from any
        worker thread; concurrent calls serialise on the lock."""
        with self._lock:
            if self._model is not None:
                return
            self.model_state.emit("loading")
            try:
                from faster_whisper import WhisperModel
                name = config.get("transcription.model", "base")
                kwargs = dict(
                    device="cpu",
                    compute_type=config.get("transcription.compute_type", "int8"),
                    cpu_threads=int(config.get("transcription.cpu_threads", 2)),
                    num_workers=1,
                )
                # Use the local cache only (no network). On first run the model
                # isn't cached, so fall back to a one-time online download; after
                # that every run takes the local_files_only path = zero network.
                try:
                    self._model = WhisperModel(name, local_files_only=True, **kwargs)
                except Exception:
                    self._model = WhisperModel(name, local_files_only=False, **kwargs)
                self.model_state.emit("ready")
            except Exception as e:
                self.model_state.emit("error")
                print(f"[transcriber] model load failed: {e}")

    # ── transcription (blocking; call off the GUI thread) ─────────────────
    def transcribe_file(self, audio_path: str, bundle_dir: str):
        if self._model is None:
            self.load()
        if self._model is None:
            self.failed.emit(bundle_dir, "model unavailable")
            return
        try:
            lang = config.get("transcription.language", "auto")
            prompt = config.get("transcription.biasing.initial_prompt", "") or None
            hotwords = config.get("transcription.biasing.hotwords", "") or None

            # SetPriorityClass moves the WHOLE process, including the PortAudio
            # capture thread and the Qt UI. Now that a new recording can start
            # while an older note is still transcribing, that would starve live
            # capture — so it is opt-in rather than always on.
            lower = bool(config.get("transcription.below_normal_priority", False))
            t0 = time.perf_counter()
            with self._infer_lock:
                if lower:
                    _set_priority(_BELOW_NORMAL_PRIORITY_CLASS)
                try:
                    segments, info = self._model.transcribe(
                        audio_path,
                        language=None if lang == "auto" else lang,
                        initial_prompt=prompt,
                        hotwords=hotwords,
                        vad_filter=True,
                        beam_size=int(config.get("transcription.beam_size", 5)),
                    )
                    seg_list = [{"start": round(s.start, 2), "end": round(s.end, 2),
                                 "text": s.text} for s in segments]   # realise generator
                finally:
                    if lower:
                        _set_priority(_NORMAL_PRIORITY_CLASS)
            wall = time.perf_counter() - t0

            text = "".join(s["text"] for s in seg_list).strip()
            dur = float(getattr(info, "duration", 0.0) or 0.0)
            bundle = Path(bundle_dir)
            bundle.mkdir(parents=True, exist_ok=True)
            (bundle / "transcript.txt").write_text(text, encoding="utf-8")
            (bundle / "transcript.json").write_text(json.dumps({
                "model": config.get("transcription.model", "base"),
                "compute_type": config.get("transcription.compute_type", "int8"),
                "cpu_threads": config.get("transcription.cpu_threads", 2),
                "language": getattr(info, "language", lang),
                "language_probability": round(getattr(info, "language_probability", 0.0) or 0.0, 3),
                "duration_s": round(dur, 2),
                "transcribe_wall_s": round(wall, 2),
                "rtf": round(wall / dur, 3) if dur else None,
                "biasing": {"initial_prompt": prompt or "", "hotwords": hotwords or ""},
                "segments": seg_list,
            }, indent=2), encoding="utf-8")
            self.ready.emit(bundle_dir, text)
        except Exception as e:
            self.failed.emit(bundle_dir, str(e))
            print(f"[transcriber] transcribe failed: {e}")
