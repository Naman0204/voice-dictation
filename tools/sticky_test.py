"""
tools/sticky_test.py
Verify the Sticky Notes insert path: push a test note, confirm a backup was made,
read the row back from plum.sqlite, then DELETE the test row again (so we don't
leave clutter). Run: .venv\\Scripts\\python.exe tools\\sticky_test.py
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core import sticky_notes      # noqa: E402

print("Sticky Notes DB available:", sticky_notes.available())
sample = {"summary": "t", "tasks": [
    {"title": "Review slide deck", "owner": None, "due": None, "priority": "normal"},
    {"title": "Order monitors", "owner": "Alex", "due": "Friday", "priority": "high"},
]}
ok = sticky_notes.push_tasks(sample, title="VN_STICKY_TEST")
print("push_tasks ->", ok)
print("backup exists:", Path(str(sticky_notes._DB) + ".voicenotes.bak").exists())

con = sqlite3.connect(f"file:{sticky_notes._DB}?mode=ro", uri=True)
rows = con.execute("select Id, Text, Theme, IsOpen from Note where Text like '%VN_STICKY_TEST%'").fetchall()
con.close()
print("inserted rows found:", len(rows))
for r in rows:
    print("   id=", r[0][:8], "theme=", r[2], "open=", r[3], "text=", repr(r[1][:90]))

# cleanup: delete the test row(s) we created
if rows:
    con = sqlite3.connect(str(sticky_notes._DB), timeout=5)
    con.execute("delete from Note where Text like '%VN_STICKY_TEST%'")
    con.commit()
    con.close()
    print("cleaned up test rows")

print("\nRESULT:", "PASS" if ok and rows else "FAIL")
sys.exit(0 if ok and rows else 1)
