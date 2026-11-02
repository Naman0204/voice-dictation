"""
tools/tasks_test.py
Test Feature A task extraction: heuristic path + output files. Uses the local LLM
only if it's ALREADY running (won't auto-start the heavy 12B here). Writes only
into a temp bundle (no master/sticky side effects).
Run: .venv\\Scripts\\python.exe tools\\tasks_test.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core import llm_client                  # noqa: E402
from core import tasks as T                   # noqa: E402
from core.config import config                # noqa: E402

config._data["tasks"]["auto_start_lms"] = False     # keep the test fast/quiet
config._data["tasks"]["output"] = []                # no master/sticky side effects

results = []


def ck(n, c):
    results.append(bool(c))
    print(f"[{'PASS' if c else 'FAIL'}] {n}")


SAMPLE = ("Okay, I need to finalize the slide deck before tomorrow's review. "
          "Alex will update the staging server. We should also order two new monitors, "
          "that's urgent. Don't forget to back up the database tonight.")

h = T._heuristic_tasks(SAMPLE)
ck("heuristic finds >= 3 tasks", len(h["tasks"]) >= 3)
print("   heuristic:", [t["title"] for t in h["tasks"]])
ck("heuristic detects owner (Alex)", any(t.get("owner") == "Alex" for t in h["tasks"]))
ck("heuristic flags urgent as high", any(t["priority"] == "high" for t in h["tasks"]))

print("LM Studio reachable right now:", llm_client.is_up())
res = T.extract_tasks(SAMPLE)
ck("extract_tasks returns tasks", len(res["tasks"]) >= 1)
print(f"   method={res['method']}  summary={res.get('summary','')[:70]}")

tmp = Path(tempfile.mkdtemp(prefix="vn_tasks_"))
bundle = tmp / "note_20260618_000000"
bundle.mkdir(parents=True)
T.write_outputs(res, str(bundle))
ck("tasks.json written", (bundle / "tasks.json").exists())
ck("tasks.md written", (bundle / "tasks.md").exists())
print("   --- tasks.md ---")
print("   " + (bundle / "tasks.md").read_text(encoding="utf-8").replace("\n", "\n   "))
shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
