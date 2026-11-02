"""
core/app_controller.py
The application brain: a small state machine (IDLE → RECORDING → STOPPING → IDLE,
plus DICTATING) that wires the hotkey, tray and overlay to the recorder and the
transcriber. It is the only place application state mutates and the only object
that touches the GUI widgets — heavy work runs on worker threads and reports back
via queued Qt signals so the UI never freezes.

Post-processing (encode + transcribe + prune) deliberately has no state of its
own: it runs detached on a worker and is counted in `_jobs`, so a slow Whisper
pass can never block the next recording.
"""
import os
import subprocess
import threading
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot, QTimer
from PySide6.QtWidgets import QApplication

from core import audio_store, retention, text_injector
from core.audio_recorder import AudioRecorder, resolve_device
from core.config import config
from core.dictation import Dictation
from core.hotkey_listener import HotkeyListener
from core.power_notify import PowerNotifier
from core.transcriber import Transcriber


class State(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    STOPPING = "stopping"
    DICTATING = "dictating"         # Feature B — typing speech into the focused field


class AppController(QObject):
    _postprocess_done = Signal(str, float)   # bundle dir, peak (from a worker thread)
    _tasks_done = Signal(str)         # tray-balloon message (emitted from a worker thread)

    def __init__(self, tray, overlay, parent=None):
        super().__init__(parent)
        self._tray = tray
        self._overlay = overlay
        self._state = State.IDLE
        self._bundle = None
        self._jobs = 0             # notes still encoding/transcribing in the background

        self._recorder = AudioRecorder(
            samplerate=config.get("audio.samplerate", 16000),
            channels=config.get("audio.channels", 1),
            blocksize=config.get("audio.blocksize", 1600),
            device=resolve_device(config.get("audio.device")),
        )
        self._hotkey = HotkeyListener([
            {"name": "record", "key": config.get("hotkey.key", "r"),
             "taps": config.get("hotkey.taps", 3),
             "window_ms": config.get("hotkey.window_ms", 450),
             "cooldown_ms": config.get("hotkey.cooldown_ms", 1500)},
            {"name": "dictate", "key": config.get("dictation.hotkey", "d"),
             "taps": config.get("dictation.taps", 3),
             "window_ms": config.get("dictation.window_ms", 450),
             "cooldown_ms": config.get("dictation.cooldown_ms", 1500)},
        ])
        self._transcriber = Transcriber()
        self._dictation = Dictation()
        self._power = PowerNotifier(on_suspend=self.on_suspend)

        # ── wiring ────────────────────────────────────────────────────────
        self._hotkey.triggered.connect(self._on_hotkey)
        self._dictation.started.connect(self._on_dictation_started)
        self._dictation.stopped.connect(self._on_dictation_stopped)
        self._dictation.failed.connect(self._on_dictation_failed)
        self._tray.toggle_requested.connect(self.request_toggle)
        self._tray.open_notes_requested.connect(self._open_notes)
        self._tray.purge_requested.connect(self._purge)
        self._tray.restart_requested.connect(self._restart)
        self._tray.extract_tasks_latest.connect(self._extract_latest)
        self._tray.extract_tasks_all.connect(self._extract_all)
        self._tasks_done.connect(self._on_tasks_done)
        self._recorder.recording_started.connect(self._on_recording_started)
        self._recorder.recording_stopped.connect(self._on_recording_stopped)
        self._recorder.error.connect(self._on_recorder_error)
        self._overlay.folder_clicked.connect(self._open_notes)
        self._transcriber.model_state.connect(self._on_model_state)
        self._postprocess_done.connect(self._on_postprocess_done)

        self._prune()   # enforce the storage budget at startup

    def start(self):
        self._hotkey.start()
        self._tray.show()
        self._power.register()                            # finalize recordings before sleep
        print(f"[power] suspend-notify registered: {self._power.is_registered()}")
        threading.Thread(target=self._prewarm_models, daemon=True).start()
        if config.get("ui.startup_notification", True):   # tell the user it's listening (esp. after a boot)
            QTimer.singleShot(1500, lambda: self._tray.message(
                "Voice Notes is ready", "Triple-tap R to start or stop a recording."))

    def _prewarm_models(self):
        """Load both Whisper models in the background, one after the other.

        Recording and dictation each hold their own model. Sequential rather than
        two threads so launch doesn't spike every core at once."""
        if config.get("transcription.enabled", True):
            self._transcriber.load()
        if config.get("dictation.prewarm", True):
            self._dictation.prewarm()

    def shutdown(self):
        try:
            self._power.unregister()
            if self._dictation.is_active:
                self._dictation.stop()
            if self._recorder.is_recording:
                self._recorder.stop_recording()
        except Exception:
            pass
        self._hotkey.stop()

    def on_suspend(self):
        """Called from the power-notification thread when the system is about to
        sleep/hibernate — finalize any in-progress recording so it's saved cleanly
        before suspend. Runs synchronously (the WAV is closed before the machine
        sleeps); encode + transcribe run on resume via the queued signal."""
        try:
            if self._recorder.is_recording:
                print("[power] system suspending — stopping the active recording")
                self._recorder.stop_recording()
        except Exception as e:
            print(f"[power] suspend stop failed: {e}")

    # ── hotkey routing (record vs dictate) ────────────────────────────────
    def _heal_state(self):
        """Reconcile the cached state with reality before acting on a trigger.

        DICTATING is the one state that can outlive the thing it describes: if the
        dictation worker died, the flag stayed set and every later triple-tap R was
        answered with "stop dictation first" — forever. Trust the Dictation object
        over the cached enum."""
        if self._state is State.DICTATING and not self._dictation.is_active:
            print("[controller] stale DICTATING state with no active dictation — resetting to idle")
            self._state = State.IDLE
            self._overlay.stop()
            self._tray.set_status("idle")

    @Slot(str)
    def _on_hotkey(self, name):
        self._heal_state()
        print(f"[hotkey] {name} (state={self._state.value})")
        if name == "record":
            if self._state is State.DICTATING:
                self._tray.message("Voice Notes", "Stop dictation (triple-tap D) before recording a note.")
                return
            self.request_toggle()
        elif name == "dictate":
            self._toggle_dictation()

    def _toggle_dictation(self):
        if self._state is State.DICTATING:
            self._dictation.stop()                 # emits stopped → _on_dictation_stopped
        elif self._state is State.IDLE:
            self._state = State.DICTATING
            try:
                self._dictation.start()
            except Exception as e:
                self._state = State.IDLE
                self._overlay.stop()
                self._tray.message("Voice Notes", f"Couldn't start dictation: {e}")
                print(f"[dictation] start failed: {e}")
        else:
            self._tray.message("Voice Notes", "Finish the current note before dictating.")

    @Slot()
    def _on_dictation_started(self):
        self._overlay.start_dictation(
            corner=config.get("overlay.corner", "top_right"),
            screen_index=config.get("overlay.screen_index", 0),
            margin=config.get("overlay.margin", 16))
        self._tray.set_status("dictating — typing into the focused field")
        self._tray.message("Voice Notes — dictation ON",
                           "Speak; text types where your cursor is after each pause. Triple-tap D to stop.")

    @Slot()
    def _on_dictation_stopped(self):
        self._overlay.stop()
        self._state = State.IDLE
        self._tray.set_status("idle")

    @Slot(str)
    def _on_dictation_failed(self, why):
        """The dictation worker died (mic went away, model failed). Return to idle
        so the record hotkey keeps working, and say why."""
        print(f"[dictation] failed: {why}")
        self._overlay.stop()
        self._state = State.IDLE
        self._tray.set_status("idle")
        self._tray.message("Voice Notes — dictation stopped", why)

    # ── toggle entry point (hotkey + tray) ────────────────────────────────
    @Slot()
    def request_toggle(self):
        self._heal_state()
        if self._state is State.IDLE:
            self._begin_recording()
        elif self._state is State.RECORDING:
            self._end_recording()
        elif self._state is State.DICTATING:
            self._tray.message("Voice Notes", "Stop dictation (triple-tap D) before recording a note.")
        else:                                  # STOPPING — a brief, genuine window
            self._tray.message("Voice Notes", "Closing the last recording…")

    # ── recording lifecycle ───────────────────────────────────────────────
    def _erase_trigger_chars(self):
        """The keyboard listener is deliberately non-suppressing, so the "rrr" that
        fired the hotkey also lands in whatever has focus. Dictation always erases
        it (you are typing into a field by definition); recording asks, because a
        note is often started with a non-text window focused, where stray
        Backspaces mean something else entirely — browser "back", for one."""
        if config.get("hotkey.erase_trigger_chars", False):
            text_injector.backspace(config.get("hotkey.taps", 3))

    def _begin_recording(self):
        try:
            self._erase_trigger_chars()
            # Paint the HUD before touching the audio device. Constructing the
            # input stream blocks this (the GUI) thread for 130-270ms, and doing
            # it first meant a quarter-second of nothing after the triple-tap —
            # the hotkey read as slow. The except branch hides it again on failure.
            self._overlay.start(
                corner=config.get("overlay.corner", "top_right"),
                screen_index=config.get("overlay.screen_index", 0),
                margin=config.get("overlay.margin", 16),
            )
            self._bundle = audio_store.new_bundle(config.notes_dir)
            self._recorder.start_recording(str(audio_store.wav_path(self._bundle)))
            self._state = State.RECORDING          # only after capture actually starts
        except Exception as e:                     # mic busy/unplugged/permission
            self._state = State.IDLE
            self._overlay.stop()
            self._tray.set_recording(False)
            self._tray.message("Voice Notes", f"Couldn't start recording: {e}")
            print(f"[controller] start_recording failed: {e}")

    def _end_recording(self):
        self._erase_trigger_chars()
        self._state = State.STOPPING
        self._recorder.stop_recording()    # drains writer, emits recording_stopped

    @Slot(str)
    def _on_recording_started(self, path):
        # The overlay is already up — _begin_recording paints it before opening
        # the device so the trigger feels instant.
        self._tray.set_recording(True, 0)

    @Slot(str, float)
    def _on_recording_stopped(self, path, duration):
        """Hand the note off to a worker and go straight back to IDLE.

        This used to enter TRANSCRIBING and stay there until encode + Whisper
        finished. With a slow transcribe that was a multi-minute window in which
        every triple-tap R was answered with "Busy finishing the last note…" — the
        hotkey looked dead. Post-processing is background work, so it no longer
        owns the state machine; `_jobs` just tracks it for the tray tooltip."""
        self._overlay.show_done()          # pill becomes a clickable "Open" folder button for 3s
        self._tray.set_recording(False)
        peak = self._recorder.last_peak
        bundle = self._bundle
        self._bundle = None
        self._state = State.IDLE           # free the hotkey immediately
        self._jobs += 1
        self._tray.set_status("transcribing…" if peak >= 1e-3 else "saving…")
        threading.Thread(target=self._postprocess,
                         args=(bundle, path, peak), daemon=True).start()

    def _postprocess(self, bundle, wav_path_str, peak):
        """Worker thread: encode to FLAC, transcribe, prune. Everything it needs is
        passed in — reading it off self would race the next recording."""
        flac = None
        try:
            wav = Path(wav_path_str)
            if wav.exists() and wav.stat().st_size > 44:    # > WAV header
                flac = audio_store.encode_to_flac(wav, audio_store.flac_path(bundle))
        except Exception as e:
            print(f"[postprocess] encode failed: {e!r}")
        # Transcribe (skip pure silence — nothing to recognise).
        if flac and config.get("transcription.enabled", True) and peak >= 1e-3:
            try:
                self._transcriber.transcribe_file(str(flac), str(bundle))
            except Exception as e:
                print(f"[postprocess] transcribe failed: {e!r}")
        try:
            self._prune()
        except Exception as e:
            print(f"[postprocess] prune failed: {e!r}")
        self._postprocess_done.emit(str(bundle), peak)

    @Slot(str, float)
    def _on_postprocess_done(self, bundle_str, peak):
        self._jobs = max(0, self._jobs - 1)
        if self._jobs:
            self._tray.set_status(f"transcribing… ({self._jobs} queued)")
        elif self._state is State.IDLE:    # never clobber a recording that started meanwhile
            self._tray.set_status("idle")
        if peak < 1e-3:        # ~ -60 dBFS: effectively silence
            self._tray.message(
                "Voice Notes",
                "Recorded near-silence — check the mic isn't muted and its input level isn't 0.")
            return
        txt = Path(bundle_str) / "transcript.txt"
        if txt.exists():
            snippet = txt.read_text(encoding="utf-8").strip()
            if snippet:
                preview = snippet[:140] + "…" if len(snippet) > 140 else snippet
                self._tray.message("Voice Notes", "Transcribed: " + preview)
            else:
                self._tray.message("Voice Notes", "Saved — no speech detected.")
        else:
            self._tray.message("Voice Notes", "Note saved (transcription unavailable).")

    @Slot(str)
    def _on_recorder_error(self, msg):
        """Capture failed mid-recording — say so instead of quietly saving a stub."""
        self._tray.message("Voice Notes", msg)

    @Slot(str)
    def _on_model_state(self, state):
        if state == "loading":
            self._tray.set_status("loading model…")
        elif state in ("ready", "error") and self._state is State.IDLE and not self._jobs:
            self._tray.set_status("idle")

    # ── helpers ───────────────────────────────────────────────────────────
    def _prune(self):
        retention.prune(
            config.notes_dir,
            config.get("retention.max_age_days", 30),
            config.get("retention.audio_cap_gb", 3.5),
        )

    @Slot()
    def _open_notes(self):
        try:
            config.notes_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(config.notes_dir))
        except Exception:
            pass

    @Slot()
    def _purge(self):
        retention.prune(config.notes_dir, max_age_days=0, audio_cap_gb=0)  # drop all audio
        self._tray.message("Voice Notes", "All stored audio purged.")

    # ── tasks (Feature A) ─────────────────────────────────────────────────
    def _note_bundles(self, with_transcript=False):
        d = config.notes_dir
        if not d.exists():
            return []
        bundles = [p for p in d.iterdir() if p.is_dir() and p.name.startswith("note_")]
        if with_transcript:
            bundles = [p for p in bundles if (p / "transcript.txt").exists()]
        bundles.sort(key=lambda p: p.stat().st_mtime)
        return bundles

    @Slot()
    def _extract_latest(self):
        threading.Thread(target=self._run_extract, args=("latest",), daemon=True).start()

    @Slot()
    def _extract_all(self):
        threading.Thread(target=self._run_extract, args=("all",), daemon=True).start()

    def _run_extract(self, scope):
        from core import tasks as tasks_mod        # lazy: keeps startup light
        print(f"[tasks] extract requested (scope={scope})")
        bundles = self._note_bundles(with_transcript=True)
        if scope == "latest":
            bundles = bundles[-1:]
        else:
            bundles = [b for b in bundles if not (b / "tasks.json").exists()]
        if not bundles:
            print("[tasks] no transcripts to extract from")
            self._tasks_done.emit("No transcripts found to extract tasks from.")
            return
        self._tasks_done.emit(f"Extracting tasks from {len(bundles)} note(s)…")
        total, method = 0, "keywords"
        for b in bundles:
            try:
                txt = (b / "transcript.txt").read_text(encoding="utf-8").strip()
                if not txt:
                    continue
                res = tasks_mod.extract_tasks(txt)
                tasks_mod.write_outputs(res, str(b))
                total += len(res["tasks"])
                method = res["method"]
            except Exception as e:
                import traceback
                print(f"[tasks] {b.name} failed: {e}")
                traceback.print_exc()
        print(f"[tasks] complete: {total} task(s) from {len(bundles)} note(s) via {method}")
        self._tasks_done.emit(
            f"Found {total} task(s) across {len(bundles)} note(s) via {method}. Saved to the notes folder.")

    @Slot(str)
    def _on_tasks_done(self, msg):
        self._tray.message("Voice Notes — tasks", msg)

    @Slot()
    def _restart(self):
        """Relaunch the app from the tray (no reboot needed). A detached helper
        waits for this instance to exit — releasing the single-instance lock —
        then starts a fresh one."""
        try:
            if self._recorder.is_recording:           # don't lose an active recording
                self._recorder.stop_recording()
            pyw = str(config.root_dir / ".venv" / "Scripts" / "pythonw.exe")
            relauncher = str(config.root_dir / "tools" / "relauncher.pyw")
            subprocess.Popen([pyw, relauncher], cwd=str(config.root_dir),
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
        except Exception as e:
            print(f"[restart] could not spawn relauncher: {e}")
            return
        QApplication.quit()
