"""The bot's dashboard: a page on this PC only (http://localhost:8765).

Shows status (running or not, HP, floor, ascension, deck, build) and the bot's latest log lines; starts and
stops the bot (one copy only); edits the settings it starts with; and shows the images folder with a
button to draw any picture (or a random one) on the map. Drawing needs the mouse, so a running bot is
stopped for it and started again afterwards; if the map is not on screen it is opened and closed again.

    python -m stsbot.dashboard        (or double-click "StsBot Dashboard.cmd")
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LOGS = ROOT / "logs"
SETTINGS = DATA / "settings.json"
PORT = 8765
DEFAULTS = {"draw": True, "still": 5.0, "runs": 1, "llm": True}

app = FastAPI()
_lock = threading.Lock()
_state = {"busy": "", "message": ""}  # what the dashboard itself is doing (drawing, starting, ...)


# ---------- settings and processes
def load_settings() -> dict:
    try:
        return {**DEFAULTS, **json.loads(SETTINGS.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_settings(s: dict):
    DATA.mkdir(exist_ok=True)
    SETTINGS.write_text(json.dumps(s, indent=1), encoding="utf-8")


def _ps(command: str) -> str:
    return subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout


def bot_running() -> bool:
    out = _ps("@(Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
              "Where-Object { $_.CommandLine -like '*-m stsbot --play*' }).Count")
    try:
        return int(out.strip() or 0) > 0
    except ValueError:
        return False


def stop_bot():
    _ps("Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*-m stsbot --play*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    time.sleep(0.8)


def start_bot():
    if bot_running():
        return
    s = load_settings()
    LOGS.mkdir(exist_ok=True)
    args = [sys.executable, "-u", "-m", "stsbot", "--play", "--still", str(s["still"])]
    if s.get("runs"):
        args += ["--runs", str(int(s["runs"]))]
    if not s.get("draw", True):
        args.append("--no-draw")
    if not s.get("llm", True):
        args.append("--no-llm")
    log = open(LOGS / time.strftime("dash_%Y%m%d_%H%M%S.txt"), "w", encoding="utf-8")
    subprocess.Popen(args, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                     env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def latest_log_lines(n: int = 40) -> list[str]:
    files = sorted([p for p in LOGS.glob("*.txt")], key=lambda p: p.stat().st_mtime) if LOGS.exists() else []
    if not files:
        return []
    noise = ("Creating model", "Model files", "gpu_resources", "InitGoogle", "WARNING")
    lines = files[-1].read_text(encoding="utf-8", errors="replace").splitlines()
    return [l for l in lines if l.strip() and not any(x in l for x in noise)][-n:]


# ---------- drawing
def _draw(name: str | None):
    from . import inputs
    from .mapdraw import IMAGES, draw_on_map, pick_picture
    from .ocr import Ocr
    from .screen import screen_kind
    from .window import find_game, grab, user32

    was_running = bot_running()
    try:
        if was_running:
            _state["message"] = "stopping the bot to draw"
            stop_bot()
        win = find_game()
        if win is None:
            raise RuntimeError("Slay the Spire 2 is not running")
        user32.SetForegroundWindow(win.hwnd)
        time.sleep(0.4)
        pic = (IMAGES / name) if name else pick_picture([])
        if pic is None or not pic.exists():
            raise RuntimeError("no picture to draw (the images folder is empty?)")
        img = grab(win)
        H, W = img.shape[:2]
        opened = False
        if screen_kind(Ocr().read(img), W, H) != "map":
            _state["message"] = "opening the map"
            inputs.click(win, 0.886, 0.035)  # the map icon, top right
            time.sleep(1.2)
            opened = True
        _state["message"] = f"drawing {pic.name}"
        n = draw_on_map(win, inputs, pic)
        if opened:
            inputs.key(win, "esc")
        _state["message"] = f"drew {pic.name} ({n} strokes)"
    except Exception as e:  # shown on the page
        _state["message"] = f"drawing failed: {e}"
    finally:
        if was_running:
            start_bot()
        _state["busy"] = ""


# ---------- API
class SettingsIn(BaseModel):
    draw: bool
    still: float
    runs: int | None = None
    llm: bool = True


class DrawIn(BaseModel):
    name: str | None = None  # None: a random picture


@app.get("/api/status")
def status():
    from .builds import deck_builds
    from .run import Run

    r = Run.load()
    return {
        "running": bot_running(),
        "busy": _state["busy"],
        "message": _state["message"],
        "hp": r.hp, "max_hp": r.max_hp, "floor": r.floor, "ascension": r.ascension, "gold": r.gold,
        "deck": [c.name for c in r.deck.cards],
        "build": deck_builds(r.deck.cards).describe(),
        "llm_build": r.build + (f" (committed on floor {r.build_floor})" if r.build_floor else ""),
        "settings": load_settings(),
        "log": latest_log_lines(),
    }


@app.get("/api/llm")
def api_llm():
    """The LLM's call in progress (its answer as it streams in) and its recent calls, newest first."""
    from .llm import HISTORY_FILE, LIVE_FILE
    live = None
    try:
        live = json.loads(LIVE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    history = []
    try:
        for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines()[-30:]:
            try:
                history.append(json.loads(line))
            except ValueError:
                pass
    except OSError:
        pass
    return {"live": live, "history": history[::-1]}


@app.get("/api/lessons")
def api_lessons():
    """The rules learned from past runs (they go into the prompts) and the latest run's lessons."""
    from .review import LESSONS_FILE, learned_rules
    latest = ""
    try:
        text = LESSONS_FILE.read_text(encoding="utf-8")
        latest = "## " + text.split("\n## ")[-1] if "\n## " in text else ""
    except OSError:
        pass
    return {"rules": learned_rules(), "latest": latest.strip()}


@app.post("/api/start")
def api_start():
    with _lock:
        start_bot()
    return {"ok": True}


@app.post("/api/stop")
def api_stop():
    with _lock:
        stop_bot()
    return {"ok": True}


@app.post("/api/settings")
def api_settings(s: SettingsIn):
    save_settings({"draw": s.draw, "still": max(1.0, s.still), "runs": s.runs, "llm": s.llm})
    return {"ok": True, "note": "used the next time the bot starts"}


@app.get("/api/images")
def api_images():
    from .mapdraw import pictures
    return [p.name for p in pictures()]


@app.get("/images/{name}")
def image(name: str):
    from .mapdraw import IMAGES
    p = (IMAGES / name).resolve()
    if p.parent != IMAGES.resolve() or not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


@app.post("/api/draw")
def api_draw(d: DrawIn):
    if _state["busy"]:
        raise HTTPException(409, f"busy: {_state['busy']}")
    _state["busy"] = "drawing"
    threading.Thread(target=_draw, args=(d.name,), daemon=True).start()
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def page():
    return (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")


def main():
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")  # this PC only


if __name__ == "__main__":
    main()
