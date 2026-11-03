"""Print every OCR line of a screenshot with its box as fractions of the image.

    python -m tools.ocrdump shots/fight1.png
"""

import sys
import time

import cv2

from stsbot.ocr import Ocr

img = cv2.imread(sys.argv[1])
H, W = img.shape[:2]
ocr = Ocr()
ocr.read(img[:64, :64])  # load models before timing
t = time.perf_counter()
lines = ocr.read(img)
print(f"{len(lines)} lines in {time.perf_counter() - t:.2f}s")
for l in lines:
    x, y, w, h = l.box
    print(f"{l.confidence:.2f}  ({x / W:.3f},{y / H:.3f} {w / W:.3f}x{h / H:.3f})  {l.text}")
