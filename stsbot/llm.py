"""The local LLM (Ollama on this PC) that makes fight and card-pick decisions. Answers are JSON.

    ask(system, user) -> dict | None        # None on timeout, connection failure or unreadable JSON
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3-vl:8b-instruct"  # the user's choice: a fast 8B model that fits on the GPU
TIMEOUT = 20.0  # seconds; the user allows about 10 per decision, this is the hard stop
REVIEW_TIMEOUT = 120.0  # a run review writes much more
OPTIONS = {"temperature": 0.2, "num_ctx": 8192, "num_predict": 400}

last = {"seconds": 0.0, "error": "", "raw": ""}  # the last call, for the log

# What the dashboard shows as the LLM thinks: the call in progress (its answer as it streams in) and
# the recent calls. Written to small files at most every LIVE_EVERY seconds, so the bot is not slowed.
DATA = Path(__file__).resolve().parent.parent / "data"
LIVE_FILE = DATA / "llm_live.json"
HISTORY_FILE = DATA / "llm_history.jsonl"
LIVE_EVERY = 0.3
HISTORY_KEEP = 60


def _write_live(entry: dict):
    try:
        DATA.mkdir(exist_ok=True)
        tmp = LIVE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry), encoding="utf-8")
        tmp.replace(LIVE_FILE)
    except OSError:
        pass  # the dashboard is only a view; never let it stop a decision


def _add_history(entry: dict):
    try:
        lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines() if HISTORY_FILE.exists() else []
        lines = (lines + [json.dumps(entry)])[-HISTORY_KEEP:]
        HISTORY_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def ask(system: str, user: str, model: str = MODEL, kind: str = "", options: dict | None = None) -> dict | None:
    """Ask the model; the answer streams in (shown live on the dashboard) and is parsed as JSON at the end."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": "json",
        "stream": True,
        "keep_alive": "30m",  # stay loaded between decisions
        "options": options or OPTIONS,
    }).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    t = time.time()
    entry = {"kind": kind, "started": time.strftime("%H:%M:%S"), "prompt": user, "text": "", "done": False,
             "seconds": 0.0, "error": ""}
    _write_live(entry)
    parts: list[str] = []
    shown = t
    try:
        limit = REVIEW_TIMEOUT if options and options.get("num_predict", 0) > OPTIONS["num_predict"] else TIMEOUT
        with urllib.request.urlopen(req, timeout=limit) as r:
            for raw in r:
                if not raw.strip():
                    continue
                chunk = json.loads(raw.decode())
                parts.append(chunk.get("message", {}).get("content", ""))
                if time.time() - shown > LIVE_EVERY:
                    shown = time.time()
                    entry.update(text="".join(parts), seconds=round(shown - t, 1))
                    _write_live(entry)
                if chunk.get("done"):
                    break
                if time.time() - t > limit:
                    raise TimeoutError("took too long")
        text = "".join(parts)
        last.update(seconds=time.time() - t, error="", raw=text)
        return json.loads(text)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        last.update(seconds=time.time() - t, error=f"no answer: {e}", raw="")
    except ValueError as e:
        last.update(seconds=time.time() - t, error=f"not JSON: {e}", raw="".join(parts))
    finally:
        entry.update(text="".join(parts), done=True, seconds=round(time.time() - t, 1), error=last["error"])
        _write_live(entry)
        _add_history(entry)
    return None


def warm_up():
    """Load the model before the first real decision (the first call is slow)."""
    ask("Answer in JSON.", 'Reply with {"ok": true}.', kind="warm up")
