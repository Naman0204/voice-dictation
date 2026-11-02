"""
core/sticky_notes.py
Best-effort push of a task list into Windows Sticky Notes by inserting a new row
into its SQLite store (plum.sqlite). Defensive by design: backs the DB up first,
only ever INSERTs a new note (never edits existing ones), reuses an existing
note's parent so it joins the same notebook, and uses the app's .NET-ticks
timestamps. Sticky Notes caches in memory, so a new note usually shows only after
the app reloads — set tasks.restart_sticky to relaunch it automatically.
"""
import os
import shutil
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.config import config

_DB = (Path(os.environ.get("LOCALAPPDATA", "")) / "Packages"
       / "Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe" / "LocalState" / "plum.sqlite")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_APPID = "Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe!App"


def available() -> bool:
    return _DB.exists()


def _ticks_now() -> int:
    # .NET DateTime.Ticks — 100-ns intervals since 0001-01-01 UTC
    delta = datetime.now(timezone.utc) - datetime(1, 1, 1, tzinfo=timezone.utc)
    return int(delta.total_seconds() * 10_000_000)


def push_tasks(result, title="Voice Notes tasks", theme="Yellow") -> bool:
    """Insert a new sticky note with the task list. Returns True on success."""
    if not _DB.exists():
        return False

    lines = [title]
    for t in result.get("tasks", []):
        owner = f" @{t['owner']}" if t.get("owner") else ""
        due = f" (due {t['due']})" if t.get("due") else ""
        lines.append(f"• {t['title']}{owner}{due}")
    # Sticky Notes stores one paragraph per line, each prefixed with \id=<guid>
    text = "\n".join(f"\\id={uuid.uuid4()} {ln}" for ln in lines)

    try:
        shutil.copy2(_DB, str(_DB) + ".voicenotes.bak")     # backup before any write
    except Exception:
        pass

    con = sqlite3.connect(str(_DB), timeout=5)
    try:
        cur = con.cursor()
        row = cur.execute("select ParentId from Note where DeletedAt is null "
                          "and ParentId is not null limit 1").fetchone()
        parent = row[0] if row else None
        nid, ticks = str(uuid.uuid4()), _ticks_now()
        cur.execute(
            "insert into Note (Text, WindowPosition, IsOpen, IsAlwaysOnTop, IsFutureNote, "
            "RemoteSchemaVersion, IsRemoteDataInvalid, PendingInsightsScan, Id, ParentId, "
            "CreatedAt, UpdatedAt, Theme) values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (text, "", 1, 0, 0, 0, 0, 0, nid, parent, ticks, ticks, theme))
        con.commit()
    finally:
        con.close()

    if config.get("tasks.restart_sticky", False):
        _restart_sticky()
    return True


def _restart_sticky():
    try:
        subprocess.run(["taskkill", "/im", "Microsoft.Notes.exe", "/f"],
                       capture_output=True, text=True, creationflags=_NO_WINDOW)
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{_APPID}"])
    except Exception as e:
        print(f"[sticky] restart failed: {e}")
