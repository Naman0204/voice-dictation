"""
main.py
Voice Notes entry point — a background system-tray app. Triple-tap R to
start/stop recording; a small click-through HUD shows while recording; audio is
stored as rolling, size-capped FLAC. Fully local: no network service, no cloud.

Always run via the project venv:
    .venv\\Scripts\\python.exe main.py
"""
import ctypes
import os
import sys
import threading
import traceback
from datetime import datetime

# NOTE: PySide6 / numpy / sounddevice are imported inside main(), *after* the
# single-instance guard — see the comment there. Only cheap stdlib at module level.

_MUTEX_HANDLE = None     # kept alive for the process lifetime


class _Null:
    def write(self, *a): pass
    def flush(self): pass


def _usable(stream) -> bool:
    """True only if `stream` actually accepts a write. Under pythonw sys.stdout is
    None, but a process launched with inherited-but-dead std handles gets a stream
    that exists and silently swallows (or errors on) every write — which is how a
    worker-thread crash went unlogged for a day and a half."""
    try:
        stream.write("")
        stream.flush()
        return True
    except Exception:
        return False


def _open_log():
    """Open app.log and prove it is writable with a session header. Returns the
    file object, or None if the log is unusable (locked, read-only, disk full)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.log")
    try:
        f = open(path, "a", encoding="utf-8", buffering=1)
        f.write(f"\n===== session {datetime.now():%Y-%m-%d %H:%M:%S} "
                f"pid={os.getpid()} =====\n")
        f.flush()
        return f
    except Exception:
        return None


def _install_excepthooks():
    """Route unhandled exceptions — including ones on daemon worker threads — into
    the log. Without the threading hook a dead capture/dictation thread leaves no
    trace at all; the app just stops doing its job."""
    def _main_hook(exc_type, exc, tb):
        print("[fatal] unhandled exception on the main thread:")
        traceback.print_exception(exc_type, exc, tb)

    def _thread_hook(args):
        name = args.thread.name if args.thread is not None else "?"
        print(f"[fatal] unhandled exception on thread {name!r}:")
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = _main_hook
    threading.excepthook = _thread_hook


def _is_console(stream) -> bool:
    """True only for a genuine interactive console we should leave alone."""
    try:
        return bool(stream.isatty()) and _usable(stream)
    except Exception:
        return False


def _setup_logging():
    """Send output to app.log unless this process has a real console.

    "Is the stream writable?" was not a strong enough test: a watchdog-launched
    instance inherits std handles that accept writes and go nowhere, so it ran for
    minutes without a single line in app.log. Only an interactive console keeps
    its own stdout now — everything else is logged."""
    log = _open_log()
    fallback = log if log is not None else _Null()
    if not _is_console(sys.stdout):
        sys.stdout = fallback
    if not _is_console(sys.stderr):
        sys.stderr = fallback
    _install_excepthooks()


def _is_only_instance() -> bool:
    """True if no other Voice Notes instance is running (single-instance guard).
    Prevents a second copy (e.g. autostart + a manual launch) from registering a
    second global hotkey hook and double-triggering recordings."""
    global _MUTEX_HANDLE
    if sys.platform != "win32":
        return True
    ERROR_ALREADY_EXISTS = 183
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # argtypes/restype declared so the 64-bit HANDLE isn't truncated to int.
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    k32.CreateMutexW.restype = ctypes.c_void_p
    _MUTEX_HANDLE = k32.CreateMutexW(None, False, "VoiceNotes_SingleInstance_v1")
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def main():
    _setup_logging()                 # make print() safe under pythonw (no console)
    if not _is_only_instance():
        print("[startup] Voice Notes is already running — exiting this instance.")
        return 0

    # Heavy imports happen only after this process has won the guard. Importing
    # PySide6 + numpy + sounddevice took ~25s on a cold cache, and doing it at
    # module level put that entire window *before* the mutex was claimed: the
    # Startup shortcut and the watchdog, launched 16s apart, both got through and
    # ran two tray apps with two global hotkey hooks.
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon    # noqa: E402

    from core import security                                       # noqa: E402
    from core.app_controller import AppController                   # noqa: E402
    from core.config import config                                  # noqa: E402
    from ui.recording_overlay import RecordingOverlay               # noqa: E402
    from ui.tray import TrayIcon                                    # noqa: E402

    ok, msg = security.check_python(config.root_dir)
    print(f"[security] {msg}")
    if config.get("security.warn_if_admin", True) and security.is_admin():
        print("[security] WARNING: running elevated — not required; prefer a standard user.")

    app = QApplication(sys.argv)
    app.setApplicationName("Voice Notes")
    app.setQuitOnLastWindowClosed(False)        # tray app: there is no main window

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("[fatal] No system tray available on this session.")
        return 1

    if config.get("security.lock_notes_dir", True):
        _, lmsg = security.lock_directory(config.notes_dir)
        print(f"[security] {lmsg}")

    tray = TrayIcon()
    overlay = RecordingOverlay()
    controller = AppController(tray, overlay)
    tray.quit_requested.connect(app.quit)
    app.aboutToQuit.connect(controller.shutdown)
    controller.start()

    print(f"[ready] Voice Notes in the tray. Triple-tap "
          f"'{config.get('hotkey.key', 'r')}' to record. PID={os.getpid()}")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
