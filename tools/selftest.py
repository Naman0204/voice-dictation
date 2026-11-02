"""
tools/selftest.py
Headless Phase-1 self-test: triple-tap FSM, FLAC encode, retention pruning, and
a best-effort short real microphone capture. Prints PASS/FAIL per check and
exits non-zero if any hard check fails. No GUI, no network.
Run: .venv\\Scripts\\python.exe tools\\selftest.py
"""
import shutil
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:                                                # Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from core import audio_store, retention            # noqa: E402
from core.hotkey_listener import TapDetector        # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ── 1. TapDetector ──────────────────────────────────────────────────────────
class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


clk = Clock()


def triple(det, gap=0.1):
    fires = 0
    for _ in range(3):
        clk.t += gap
        if det.on_trigger_press():
            fires += 1
        det.on_trigger_release()
    return fires


d = TapDetector(taps=3, window_s=0.45, cooldown_s=1.5, clock=clk)
check("triple-tap fires once", triple(d) == 1)

clk.t += 5.0
d2 = TapDetector(clock=clk)
rep = sum(1 for _ in range(6) if (clk.__setattr__('t', clk.t + 0.02) or d2.on_trigger_press()))
check("auto-repeat (held key) ignored", rep == 0, f"fires={rep}")

clk.t += 5.0
d3 = TapDetector(window_s=0.45, clock=clk)
check("slow taps outside window don't fire", triple(d3, gap=0.5) == 0)

clk.t += 5.0
d4 = TapDetector(clock=clk)
f4 = 0
clk.t += 0.1; f4 += int(d4.on_trigger_press()); d4.on_trigger_release()
d4.on_other_key()                                   # typing another key resets
clk.t += 0.1; f4 += int(d4.on_trigger_press()); d4.on_trigger_release()
clk.t += 0.1; f4 += int(d4.on_trigger_press()); d4.on_trigger_release()
check("interleaved other key breaks sequence", f4 == 0, f"fires={f4}")

clk.t += 5.0
d5 = TapDetector(taps=3, window_s=0.45, cooldown_s=1.5, clock=clk)
f5 = triple(d5) + triple(d5)                        # second triple is within cooldown
check("cooldown blocks immediate re-fire", f5 == 1, f"fires={f5}")

# ── 2. FLAC encode + 3. retention ────────────────────────────────────────────
tmp = Path(tempfile.mkdtemp(prefix="vn_selftest_"))
try:
    sr = 16000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    tone = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    wav = tmp / "audio.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
        wf.writeframes((np.clip(tone, -1, 1) * 32767).astype("<i2").tobytes())
    wav_size = wav.stat().st_size

    flac = tmp / "audio.flac"
    audio_store.encode_to_flac(wav, flac, delete_wav=True)
    import soundfile as sf
    info = sf.info(str(flac))
    check("flac created", flac.exists())
    check("wav deleted after encode", not wav.exists())
    check("flac is 16k mono", info.samplerate == sr and info.channels == 1,
          f"{info.samplerate}/{info.channels}")
    check("flac smaller than wav", flac.stat().st_size < wav_size,
          f"{flac.stat().st_size} < {wav_size}")

    import os
    notes = tmp / "notes"; notes.mkdir()
    for i in range(3):
        b = notes / f"note_2026010{i}_000000"; b.mkdir()
        (b / "transcript.txt").write_text("hello")
        f = b / "audio.flac"; f.write_bytes(b"\0" * (1024 * 1024))   # 1 MB each
        os.utime(f, (1000 + i, 1000 + i))                            # bundle 0 oldest
    retention.prune(notes, max_age_days=0, audio_cap_gb=1.5 / 1024)  # cap ~1.5 MB
    remaining = list(notes.rglob("audio.flac"))
    transcripts = list(notes.rglob("transcript.txt"))
    check("retention removed oldest audio to fit cap", len(remaining) == 1,
          f"remaining={len(remaining)}")
    check("retention kept all transcripts", len(transcripts) == 3,
          f"transcripts={len(transcripts)}")
    check("newest audio survived", bool(remaining) and "2_000000" in remaining[0].parent.name,
          f"kept={remaining[0].parent.name if remaining else None}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ── 4. best-effort real mic capture ──────────────────────────────────────────
try:
    from core.audio_recorder import AudioRecorder
    rec = AudioRecorder(samplerate=16000, channels=1, blocksize=1600)
    cap = Path(tempfile.mkdtemp(prefix="vn_mic_"))
    wavp = cap / "audio.wav"
    rec.start_recording(str(wavp))
    time.sleep(1.5)
    dur = rec.stop_recording()
    fmt_ok = False
    frames = 0
    ok = wavp.exists() and wavp.stat().st_size > 44
    if ok:
        with wave.open(str(wavp)) as wf:
            frames = wf.getnframes()
            fmt_ok = (wf.getframerate() == 16000 and wf.getnchannels() == 1
                      and wf.getsampwidth() == 2)
    check("mic capture to 16k mono wav with frames", ok and fmt_ok and frames > 0,
          f"dur={dur:.2f}s frames={frames}")
    shutil.rmtree(cap, ignore_errors=True)
except Exception as e:
    print(f"[SKIP] mic capture ({e}) — mic may be unavailable/blocked; not a hard failure")

# ── summary ───────────────────────────────────────────────────────────────────
passed = sum(1 for _, ok in results if ok)
print(f"\n{passed}/{len(results)} hard checks passed.")
sys.exit(0 if passed == len(results) else 1)
