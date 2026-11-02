"""
core/security.py
Local-only hardening helpers. The app never opens a network service of any kind;
these functions confirm we run from the project venv (not the Windows Store
Python), warn on elevation, lock the notes directory to the current user, and
provide a best-effort self-check that this process opens no listening sockets.
All defensive, all local — nothing here reaches the network.
"""
import ctypes
import getpass
import os
import subprocess
import sys
from pathlib import Path

EXPECTED_PYVER = (3, 12)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def check_python(root_dir: Path):
    """Return (ok, message). Confirms interpreter is the project venv on 3.12."""
    ver_ok = sys.version_info[:2] == EXPECTED_PYVER
    exe = Path(sys.executable).resolve()
    in_venv = str(root_dir.resolve()).lower() in str(exe).lower()
    if ver_ok and in_venv:
        return True, f"Python {sys.version.split()[0]} from project venv"
    msg = f"Python {sys.version.split()[0]} at {exe}"
    if not ver_ok:
        msg += f" (expected {EXPECTED_PYVER[0]}.{EXPECTED_PYVER[1]})"
    if not in_venv:
        msg += " (NOT the project .venv — launch via .venv\\Scripts\\python.exe)"
    return False, msg


def is_admin() -> bool:
    """True if running elevated. We deliberately do NOT need admin for anything."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def lock_directory(path: Path):
    """Restrict `path` to the current user + SYSTEM via icacls. Best-effort.
    Returns (ok, message)."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        user = os.environ.get("USERNAME") or getpass.getuser()
        proc = subprocess.run(
            ["icacls", str(path), "/inheritance:r",
             "/grant:r", f"{user}:(OI)(CI)F", "SYSTEM:(OI)(CI)F"],
            capture_output=True, text=True, check=False, creationflags=_NO_WINDOW,
        )
        if proc.returncode == 0:
            return True, f"Locked {path} to {user}"
        return False, f"icacls returned {proc.returncode}: {proc.stderr.strip()}"
    except Exception as e:
        return False, f"Could not lock {path}: {e}"


def listening_sockets(pid: int | None = None):
    """Best-effort list of TCP ports this process listens on — used only to
    *verify* the no-network-surface guarantee. Returns [] on any error or none."""
    pid = pid if pid is not None else os.getpid()
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-NetTCPConnection -State Listen -OwningProcess {pid} "
             "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty LocalPort"],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
        )
        return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    except Exception:
        return []
