"""Read a game screen from OCR lines: which screen it is, and for combat the full state.

All positions are fractions of the window (measured at 2562x1440, 16:9), so other 16:9 sizes work too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cards import Effects
from .ocr import Line

FRAC = re.compile(r"^(\d{1,3})\s*/\s*(\d{1,3})$")
DIGITS = re.compile(r"^\d{1,3}$")
INTENT = re.compile(r"^(\d{1,3})\s*(?:[xX×]\s*(\d{1,2}))?$")
NOT_CARD_NAMES = {"end", "turn", "attack", "skill", "power", "curse", "status", "enemy"}


@dataclass
class Card:
    name: str
    cost: int | None
    x: float  # name's center, fractions of the window
    y: float
    effects: Effects | None = None

    @property
    def grab_point(self) -> tuple[float, float]:
        """Where to press to pick the card up: on its art, below the name."""
        return self.x, min(0.97, self.y + 0.07)


@dataclass
class Enemy:
    hp: int
    max_hp: int
    x: float  # health bar center
    y: float
    intent_damage: int = 0
    intent_hits: int = 1
    intent_text: str = ""

    @property
    def body_point(self) -> tuple[float, float]:
        return self.x, max(0.2, self.y - 0.12)

    @property
    def incoming(self) -> int:
        return self.intent_damage * self.intent_hits


@dataclass
class Combat:
    hp: int
    max_hp: int
    block: int
    energy: int
    max_energy: int
    turn: int
    hand: list[Card] = field(default_factory=list)
    enemies: list[Enemy] = field(default_factory=list)
    player_x: float = 0.25

    def summary(self) -> str:
        hand = ", ".join(f"{c.name}({c.cost})" for c in self.hand)
        foes = "; ".join(f"{e.hp}/{e.max_hp} intent {e.intent_damage}x{e.intent_hits}" for e in self.enemies)
        return (f"turn {self.turn}  HP {self.hp}/{self.max_hp} block {self.block}  energy {self.energy}/"
                f"{self.max_energy}  hand [{hand}]  enemies [{foes}]")


def _frac(lines: list[Line], W: int, H: int):
    for l in lines:
        cx, cy = l.center
        yield l, cx / W, cy / H


def screen_kind(lines: list[Line], W: int, H: int) -> str:
    texts = " | ".join(l.text for l in lines).lower()
    corner = " ".join(l.text for l, fx, fy in _frac(lines, W, H) if fx > 0.8 and 0.76 < fy < 0.88).lower()
    if re.search(r"\bend\b", corner) and "turn" in corner:
        return "combat"
    if "enemy" in corner or re.search(r"enemy turn", texts):
        return "enemy_turn"
    if "legend" in texts and "unknown" in texts:
        return "map"
    if "singleplayer" in texts and "compendium" in texts:
        return "main_menu"
    if re.search(r"\breward", texts):
        return "reward"
    if re.search(r"\bproceed\b", texts):
        return "proceed"
    return "unknown"


def read_combat(lines: list[Line], W: int, H: int) -> Combat | None:
    hp = max_hp = energy = max_energy = None
    turn = 0
    bars: list[tuple[int, int, float, float]] = []
    digits: list[tuple[int, float, float]] = []
    names: list[tuple[str, float, float]] = []
    for l, fx, fy in _frac(lines, W, H):
        t = l.text.strip()
        m = FRAC.match(t)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if fy < 0.06 and fx < 0.2 and hp is None:
                hp, max_hp = a, b  # top bar
            elif 0.74 < fy < 0.88 and fx < 0.14:
                energy, max_energy = a, b  # energy orb
            elif 0.55 < fy < 0.78:
                bars.append((a, b, fx, fy))
            continue
        mt = re.match(r"^(?:End\s*)?Turn\s*(\d+)", t, re.I)
        if mt and fx > 0.8:
            turn = int(mt.group(1))
            continue
        if fx > 0.8 and 0.76 < fy < 0.88:
            if DIGITS.match(t):
                turn = int(t)  # the turn number read apart from "End Turn"
            continue
        if DIGITS.match(t) or INTENT.match(t):
            digits.append((t, fx, fy))
            continue
        if 0.76 < fy < 0.93 and 0.18 < fx < 0.84 and re.match(r"^[A-Za-z][A-Za-z' \-]*\+?$", t):
            if t.lower() not in NOT_CARD_NAMES:
                names.append((t, fx, fy))
    if energy is None or hp is None:
        return None

    # Player's bar is the leftmost health bar; enemies are the rest.
    bars.sort(key=lambda b: b[2])
    player_x = 0.25
    enemies: list[Enemy] = []
    if bars and bars[0][2] < 0.45:
        player_x = bars[0][2]
        bars = bars[1:]
    for a, b, fx, fy in bars:
        enemies.append(Enemy(a, b, fx, fy))

    block = 0
    for t, fx, fy in digits:
        if DIGITS.match(t) and abs(fy - 0.698) < 0.03 and player_x - 0.13 < fx < player_x - 0.04:
            block = int(t)

    # Intent numbers sit above each enemy, next to the intent icon.
    for e in enemies:
        best = None
        for t, fx, fy in digits:
            m = INTENT.match(t)
            if m and abs(fx - e.x) < 0.07 and 0.12 < fy < e.y - 0.08:
                if best is None or fy > best[2]:
                    best = (m, fx, fy)
        if best:
            e.intent_damage = int(best[0].group(1))
            e.intent_hits = int(best[0].group(2) or 1)

    # Cards: each name with the cost gem just left of it and a little higher.
    hand: list[Card] = []
    for name, fx, fy in sorted(names, key=lambda n: n[1]):
        cost = None
        best_d = 9.0
        for t, dx, dy in digits:
            if DIGITS.match(t) and -0.09 < dx - fx < -0.01 and -0.05 < dy - fy < 0.04 and dy > 0.74:
                d = abs(dx - fx) + abs(dy - fy)
                if d < best_d:
                    best_d, cost = d, int(t)
        hand.append(Card(name, cost, fx, fy))
    return Combat(hp, max_hp, block, energy, max_energy, turn, hand, enemies, player_x)
