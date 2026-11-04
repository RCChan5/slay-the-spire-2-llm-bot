"""Map drawing helpers (run: python -m tests.test_mapdraw)."""

import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

import stsbot.mapdraw as md

passed = failed = 0


def check(what, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


# Random pick from images/ without repeats until all are used.
with tempfile.TemporaryDirectory() as d:
    md.IMAGES = Path(d)
    for name in ("a.png", "b.png", "c.png"):
        cv2.imwrite(str(Path(d) / name), np.full((50, 40, 3), 200, np.uint8))
    used = []
    for _ in range(3):
        used.append(md.pick_picture(used).name)
    check("no repeats until all used", sorted(used), ["a.png", "b.png", "c.png"])
    check("then any picture again", md.pick_picture(used).name in used, True)
    md.IMAGES = Path(d) / "missing"
    check("no folder -> no picture", md.pick_picture([]), None)

# The flag only for pictures with "flag" in the name.
with tempfile.TemporaryDirectory() as d:
    img = np.full((300, 220, 3), 230, np.uint8)
    cv2.circle(img, (110, 110), 60, (40, 40, 40), -1)
    plain, flagged = Path(d) / "plain.png", Path(d) / "x_flag.png"
    cv2.imwrite(str(plain), img)
    cv2.imwrite(str(flagged), img)
    check("flag adds strokes", len(md.strokes_from_picture(flagged)) > len(md.strokes_from_picture(plain)), True)
    check("plain outline by default (no hatching)",
          len(md.strokes_from_picture(plain)) < len(md.strokes_from_picture(plain, detail=True)), True)

print(f"test_mapdraw: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
