"""Calibration helper: click a point (fractions of the window), wait, save a screenshot.

    python -m tools.poke click 0.40 0.66 name     # left click, then shots/name.png
    python -m tools.poke key esc name
    python -m tools.poke front                    # bring the game to the front
"""

import sys
import time
from pathlib import Path

import cv2

from stsbot import inputs
from stsbot.window import find_game, grab, user32

win = find_game()
if win is None:
    sys.exit("Slay the Spire 2 is not running.")
cmd = sys.argv[1]
if cmd == "front":
    user32.SetForegroundWindow(win.hwnd)
    time.sleep(0.3)
    print("in front:", inputs.is_foreground(win))
    sys.exit()
if cmd == "click":
    inputs.click(win, float(sys.argv[2]), float(sys.argv[3]))
    name = sys.argv[4] if len(sys.argv) > 4 else "poke"
elif cmd == "rclick":
    inputs.click(win, float(sys.argv[2]), float(sys.argv[3]), right=True)
    name = sys.argv[4] if len(sys.argv) > 4 else "poke"
elif cmd == "key":
    inputs.key(win, sys.argv[2])
    name = sys.argv[3] if len(sys.argv) > 3 else "poke"
time.sleep(1.5)
out = Path(__file__).resolve().parent.parent / "shots"
out.mkdir(exist_ok=True)
cv2.imwrite(str(out / f"{name}.png"), grab(win))
print("saved", name)
