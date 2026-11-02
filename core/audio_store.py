"""
core/audio_store.py
Per-recording bundle layout + lossless FLAC encoding. Each recording lives in
its own folder: notes/note_YYYYMMDD_HHMMSS/ holding audio.flac (and, later,
transcript.txt / transcript.json / corrected.txt). We record to a temp WAV for
reliable writes, then stream-encode to FLAC (~2x smaller, lossless) and delete
the WAV to respect the storage budget.
"""
from datetime import datetime
from pathlib import Path

import soundfile as sf

WAV_NAME  = "audio.wav"
FLAC_NAME = "audio.flac"


def new_bundle(notes_dir: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = notes_dir / f"note_{ts}"
    bundle, n = base, 1
    while bundle.exists():                 # guard same-second collisions
        bundle = Path(f"{base}_{n}")
        n += 1
    bundle.mkdir(parents=True, exist_ok=True)
    return bundle


def wav_path(bundle: Path) -> Path:
    return bundle / WAV_NAME


def flac_path(bundle: Path) -> Path:
    return bundle / FLAC_NAME


def encode_to_flac(wav: Path, flac: Path, delete_wav: bool = True) -> Path:
    """Stream-encode WAV → FLAC in blocks (low memory). Returns the FLAC path."""
    wav, flac = Path(wav), Path(flac)
    with sf.SoundFile(str(wav)) as fin, \
         sf.SoundFile(str(flac), mode="w", samplerate=fin.samplerate,
                      channels=fin.channels, format="FLAC", subtype="PCM_16") as fout:
        for block in fin.blocks(blocksize=65536, dtype="int16"):
            fout.write(block)
    if delete_wav:
        try:
            wav.unlink()
        except Exception:
            pass
    return flac
