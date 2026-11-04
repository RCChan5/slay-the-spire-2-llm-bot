"""Status icons (Vulnerable, Weak, Strength, ...) under the health bars.

Each status shows as a small icon with its stack count. The first time an icon is seen, the bot hovers
it and reads the name from the tooltip, then keeps a picture of the icon in data/status_icons/. Later
the icon is recognized from that picture alone, without hovering.
"""

from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "data" / "status_icons"

KNOWN = ["Vulnerable", "Weak", "Strength", "Dexterity", "Frail", "Artifact", "Ritual", "Thorns", "Metallicize",
         "Plated Armor", "Poison", "Regen", "Intangible", "Barricade", "Shrink", "Shrunk", "Enrage", "Curl Up",
         "Angry", "Sharp Hide", "Spore Cloud", "Slow", "Constrict", "Entangled", "No Draw", "Hex", "Rage"]

# Icon position relative to its stack number, and sizes, as fractions of the window.
ICON_DX, ICON_DY = -0.009, -0.012
HALF_W, HALF_H = 0.009, 0.013  # the saved picture
PAD_W, PAD_H = 0.008, 0.012  # extra room when searching for it


def icon_center(dx: float, dy: float) -> tuple[float, float]:
    return dx + ICON_DX, dy + ICON_DY


def _crop(img: np.ndarray, cx: float, cy: float, hw: float, hh: float) -> np.ndarray:
    H, W = img.shape[:2]
    x0, x1 = int(max(0, (cx - hw) * W)), int(min(W, (cx + hw) * W))
    y0, y1 = int(max(0, (cy - hh) * H)), int(min(H, (cy + hh) * H))
    return img[y0:y1, x0:x1]


def name_from_tooltip(text: str) -> str | None:
    for k in sorted(KNOWN, key=len, reverse=True):
        if re.search(rf"\b{re.escape(k)}\b", text, re.I):
            return k
    return None


class StatusBook:
    def __init__(self):
        self.icons: dict[str, list[np.ndarray]] = {}
        self.unknown: list[np.ndarray] = []  # icons with no name this fight (cleared between fights)
        if ICONS.exists():
            for p in ICONS.glob("*.png"):
                name = p.stem.split("__")[0].replace("_", " ")
                img = cv2.imread(str(p))
                if img is not None:
                    self.icons.setdefault(name, []).append(img)

    def identify(self, img: np.ndarray, dx: float, dy: float, min_score: float = 0.8) -> str | None:
        """The status whose saved icon best matches the icon beside the stack number at (dx, dy)."""
        cx, cy = icon_center(dx, dy)
        window = _crop(img, cx, cy, HALF_W + PAD_W, HALF_H + PAD_H)
        best, best_s = None, min_score
        for name, temps in self.icons.items():
            for t in temps:
                if t.shape[0] > window.shape[0] or t.shape[1] > window.shape[1]:
                    t = cv2.resize(t, (min(t.shape[1], window.shape[1]), min(t.shape[0], window.shape[0])))
                s = float(cv2.matchTemplate(window, t, cv2.TM_CCOEFF_NORMED).max())
                if s > best_s:
                    best, best_s = name, s
        return best

    def mark_unknown(self, img: np.ndarray, dx: float, dy: float):
        """An icon whose tooltip gave no name (a teammate's power in multiplayer, say): remembered for this
        fight so it is not hovered again after every card."""
        cx, cy = icon_center(dx, dy)
        self.unknown.append(_crop(img, cx, cy, HALF_W, HALF_H))

    def is_unknown(self, img: np.ndarray, dx: float, dy: float, min_score: float = 0.8) -> bool:
        if not self.unknown:
            return False
        cx, cy = icon_center(dx, dy)
        window = _crop(img, cx, cy, HALF_W + PAD_W, HALF_H + PAD_H)
        for t in self.unknown:
            if t.size == 0 or t.shape[0] > window.shape[0] or t.shape[1] > window.shape[1]:
                continue
            if float(cv2.matchTemplate(window, t, cv2.TM_CCOEFF_NORMED).max()) > min_score:
                return True
        return False

    def learn(self, name: str, img: np.ndarray, dx: float, dy: float):
        cx, cy = icon_center(dx, dy)
        pic = _crop(img, cx, cy, HALF_W, HALF_H)
        ICONS.mkdir(parents=True, exist_ok=True)
        n = len(self.icons.get(name, []))
        cv2.imwrite(str(ICONS / f"{name.replace(' ', '_')}__{n}.png"), pic)
        self.icons.setdefault(name, []).append(pic)


def red_icon(img: np.ndarray, nx: float, ny: float) -> bool:
    """Is the intent icon next to this number red (an attack)? Used when hovering is not allowed."""
    region = _crop(img, nx + 0.018, ny - 0.015, 0.016, 0.02).astype(np.int32)
    if region.size == 0:
        return False
    b, g, r = region[..., 0], region[..., 1], region[..., 2]
    red = (r > 150) & (r > g + 60) & (r > b + 60)
    return float(red.mean()) > 0.08
