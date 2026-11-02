"""
core/tasks.py
Extract action items / a plan from a transcript. LLM-first via a local LM Studio
(core/llm_client), with a regex heuristic fallback when no local LLM is reachable.
Writes tasks.json + tasks.md into the note bundle, appends to a master file, and
optionally pushes to Windows Sticky Notes (best-effort).
"""
import json
import re
from datetime import datetime
from pathlib import Path

from core import llm_client, sticky_notes
from core.config import config

_SYS = (
    "You extract concrete action items from a voice-note transcript. "
    "Return ONLY valid minified JSON, no markdown, no commentary, shaped exactly as: "
    '{"summary": str, "tasks": [{"title": str, "owner": str|null, "due": str|null, '
    '"priority": "high"|"normal"|"low"}]}. '
    "Include only real, actionable tasks the speaker intends to do or assign. "
    "If there are none, return an empty tasks list."
)

_PRI = {"high": "[!]", "normal": "[ ]", "low": "[~]"}


# ── extraction ───────────────────────────────────────────────────────────────
def _extract_json(text):
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None


def _norm(data, method):
    tasks = []
    for t in data.get("tasks", []):
        if not isinstance(t, dict) or not t.get("title"):
            continue
        pr = t.get("priority")
        tasks.append({
            "title": str(t["title"]).strip(),
            "owner": (t.get("owner") or None),
            "due": (t.get("due") or None),
            "priority": pr if pr in ("high", "normal", "low") else "normal",
        })
    return {"summary": str(data.get("summary", "")).strip(), "tasks": tasks, "method": method}


def _llm_tasks(transcript):
    if not llm_client.ensure_server():
        return None
    reply = llm_client.chat([
        {"role": "system", "content": _SYS},
        {"role": "user", "content": "Transcript:\n" + transcript.strip() + "\n\nJSON:"},
    ])
    data = _extract_json(reply)
    return _norm(data, "llm") if data and "tasks" in data else None


_CUE = re.compile(r"\b(?:i|we|you|let'?s)\s+(?:need to|should|must|have to|will|gotta|want to|plan to)\s+(.+)", re.I)
_MARK = re.compile(r"\b(?:todo|to-do|action item|follow[ -]?up|remember to|don'?t forget to)\b[:\-\s]+(.+)", re.I)
_ASSIGN = re.compile(r"\b([A-Z][a-z]+)\s+(?:will|should|needs to|has to)\s+(.+)")


def _heuristic_tasks(transcript):
    tasks, seen = [], set()

    def add(title, owner=None, priority="normal"):
        title = re.split(r"[.!?\n]", title.strip())[0].strip(" ,.;:")
        key = title.lower()
        if len(title) >= 4 and key not in seen:
            seen.add(key)
            tasks.append({"title": title, "owner": owner, "due": None, "priority": priority})

    pron = {"we", "i", "you", "they", "he", "she", "it", "let", "lets",
            "okay", "so", "this", "that", "there", "then"}
    for line in re.split(r"[.!?\n]", transcript):
        s = line.strip()
        if not s:
            continue
        title, owner = None, None
        m = _MARK.search(s)
        if m:
            title = m.group(1)
        else:
            a = _ASSIGN.search(s)
            if a and a.group(1).lower() not in pron:     # a real name, not a pronoun
                title, owner = a.group(2), a.group(1)
            else:
                c = _CUE.search(s)
                if c:
                    title = c.group(1)
        if not title:
            continue
        pr = "high" if re.search(r"\b(urgent|asap|critical|today|right now|immediately|by tonight)\b",
                                 s, re.I) else "normal"
        add(title, owner=owner, priority=pr)
    return {"summary": f"{len(tasks)} action item(s) found by keyword.", "tasks": tasks[:25], "method": "heuristic"}


def extract_tasks(transcript):
    """Return {summary, tasks, method}. Local LLM first, heuristic fallback."""
    if not transcript or not transcript.strip():
        return {"summary": "", "tasks": [], "method": "empty"}
    return _llm_tasks(transcript) or _heuristic_tasks(transcript)


# ── output ───────────────────────────────────────────────────────────────────
def _md_lines(result):
    out = []
    for t in result["tasks"]:
        bits = [t["title"]]
        if t.get("owner"):
            bits.append(f"@{t['owner']}")
        if t.get("due"):
            bits.append(f"(due {t['due']})")
        box = "- [ ] " + (_PRI.get(t["priority"], "") + " " if t["priority"] != "normal" else "")
        out.append(box + " ".join(bits))
    return out


def write_outputs(result, bundle_dir):
    bundle = Path(bundle_dir)
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "tasks.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = _md_lines(result) or ["_(no tasks found)_"]
    (bundle / "tasks.md").write_text(
        "\n".join([f"# Tasks — {bundle.name}", "", result.get("summary", ""), ""] + lines),
        encoding="utf-8")

    outputs = config.get("tasks.output", ["local"])
    if "local" in outputs and result["tasks"]:
        master = config.notes_dir / config.get("tasks.master_file", "tasks_master.md")
        header = "" if master.exists() else "# Voice Notes — master task list\n"
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        block = [f"\n## {bundle.name}  ({stamp})  ·  via {result['method']}"] + _md_lines(result)
        with open(master, "a", encoding="utf-8") as f:
            f.write(header + "\n".join(block) + "\n")
    if "sticky" in outputs and result["tasks"]:
        try:
            sticky_notes.push_tasks(result, title=f"Tasks — {bundle.name}")
        except Exception as e:
            print(f"[tasks] sticky push failed: {e}")
    return result
