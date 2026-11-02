"""
core/dictation.py
Real-time dictation: capture the mic, segment speech into phrases on silence,
transcribe each phrase with faster-whisper, and inject the recognized text into
the focused window via core.text_injector. Phrase-incremental — text appears
after each pause (word-by-word isn't feasible on CPU). Runs on its own threads
and reports state via Qt signals so the GUI never blocks.
"""
import queue
import threading
import time
import traceback

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal

from core import text_injector
from core.config import config


def _lang():
    """Dictation gets its own language setting, separate from batch transcription.

    Left on "auto", Whisper fed room tone will confidently emit fluent text in an
    unrelated script — a real session here filled a chat box with Sinhala. Pinning
    the language removes that whole failure mode."""
    lang = config.get("dictation.language", "en")
    return None if lang in (None, "", "auto") else lang


class Dictation(QObject):
    started = Signal()
    stopped = Signal()
    failed  = Signal(str)        # worker died / mic went away — state must be reset
    phrase  = Signal(str)        # text just injected
    status  = Signal(str)        # "listening" | "transcribing"

    SR = 16000
    BLOCK = 1600                 # 100 ms

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = None
        self._lock = threading.Lock()
        self._stream = None
        self._q = queue.Queue()
        self._stop = threading.Event()
        self._worker = None
        self._active = False
        self._target_hwnd = None
        self._injection = "type"
        self._recent = ""           # last phrases, used as context for the next

    @property
    def is_active(self) -> bool:
        return self._active

    def _ensure_model(self):
        with self._lock:
            if self._model is not None:
                return self._model
            from faster_whisper import WhisperModel
            kw = dict(device="cpu",
                      compute_type=config.get("transcription.compute_type", "int8"),
                      cpu_threads=int(config.get("dictation.cpu_threads", 4)), num_workers=1)
            name = config.get("dictation.model", "base")
            try:
                self._model = WhisperModel(name, local_files_only=True, **kw)
            except Exception:
                self._model = WhisperModel(name, local_files_only=False, **kw)
            return self._model

    def prewarm(self):
        """Load the dictation model ahead of first use.

        Dictation keeps its own WhisperModel, and it used to load lazily inside the
        worker — after the mic was already live. The first triple-tap D therefore
        ate a ~3.3s stall with audio piling up in the queue, which is most of what
        'delayed start' meant. Safe from any thread: _ensure_model is idempotent
        and lock-serialised."""
        try:
            t0 = time.perf_counter()
            self._ensure_model()
            print(f"[dictation] model pre-warmed in {time.perf_counter() - t0:.1f}s")
        except Exception as e:
            print(f"[dictation] model pre-warm failed: {e!r}")

    # ── lifecycle ──────────────────────────────────────────────────────────
    def start(self):
        if self._active:
            return
        self._injection = config.get("dictation.injection", "type")
        self._recent = ""
        self._target_hwnd = text_injector.foreground_window()
        text_injector.backspace(config.get("dictation.taps", 3))   # erase the "ddd" the toggle typed
        self._active = True
        self._stop.clear()
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        self._stream = sd.InputStream(samplerate=self.SR, channels=1, dtype="float32",
                                      blocksize=self.BLOCK, callback=self._cb)
        self._stream.start()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()
        print(f"[dictation] started (injection={self._injection}, target_hwnd={self._target_hwnd})")
        self.started.emit()
        self.status.emit("listening")

    def _close_stream(self):
        if self._stream is not None:
            try:
                self._stream.stop(); self._stream.close()
            except Exception as e:
                print(f"[dictation] closing the input stream failed: {e!r}")
            self._stream = None

    def stop(self):
        if not self._active:
            return
        self._active = False
        self._stop.set()
        self._close_stream()
        if self._worker is not None:
            # Called from the GUI thread, so this join is a UI freeze. Keep it
            # short and report rather than hanging the tray on a stuck worker.
            self._worker.join(timeout=8)
            if self._worker.is_alive():
                print("[dictation] worker did not exit within 8s — abandoning it")
            self._worker = None
        text_injector.backspace(config.get("dictation.taps", 3))   # erase the stop-toggle "ddd"
        print("[dictation] stopped")
        self.stopped.emit()

    # ── audio callback (RT thread) ────────────────────────────────────────
    def _cb(self, indata, frames, t, status):
        try:
            self._q.put_nowait(indata.copy())
        except queue.Full:
            pass

    # ── segmentation + transcription loop ─────────────────────────────────
    @staticmethod
    def _plausible(seg) -> bool:
        """Reject Whisper's noise hallucinations using its own per-segment
        confidence. Silence and fan noise score badly on both metrics; real speech
        does not."""
        max_no_speech = float(config.get("dictation.max_no_speech", 0.6))
        min_logprob = float(config.get("dictation.min_avg_logprob", -1.0))
        if float(getattr(seg, "no_speech_prob", 0.0) or 0.0) > max_no_speech:
            return False
        if float(getattr(seg, "avg_logprob", 0.0) or 0.0) < min_logprob:
            return False
        return True

    def _loop(self):
        """Crash barrier around the real worker.

        An exception escaping here used to kill the thread while `_active` stayed
        True. The app then sat in DICTATING forever: the record hotkey answered
        every triple-tap with "stop dictation first", and nothing could clear it
        short of a restart. Now any failure drops dictation and tells the
        controller, so the state machine always converges back to idle."""
        try:
            self._run()
        except Exception as e:
            print(f"[dictation] worker died: {e!r}")
            traceback.print_exc()
            self._active = False
            self._stop.set()
            self._close_stream()
            self.failed.emit(str(e))

    def _run(self):
        model = self._ensure_model()
        sr = self.SR
        silence_ms = int(config.get("dictation.silence_ms", 600))
        min_phrase_ms = int(config.get("dictation.min_phrase_ms", 350))
        thresh = float(config.get("dictation.silence_rms", 0.006))
        beam = int(config.get("dictation.beam_size", 1))
        buf, voiced, silent_for = [], False, 0.0

        def flush():
            nonlocal buf, voiced, silent_for
            chunk, buf, voiced, silent_for = buf, [], False, 0.0
            if not chunk:
                return
            audio = np.concatenate(chunk).flatten().astype(np.float32)
            if len(audio) / sr * 1000 < min_phrase_ms or float(np.abs(audio).max() or 0) < 1e-3:
                return
            self.status.emit("transcribing")
            try:
                segs, _ = model.transcribe(audio, language=_lang(), beam_size=beam,
                                           initial_prompt=(self._recent or None),
                                           vad_filter=True)
                text = "".join(s.text for s in segs if self._plausible(s)).strip()
            except Exception as e:
                # A single bad phrase must not take dictation down — log and keep
                # listening. Only stream/model-level failures reach _loop.
                print(f"[dictation] transcribe failed: {e!r}")
                text = ""
            if text:
                text_injector.insert(text + " ", method=self._injection)
                self.phrase.emit(text)
                self._recent = (self._recent + " " + text)[-200:]   # context for next phrase
                print(f"[dictation] injected: {text!r}")
            self.status.emit("listening")

        stall_s = float(config.get("dictation.stall_timeout_s", 20))
        last_block = time.monotonic()

        while not self._stop.is_set() or not self._q.empty():
            try:
                block = self._q.get(timeout=0.1)
            except queue.Empty:
                # PortAudio input streams die silently across sleep/resume and
                # device changes: the callback simply stops firing. Without this
                # check the loop spins on an empty queue forever and dictation
                # looks alive while capturing nothing.
                if stall_s > 0 and not self._stop.is_set() \
                        and time.monotonic() - last_block > stall_s:
                    raise RuntimeError(
                        f"the microphone stopped delivering audio for {stall_s:.0f}s")
                continue
            last_block = time.monotonic()
            rms = float(np.sqrt(np.mean(block ** 2))) if block.size else 0.0
            block_ms = len(block) / sr * 1000
            if rms >= thresh:
                voiced, silent_for = True, 0.0
                buf.append(block)
            elif voiced:
                buf.append(block)                 # keep a little trailing silence
                silent_for += block_ms
                if silent_for >= silence_ms:
                    flush()
        flush()                                   # final phrase when stopping
