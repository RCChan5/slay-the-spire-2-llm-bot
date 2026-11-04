"""Start the bot in this window with the dashboard's saved settings (python -m tools.start).

Stops any copy already running, checks that Ollama answers (without it the built-in rules play), then
runs the bot here so its log scrolls in this window. Ctrl+C stops it.
"""

import subprocess
import sys
import urllib.request

from stsbot.dashboard import load_settings


def main():
    subprocess.run([sys.executable, "-m", "tools.stop"])
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
    print("starting:", " ".join(args[2:]))
    try:
        sys.exit(subprocess.call(args))
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
