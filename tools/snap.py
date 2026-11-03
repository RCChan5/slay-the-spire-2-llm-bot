"""Save a screenshot of the game window to shots/ (for calibrating screen readers).

    python -m tools.snap [name]
"""

import sys
import time
from pathlib import Path

import cv2

from stsbot.window import find_game, grab

win = find_game()
if win is None:
    sys.exit("Slay the Spire 2 is not running.")
out = Path(__file__).resolve().parent.parent / "shots"
out.mkdir(exist_ok=True)
name = sys.argv[1] if len(sys.argv) > 1 else time.strftime("%Y%m%d_%H%M%S")
path = out / f"{name}.png"
cv2.imwrite(str(path), grab(win))
print(f"{win.title!r} {win.width}x{win.height} at ({win.left},{win.top}) -> {path}")
