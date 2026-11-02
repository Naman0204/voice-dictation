"""
core/llm_client.py
Minimal client for a LOCAL OpenAI-compatible LLM server (LM Studio at
http://localhost:1234/v1 by default). Detects whether a server is up, optionally
starts LM Studio's headless server via the `lms` CLI, and runs chat completions.
Pure `requests` — no cloud, no new dependency. Returns None when unavailable so
callers can fall back to heuristics.
"""
import subprocess
import time

import requests

from core.config import config

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _base():
    return config.get("tasks.llm_base_url", "http://localhost:1234/v1").rstrip("/")


def loaded_model():
    """Return an available model id, or None if the server isn't up / has none."""
    try:
        data = requests.get(_base() + "/models", timeout=3).json().get("data", [])
        return data[0]["id"] if data else None
    except Exception:
        return None


def is_up() -> bool:
    return loaded_model() is not None


def ensure_server(timeout=25) -> bool:
    """If no server is reachable, best-effort `lms server start`, then wait. Returns
    True once a model is reachable within `timeout` seconds."""
    if is_up():
        return True
    if not config.get("tasks.auto_start_lms", True):
        return False
    try:
        subprocess.run(["lms", "server", "start"], capture_output=True, text=True,
                       timeout=25, creationflags=_NO_WINDOW, stdin=subprocess.DEVNULL)
    except Exception as e:
        print(f"[llm] `lms server start` failed: {e}")
        return False
    t0 = time.time()
    while time.time() - t0 < timeout:
        if is_up():
            return True
        time.sleep(1.5)
    return is_up()


def chat(messages, temperature=0.1, max_tokens=1500, timeout=180):
    """Run a chat completion. Returns the assistant text, or None on failure."""
    model = config.get("tasks.model", "") or loaded_model()
    if not model:
        return None
    try:
        r = requests.post(_base() + "/chat/completions", timeout=timeout, json={
            "model": model, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens, "stream": False,
        })
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[llm] chat failed: {e}")
        return None
