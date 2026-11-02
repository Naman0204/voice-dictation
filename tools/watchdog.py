"""
watchdog.py  —  keep Voice Notes alive between logins.

Run periodically by the Scheduled Task "VoiceNotesWatchdog" (at logon + every
few minutes, in the user's interactive session, via the venv pythonw.exe).

It probes the app's own single-instance mutex ("VoiceNotes_SingleInstance_v1",
created in main.py). If the mutex exists the app is running and we do nothing.
If it does not exist the app is down, so we relaunch it detached and note it in
watchdog.log. Probing (OpenMutexW) never creates the mutex, so there is no race
and no risk of spawning a duplicate — main.py's guard is the single source of
truth for "already running".

Runs under pythonw (no console): file I/O only, never print().
"""
import ctypes
import os
import subprocess
from datetime import datetime

MUTEX_NAME = "VoiceNotes_SingleInstance_v1"      # must match main.py
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # voice_notes/
PYTHONW = os.path.join(ROOT, ".venv", "Scripts", "pythonw.exe")
LOG = os.path.join(ROOT, "watchdog.log")


def _log(msg: str) -> None:
    try:
        with open(LOG, "a", encoding="utf-8", buffering=1) as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [watchdog] {msg}\n")
    except Exception:
        pass


def _app_running() -> bool:
    """True if the Voice Notes single-instance mutex exists in this session."""
    SYNCHRONIZE = 0x00100000
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenMutexW.restype = ctypes.c_void_p
    k32.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = k32.OpenMutexW(SYNCHRONIZE, False, MUTEX_NAME)
    if handle:
        k32.CloseHandle(handle)
        return True
    return False


def main() -> int:
    try:
        if _app_running():
            return 0                              # healthy — stay quiet
        if not os.path.exists(PYTHONW):
            _log(f"cannot relaunch: missing {PYTHONW}")
            return 1
        # Detached so the app outlives this watchdog run. Mirror the Startup
        # shortcut exactly: no stdout/stderr redirection, so under pythonw
        # sys.stdout stays None and main.py redirects its prints to app.log.
        # Only stdin is pinned to DEVNULL — that is the part that prevents the
        # known pythonw child-process hang.
        subprocess.Popen(
            [PYTHONW, "main.py"],
            cwd=ROOT,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
        _log("app was not running -> relaunched")
        return 0
    except Exception as e:                         # never crash the task
        _log(f"error: {e!r}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
