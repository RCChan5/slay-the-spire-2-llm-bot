"""Screen reader checks on saved screenshots (run: python -m tests.test_screen). Skips shots that are missing."""

import sys
from pathlib import Path

import cv2

from stsbot.ocr import Ocr
from stsbot.screen import read_combat, screen_kind

SHOTS = Path(__file__).resolve().parent.parent / "shots"
CASES = {
    "fight2.png": dict(kind="combat", hp=64, energy=3, block=0, hand=["Strike", "Strike", "Strike", "Bash", "Defend"],
                       costs=[1, 1, 1, 2, 1], enemies=[(39, 39)]),
    "after_bash.png": dict(kind="combat", hp=64, energy=1, block=0, hand=["Strike", "Strike", "Strike", "Defend"],
                           enemies=[(31, 39)]),
    "after_defend.png": dict(kind="combat", hp=64, energy=0, block=5, hand=["Strike", "Strike", "Strike"],
                             enemies=[(31, 39)]),
    "map1b.png": dict(kind="map"),
    "first.png": dict(kind="main_menu"),
    "now1.png": dict(kind="main_menu"),  # with Continue
    "menu2.png": dict(kind="mode_select"),
    "charsel.png": dict(kind="char_select"),
    "run1b.png": dict(kind="neow"),
    "neow3.png": dict(kind="proceed"),
    "cards1.png": dict(kind="card_choice"),
    "reward1.png": dict(kind="loot"),
    "gameover1.png": dict(kind="game_over"),
}

ocr = Ocr()
passed = failed = 0


def check(name, what, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {what}: got {got!r}, want {want!r}")


for shot, want in CASES.items():
    p = SHOTS / shot
    if not p.exists():
        print(f"skip {shot} (not saved)")
        continue
    img = cv2.imread(str(p))
    H, W = img.shape[:2]
    lines = ocr.read(img)
    check(shot, "kind", screen_kind(lines, W, H), want["kind"])
    if want["kind"] != "combat":
        continue
    c = read_combat(lines, W, H)
    if c is None:
        check(shot, "combat read", None, "a state")
        continue
    check(shot, "hp", c.hp, want["hp"])
    check(shot, "energy", c.energy, want["energy"])
    check(shot, "block", c.block, want["block"])
    check(shot, "hand", [x.name for x in c.hand], want["hand"])
    if "costs" in want:
        check(shot, "costs", [x.cost for x in c.hand], want["costs"])
    check(shot, "enemies", [(e.hp, e.max_hp) for e in c.enemies], want["enemies"])

# Event options (the layout events use: option boxes on the right, gold title over effect text).
from stsbot.events import best_option, read_options  # noqa: E402

for shot, want in {"menuX.png": "Nab the Map", "ev1b.png": "Share Knowledge"}.items():
    p = SHOTS / shot
    if not p.exists():
        print(f"skip {shot} (not saved)")
        continue
    img = cv2.imread(str(p))
    H, W = img.shape[:2]
    opts = read_options(ocr.read(img), W, H, (0.47, 0.92, 0.53, 0.95))
    i, _ = best_option(opts, 56, 80)
    check(shot, "event pick", opts[i].title if i is not None else None, want)

print(f"test_screen: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
