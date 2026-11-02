"""
core/retention.py
Rolling-storage manager. Keeps the audio store under a hard size cap and within
a maximum age, deleting the OLDEST audio first. Transcripts (tiny) are kept even
after their audio is pruned, so notes persist while audio rolls off. Runs on
startup and after every recording.
"""
import time
from pathlib import Path

AUDIO_NAMES = ("audio.flac", "audio.wav")


def _audio_files(notes_dir: Path):
    items = []
    if not notes_dir.exists():
        return items
    for bundle in notes_dir.iterdir():
        if not bundle.is_dir():
            continue
        for name in AUDIO_NAMES:
            f = bundle / name
            if f.exists():
                try:
                    st = f.stat()
                    items.append((f, st.st_size, st.st_mtime))
                except Exception:
                    pass
    items.sort(key=lambda t: t[2])          # oldest first
    return items


def _delete(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except Exception:
        return False


def prune(notes_dir: Path, max_age_days: float, audio_cap_gb: float) -> dict:
    """Delete oldest audio past max_age_days, then until total <= cap.
    Returns dict(removed, freed_bytes, remaining_bytes)."""
    files = _audio_files(Path(notes_dir))
    cap_bytes = int(audio_cap_gb * (1024 ** 3))
    now = time.time()
    age_limit = max_age_days * 86400.0
    removed, freed = 0, 0

    # 1) age-based eviction
    survivors = []
    for f, size, mtime in files:
        if max_age_days and (now - mtime) > age_limit:
            if _delete(f):
                removed += 1
                freed += size
        else:
            survivors.append((f, size, mtime))

    # 2) size-based eviction (oldest first until under cap)
    total = sum(s for _, s, _ in survivors)
    i = 0
    while total > cap_bytes and i < len(survivors):
        f, size, _ = survivors[i]
        if _delete(f):
            removed += 1
            freed += size
            total -= size
        i += 1

    return {"removed": removed, "freed_bytes": freed, "remaining_bytes": total}
