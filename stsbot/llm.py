"""The local LLM (Ollama on this PC) that makes fight and card-pick decisions. Answers are JSON.

    ask(system, user) -> dict | None        # None on timeout, connection failure or unreadable JSON
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

OLLAMA = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3-vl:8b-instruct"  # the user's choice: a fast 8B model that fits on the GPU
TIMEOUT = 20.0  # seconds; the user allows about 10 per decision, this is the hard stop
OPTIONS = {"temperature": 0.2, "num_ctx": 8192, "num_predict": 400}

last = {"seconds": 0.0, "error": "", "raw": ""}  # the last call, for the log


def ask(system: str, user: str, model: str = MODEL) -> dict | None:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": "json",
        "stream": False,
        "keep_alive": "30m",  # stay loaded between decisions
        "options": OPTIONS,
    }).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            reply = json.loads(r.read().decode())
        text = reply.get("message", {}).get("content", "")
        last.update(seconds=time.time() - t, error="", raw=text)
        return json.loads(text)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        last.update(seconds=time.time() - t, error=f"no answer: {e}", raw="")
    except ValueError as e:
        last.update(seconds=time.time() - t, error=f"not JSON: {e}")
    return None


def warm_up():
    """Load the model before the first real decision (the first call is slow)."""
    ask("Answer in JSON.", 'Reply with {"ok": true}.')
