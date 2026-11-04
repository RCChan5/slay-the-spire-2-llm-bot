"""Draw a picture on the open map once (a test), then save a screenshot.

    python -m tools.drawtest [images/file.jpg] [--low]   # default: a random picture; --low: the map's lower half
"""

import sys
import time
from pathlib import Path

import cv2

from stsbot import inputs
from stsbot.mapdraw import draw_on_map, pick_picture
from stsbot.window import find_game, grab, user32


def main():
    win = find_game()
    user32.SetForegroundWindow(win.hwnd)
    time.sleep(0.3)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    pic = Path(args[0]) if args else pick_picture([])
    box = (0.22, 0.6, 0.78, 0.98) if "--low" in sys.argv else None
    t = time.time()
    n = draw_on_map(win, inputs, pic, box=box) if box else draw_on_map(win, inputs, pic)
    inputs.move(win, 0.9, 0.5)
    time.sleep(0.5)
    cv2.imwrite("shots/drawn.png", grab(win))
    print(f"drew {n} strokes of {pic.name} in {time.time() - t:.0f} s; screenshot shots/drawn.png")


if __name__ == "__main__":
    main()
