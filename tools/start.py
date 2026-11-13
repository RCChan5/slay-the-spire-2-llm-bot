"""Start the bot in this window with the dashboard's saved settings (python -m tools.start).

Stops any copy already running, starts the dashboard in the background if it is not up yet and opens it
in the browser, checks that Ollama answers (without it the built-in rules play), then runs the bot here so
its log scrolls in this window. Ctrl+C stops the bot; the dashboard keeps running.
"""

import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from stsbot.dashboard import PORT, load_settings

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = f"http://localhost:{PORT}"


def dashboard_up() -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/llm", timeout=2).read()
        return True
    except OSError:
        return False


def open_dashboard():
    """Start the dashboard in the background (no window) if needed, then open it in the browser."""
    if not dashboard_up():
        (ROOT / "logs").mkdir(exist_ok=True)
        log = open(ROOT / "logs" / "dashboard_server.txt", "w", encoding="utf-8")
        subprocess.Popen([sys.executable, "-m", "stsbot.dashboard"], cwd=str(ROOT), stdout=log,
                         stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                         | getattr(subprocess, "DETACHED_PROCESS", 0))
        for _ in range(40):
            time.sleep(0.25)
            if dashboard_up():
                break
        else:
            print("the dashboard did not start (see logs/dashboard_server.txt); the bot starts anyway")
            return
    webbrowser.open(DASHBOARD)
    print("dashboard:", DASHBOARD)


def main():
    subprocess.run([sys.executable, "-m", "tools.stop"])
    open_dashboard()
    s = load_settings()
    if s.get("llm", True):
        try:
            urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3).read()
        except OSError:
            print("Ollama is not answering: the built-in rules will play until it does (open the Ollama app).")
    args = [sys.executable, "-u", "-m", "stsbot", "--play", "--still", str(s["still"])]
    if s.get("runs"):  # none or 0 on the dashboard: keep starting new runs
        args += ["--runs", str(int(s["runs"]))]
    if not s.get("draw", True):
        args.append("--no-draw")
    if not s.get("llm", True):
        args.append("--no-llm")
    if s.get("mapping") in ("plan", "random", "teammates", "off"):
        args += ["--mapping", s["mapping"]]
    if not s.get("route_line", True):
        args.append("--no-route-line")
    print("starting:", " ".join(args[2:]))
    try:
        sys.exit(subprocess.call(args))
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
