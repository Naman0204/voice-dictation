"""
tools/tasks_llm_test.py
Exercise the LOCAL LLM task-extraction path: start LM Studio's server, load the
model, extract tasks from a sample transcript, and print the structured result.
Run: .venv\\Scripts\\python.exe tools\\tasks_llm_test.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core import llm_client          # noqa: E402
from core import tasks as T          # noqa: E402

SAMPLE = ("Okay, I need to finalize the slide deck before tomorrow's review. "
          "Alex will update the staging server by Friday. We should also order two new "
          "monitors, that's urgent. Don't forget to back up the database tonight. Let's schedule "
          "a planning meeting next week.")

print("server up before:", llm_client.is_up())
t0 = time.time()
ok = llm_client.ensure_server(timeout=90)
print(f"ensure_server -> {ok} in {time.time() - t0:.1f}s; model = {llm_client.loaded_model()}")

if ok:
    t1 = time.time()
    res = T.extract_tasks(SAMPLE)
    print(f"\nextract: method={res['method']}  in {time.time() - t1:.1f}s")
    print("summary:", res.get("summary"))
    for t in res["tasks"]:
        print(f"  - [{t['priority']}] {t['title']}  | owner={t.get('owner')} | due={t.get('due')}")
    print("\nRESULT:", "PASS (llm)" if res["method"] == "llm" and res["tasks"] else
          "FELL BACK TO HEURISTIC" if res["tasks"] else "NO TASKS")
else:
    print("LLM not available; the app would use the heuristic fallback.")
