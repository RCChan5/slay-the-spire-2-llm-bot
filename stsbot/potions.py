"""Potions: read the belt, and decide when to use one.

Rules (the user's): keep one slot open. When every slot is full, use the potion that helps most in this
fight, so the next potion reward has room. In an emergency (the coming attacks would kill even after the
best plays) use whatever potion helps, full belt or not.

Using a potion: click its slot, then the first button of the menu (Throw or Drink); a potion aimed at one
enemy is then dropped on that enemy.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .cards import Effects, parse

SLOT_X = (0.276, 0.3085, 0.341)  # belt slots, fractions of the window (measured at 2562x1440)
SLOT_Y = 0.0356
MENU_FIRST_DY = 0.14  # the menu's first button (Throw / Drink) sits this far below the slot


@dataclass
class Potion:
    slot: int
    x: float
    name: str = ""
    text: str = ""
    effects: Effects | None = None

    @property
    def use_point(self) -> tuple[float, float]:
        return self.x, SLOT_Y + MENU_FIRST_DY


def slot_count(ascension: int) -> int:
    return 2 if ascension >= 4 else 3  # A4 Tight Belt: one fewer slot


def filled_slots(img: np.ndarray, ascension: int) -> list[int]:
    """Indexes of slots that hold a potion (a colored icon; an empty slot is a grey outline)."""
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    out = []
    for i, fx in enumerate(SLOT_X[:slot_count(ascension)]):
        cx, cy, r = int(fx * W), int(SLOT_Y * H), int(0.011 * W)
        patch = hsv[cy - r:cy + r, cx - r:cx + r]
        if float(((patch[..., 1] > 90) & (patch[..., 2] > 90)).mean()) > 0.08:
            out.append(i)
    return out


def from_tooltip(slot: int, text: str) -> Potion:
    """Tooltip text is the name, then the effect."""
    words = text.split()
    # The name is the leading words up to the first effect verb.
    verbs = {"deal", "gain", "apply", "draw", "heal", "add", "upgrade", "lose", "play", "choose", "at", "the", "your"}
    cut = next((k for k, w in enumerate(words) if w.lower() in verbs), len(words))
    name, effect = " ".join(words[:cut]), " ".join(words[cut:])
    p = Potion(slot, SLOT_X[slot], name, effect)
    p.effects = parse(effect, "Potion")
    return p


def potion_value(p: Potion, incoming: int, block: int, hp: int, max_hp: int, foes_alive: int,
                 lowest_foe_hp: int) -> float:
    """How much using this potion now helps."""
    e = p.effects
    if e is None:
        return 0.0
    v = 0.0
    if e.damage:
        dmg = e.damage * e.hits * (foes_alive if e.all_enemies else 1)
        v += dmg * 0.8
        if e.damage * e.hits >= lowest_foe_hp:
            v += 8  # finishes an enemy
    if e.block:
        v += min(e.block, max(0, incoming - block)) * 1.4
    v += 4 * e.strength + 2 * e.vulnerable + 2 * e.weak + 1.5 * e.draw + 3 * e.energy
    heal = 0
    import re
    m = re.search(r"Heal\s*(\d+)", p.text, re.I)
    if m:
        heal = min(int(m.group(1)), max_hp - hp)
        v += heal * (1.2 if hp < 0.5 * max_hp else 0.3)
    return v


@dataclass
class PotionChoice:
    potion: Potion | None
    target: int | None
    why: str


def choose_potion(potions: list[Potion], slots: int, incoming: int, block_after: int, hp: int, max_hp: int,
                  enemies_hp: list[int]) -> PotionChoice:
    """Which potion to use now, if any. block_after: block once the planned cards are played."""
    if not potions:
        return PotionChoice(None, None, "")
    alive = [i for i, h in enumerate(enemies_hp) if h > 0]
    if not alive:
        return PotionChoice(None, None, "")
    lowest = min(alive, key=lambda i: enemies_hp[i])
    full = len(potions) >= slots
    taken = max(0, incoming - block_after)
    emergency = taken >= hp
    if not (full or emergency):
        return PotionChoice(None, None, "")
    vals = [(potion_value(p, incoming, block_after, hp, max_hp, len(alive), enemies_hp[lowest]), p) for p in potions]
    vals.sort(key=lambda t: -t[0])
    v, best = vals[0]
    if v <= 0.5:
        return PotionChoice(None, None, "no potion helps right now")
    e = best.effects
    target = lowest if (e and e.needs_target) else None
    why = ("emergency: would take " + str(taken) + " with " + str(hp) + " HP") if emergency else \
        f"belt full ({len(potions)}/{slots}): keeping one slot open"
    return PotionChoice(best, target, f"{why}; use {best.name or 'potion'} ({best.text})")
