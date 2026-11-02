"""tools/tasks_diag.py — run the real task-extraction path on the latest note and
report exactly what happens (heuristic + full LLM path + file writes)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core import llm_client                  # noqa: E402
from core import tasks as T                   # noqa: E402
from core.config import config                # noqa: E402

notes = config.notes_dir
bundles = sorted([p for p in notes.iterdir()
                  if p.is_dir() and p.name.startswith("note_") and (p / "transcript.txt").exists()],
                 key=lambda p: p.stat().st_mtime) if notes.exists() else []
if not bundles:
    print("NO transcripts to extract from.")
    sys.exit(0)

latest = bundles[-1]
txt = (latest / "transcript.txt").read_text(encoding="utf-8").strip()
print(f"note: {latest.name}")
print(f"transcript: {txt!r}\n")

h = T._heuristic_tasks(txt)
print(f"HEURISTIC -> {len(h['tasks'])} tasks: {[t['title'] for t in h['tasks']]}")

print("\nFULL extract (may start LM Studio, ~30-60s)...")
t0 = time.time()
try:
    res = T.extract_tasks(txt)
    print(f"  method={res['method']} in {time.time() - t0:.1f}s, tasks={len(res['tasks'])}")
    for t in res["tasks"]:
        print(f"    - [{t['priority']}] {t['title']}  owner={t.get('owner')} due={t.get('due')}")
except Exception as e:
    import traceback
    print("  EXTRACT THREW:", e)
    traceback.print_exc()
    res = None

if res is not None:
    config._data["tasks"]["output"] = ["local"]   # no sticky in the diag
    T.write_outputs(res, str(latest))
    print("\ntasks.json written:", (latest / "tasks.json").exists())
    print("tasks.md written :", (latest / "tasks.md").exists())
