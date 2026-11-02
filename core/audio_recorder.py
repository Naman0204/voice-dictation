"""
core/audio_recorder.py
Threaded microphone recorder. Audio blocks are queued from the real-time
sounddevice callback (which therefore never blocks), and a daemon writer thread
streams them to a 16 kHz mono PCM16 WAV, using a threading/queue/Event pattern.

Security: the input stream is opened only while recording and closed on stop, so
the microphone is never held open while idle.
"""
import queue
import threading
import traceback
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal


def resolve_device(name_or_index):
    """Map a config device value to a sounddevice index. None → default input."""
    if name_or_index is None:
        return None
    if isinstance(name_or_index, int):
        return name_or_index
    try:
        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0 and \
               str(name_or_index).lower() in dev["name"].lower():
                return idx
    except Exception:
        pass
    return None


class AudioRecorder(QObject):
    recording_started = Signal(str)          # wav path
    recording_stopped = Signal(str, float)   # wav path, duration seconds
    status_changed    = Signal(str)
    level_changed     = Signal(float)        # 0..1 peak (optional metering)
    error             = Signal(str)          # capture failed; the note is truncated

    def __init__(self, samplerate=16000, channels=1, blocksize=1600,
                 device=None, parent=None):
        super().__init__(parent)
        self._sr        = int(samplerate)
        self._ch        = int(channels)
        self._blocksize = int(blocksize)
        self._device    = device
        self._queue     = queue.Queue(maxsize=512)  # ~51 s slack at 100 ms blocks
        self._stop      = threading.Event()
        self._thread    = None
        self._stream    = None
        self._recording = False
        self._path      = ""
        self._frames    = 0
        self._peak      = 0.0      # max |sample| seen this recording (silence check)
        self._dropped   = 0        # blocks the writer could not keep up with
        self._failed    = ""       # writer error text, "" while healthy

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def last_peak(self) -> float:
        """Peak absolute amplitude (0..1) of the last/current recording."""
        return self._peak

    @property
    def last_error(self) -> str:
        """Writer error from the last recording, or "" if it completed cleanly."""
        return self._failed

    # ── Real-time audio callback (PortAudio thread) ───────────────────────
    def _callback(self, indata, frames, time_info, status):
        # Keep this microscopic: copy + non-blocking put, nothing else.
        try:
            self._queue.put_nowait(indata.copy())
        except queue.Full:
            # Drop a block rather than stall the real-time thread. Counted, not
            # silent: a dead writer shows up here as thousands of drops, and that
            # is the difference between "you said nothing" and "we lost it".
            self._dropped += 1

    def start_recording(self, wav_path: str):
        if self._recording:
            return
        Path(wav_path).parent.mkdir(parents=True, exist_ok=True)
        self._path      = wav_path
        self._frames    = 0
        self._peak      = 0.0
        self._dropped   = 0
        self._failed    = ""
        self._recording = True
        self._stop.clear()
        while not self._queue.empty():           # drop any stale blocks
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._thread = threading.Thread(target=self._write_loop, daemon=True)
        self._thread.start()
        self._stream = sd.InputStream(
            samplerate=self._sr, channels=self._ch, dtype="float32",
            blocksize=self._blocksize, device=self._device, callback=self._callback,
        )
        self._stream.start()
        self.recording_started.emit(self._path)
        self.status_changed.emit("REC")

    def stop_recording(self) -> float:
        if not self._recording:
            return 0.0
        self._recording = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        dur = self._frames / float(self._sr) if self._sr else 0.0
        if self._dropped:
            lost = self._dropped * self._blocksize / float(self._sr)
            print(f"[recorder] {self._dropped} block(s) dropped — {lost:.1f}s of audio lost")
        if self._failed:
            self.error.emit(f"Recording was cut short: {self._failed}")
        self.recording_stopped.emit(self._path, dur)
        self.status_changed.emit("")
        return dur

    def _write_loop(self):
        """Drain the queue to disk.

        Any exception in here used to kill the thread silently: `_recording` stayed
        True, the PortAudio callback kept filling a queue nobody read, every block
        after the first 512 hit queue.Full, and the WAV ended at whatever had
        already been flushed. The result was a 55-second recording that held 3.2
        seconds of audio and no error anywhere. Now the failure is logged, counted
        and surfaced."""
        wf = None
        try:
            wf = wave.open(self._path, "wb")
            wf.setnchannels(self._ch)
            wf.setsampwidth(2)          # PCM16
            wf.setframerate(self._sr)
            while not self._stop.is_set() or not self._queue.empty():
                try:
                    block = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                peak = float(np.abs(block).max()) if block.size else 0.0
                if peak > self._peak:
                    self._peak = peak
                pcm16 = (np.clip(block, -1.0, 1.0) * 32767.0).astype("<i2")
                wf.writeframes(pcm16.tobytes())
                self._frames += len(block)
                self.level_changed.emit(min(peak, 1.0))
        except Exception as e:
            self._failed = repr(e)
            secs = self._frames / float(self._sr) if self._sr else 0.0
            print(f"[recorder] writer thread died after {secs:.1f}s: {e!r}")
            traceback.print_exc()
        finally:
            if wf is not None:
                try:
                    wf.close()
                except Exception as e:
                    print(f"[recorder] closing the WAV failed: {e!r}")
