"""
core/config.py
Persisted settings for Voice Notes — audio device, hotkey behaviour, overlay
placement, transcription model, rolling-retention limits and security toggles.
Stored as a small JSON file in the project root. Emits `changed` so live widgets
can react. Deep-merges stored values over the defaults so new keys appear
automatically on upgrade.
"""
import json
from pathlib import Path

from PySide6.QtCore import QObject, Signal

_ROOT = Path(__file__).resolve().parent.parent
_PATH = _ROOT / "config.json"

_DEFAULTS = {
    "audio": {
        "device": None,          # None = system default input; or a name substring
        "samplerate": 16000,     # Whisper-native; capture here to avoid resampling
        "channels": 1,
        "blocksize": 1600,       # 100 ms blocks at 16 kHz
    },
    "hotkey": {
        "key": "r",              # trigger key: "r" | "ctrl_r" | "ctrl_l" | "scroll_lock"
        "taps": 3,               # triple-tap
        "window_ms": 600,        # all taps must fall within this rolling window
        "cooldown_ms": 1500,     # ignore re-trigger for this long after firing
        "erase_trigger_chars": False,  # backspace the "rrr" the trigger typed; off by
                                       # default because recording is often started
                                       # with no text field focused
    },
    "overlay": {
        "corner": "top_right",   # top_right | top_left | bottom_right | bottom_left
        "screen_index": 0,
        "margin": 16,
    },
    "transcription": {
        "enabled": True,
        "engine": "faster-whisper",
        "model": "small",        # upgraded from base for accuracy (2026-06-21)
        "compute_type": "int8",
        "cpu_threads": 8,        # was 2, which put a 3s note at 235s wall (RTF 73x)
        "beam_size": 1,          # was 5; greedy is ~5x faster and `small` carries the accuracy
        "language": "auto",      # "auto" | "en" | ...
        "below_normal_priority": False,  # lowering priority moves the WHOLE process,
                                         # including live capture — opt in only
        "biasing": {
            # Comma-separated domain terms you want Whisper to recognize more
            # reliably (names, acronyms, jargon). Empty by default; add your own.
            "initial_prompt": "",
            "hotwords": "",
        },
    },
    "dictation": {              # Feature B — type speech into the focused field
        "hotkey": "d",          # triple-tap D toggles dictation
        "taps": 3,
        "window_ms": 600,
        "cooldown_ms": 1500,
        "model": "small",       # upgraded from base for accuracy (2026-06-21). Keep it:
                                # base is ~3x faster but renders "telemetry link" as
                                # "to limit tree length" — it loses the jargon.
        "cpu_threads": 8,       # was 4; 2.60s -> 2.29s per phrase on this 8-core part
        "beam_size": 1,         # greedy — keep dictation latency low (model gives the accuracy)
        "prewarm": True,        # load the model at launch, not on the first triple-tap D
        "silence_ms": 600,      # silence gap that ends a phrase
        "silence_rms": 0.006,   # RMS below this = silence (tune per mic)
        "min_phrase_ms": 350,   # ignore ultra-short blips
        "injection": "type",    # "type" (SendInput unicode) | "paste" (clipboard+Ctrl+V)
        "language": "en",       # pinned: on "auto" Whisper renders room noise as
                                # fluent text in random scripts (a session produced
                                # pages of Sinhala). "auto" still allowed.
        "stall_timeout_s": 20,  # no audio for this long = the mic died; stop cleanly
        "max_no_speech": 0.6,   # drop segments Whisper itself doubts are speech
        "min_avg_logprob": -1.0,  # drop low-confidence segments (noise hallucinations)
    },
    "tasks": {                  # Feature A — extract tasks/plan from a transcript
        "llm_base_url": "http://localhost:1234/v1",
        "model": "",            # "" = whatever LM Studio has loaded
        "auto_start_lms": True,  # try `lms server start` if the server is down
        "output": ["local", "sticky"],   # subset of ["local","sticky"]
        "master_file": "tasks_master.md",
        "restart_sticky": False,  # restart the Notes app so a new sticky shows (intrusive)
    },
    "retention": {
        "max_age_days": 30,
        "audio_cap_gb": 3.5,
        "keep_transcripts": True,  # keep the (tiny) text even after audio is pruned
    },
    "storage": {
        "format": "flac",
    },
    "ui": {
        "startup_notification": True,   # show a "ready" tray popup at launch
    },
    "security": {
        "warn_if_admin": True,
        "lock_notes_dir": True,
    },
}


def _merge(base: dict, stored: dict) -> dict:
    out = json.loads(json.dumps(base))  # deep copy
    for k, v in stored.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        elif k in out:
            out[k] = v
    return out


class _Config(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._data = json.loads(json.dumps(_DEFAULTS))
        try:
            if _PATH.exists():
                self._data = _merge(_DEFAULTS, json.loads(_PATH.read_text()))
        except Exception:
            pass
        self._save()  # ensure a template config.json always exists on disk

    def _save(self):
        try:
            _PATH.write_text(json.dumps(self._data, indent=2))
        except Exception:
            pass

    # ── Dotted get/set (e.g. "audio.samplerate") ──────────────────────────
    def get(self, path: str, default=None):
        node = self._data
        for part in path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def set(self, path: str, value):
        parts = path.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        if node.get(parts[-1]) != value:
            node[parts[-1]] = value
            self._save()
            self.changed.emit()

    # ── Paths ─────────────────────────────────────────────────────────────
    @property
    def root_dir(self) -> Path:
        return _ROOT

    @property
    def notes_dir(self) -> Path:
        return _ROOT / "notes"


config = _Config()
