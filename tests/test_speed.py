"""The speed helpers with fake frames (run: python -m tests.test_speed): the hover wait and the icons
remembered as unnamed for the fight."""

import sys
import time

import numpy as np

from stsbot.bot import Bot
from stsbot.status import StatusBook

passed = failed = 0


def check(what, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


class FakeScreen:
    """Frames that change at `change_at` seconds and settle at `settle_at`."""

    def __init__(self, change_at, settle_at):
        self.t0 = time.time()
        self.change_at, self.settle_at = change_at, settle_at

    def __call__(self):
        t = time.time() - self.t0
        img = np.zeros((180, 320, 3), np.uint8)
        if t >= self.settle_at:
            img[:] = 200
        elif t >= self.change_at:
            img[:] = 60 + int((t - self.change_at) * 1000) % 120  # moving
        return img


b = Bot.__new__(Bot)
b.frame = FakeScreen(0.15, 0.3)
t = time.time()
b.hover_wait((0, 1, 0, 1), timeout=1.5)
took = time.time() - t
check("waits for the change and returns once still (not the full timeout)", 0.3 <= took < 0.7, True)

b.frame = FakeScreen(9, 9)  # nothing ever changes
t = time.time()
b.hover_wait((0, 1, 0, 1), timeout=0.5)
check("no change: gives up at the timeout", 0.45 <= time.time() - t < 0.8, True)

book = StatusBook()
book.icons = {}
img = np.random.default_rng(1).integers(0, 255, (1440, 2560, 3), dtype=np.uint8)
check("an icon not seen yet is not unknown", book.is_unknown(img, 0.3, 0.74), False)
book.mark_unknown(img, 0.3, 0.74)
check("an unnamed icon is remembered", book.is_unknown(img, 0.3, 0.74), True)
check("a different icon is not taken for it", book.is_unknown(img, 0.6, 0.74), False)

print(f"test_speed: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
