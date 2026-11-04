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
# First words of card text: when a card is raised its text can land where names are read.
TEXT_WORDS = {"deal", "deals", "gain", "apply", "draw", "exhaust", "lose", "whenever", "play", "add", "upgrade"}


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
    intent_pos: tuple[float, float] | None = None  # the intent number, if any
    intent_attack: bool | None = None  # None until the icon or tooltip says
    block: int = 0
    statuses: dict[str, int] = field(default_factory=dict)
    status_slots: list[tuple[float, float, int]] = field(default_factory=list)  # stack number x, y, count

    @property
    def body_point(self) -> tuple[float, float]:
        # Just above the health bar is on the body of every enemy, small or tall.
        return self.x, self.y - 0.07

    @property
    def drop_points(self) -> list[tuple[float, float]]:
        """Where to release a targeted card, best first; the next ones are tried if a drop misses."""
        return [self.body_point, (self.x, self.y - 0.035), (self.x, self.y - 0.14), (self.x, self.y - 0.22)]

    @property
    def incoming(self) -> int:
        if self.intent_attack is False:
            return 0
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
    statuses: dict[str, int] = field(default_factory=dict)
    status_slots: list[tuple[float, float, int]] = field(default_factory=list)

    def summary(self) -> str:
        hand = ", ".join(f"{c.name}({c.cost})" for c in self.hand)

        def st(d):
            return (" " + ",".join(f"{k} {v}" for k, v in d.items())) if d else ""

        foes = "; ".join(f"{e.hp}/{e.max_hp}" + (f" block {e.block}" if e.block else "") + st(e.statuses)
                         + f" intent {e.incoming}" + (f"={e.intent_damage}x{e.intent_hits}" if e.intent_hits > 1 else "")
                         + ("" if e.intent_attack is not False or not e.intent_pos else " (not an attack)")
                         for e in self.enemies)
        return (f"turn {self.turn}  HP {self.hp}/{self.max_hp} block {self.block}{st(self.statuses)}  energy "
                f"{self.energy}/{self.max_energy}  hand [{hand}]  enemies [{foes}]")


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
    if re.search(r"what\s*shall", texts):  # "What shall I do?" (OCR sometimes drops the I)
        return "campfire"
    if "card to upgrade" in texts:
        return "upgrade_select"
    if "card to remove" in texts:  # before "choose a card": this one takes a card away
        return "remove_select"
    if "choose a card" in texts:
        return "card_choice"
    if "loot!" in texts or texts.startswith("loot") or " | loot" in texts:
        return "loot"
    if "legend" in texts and "unknown" in texts:
        return "map"
    if "compendium" in texts and ("singleplayer" in texts or "continue" in texts):
        return "main_menu"
    if "standard" in texts and "daily" in texts and "custom" in texts:
        return "mode_select"
    words = {l.text.strip().lower() for l in lines}
    if words & {"ironclad", "silent", "defect", "regent", "necrobinder", "the ironclad", "the silent",
                "the defect", "the regent", "the necrobinder"}:  # the big name, read as one or two lines
        return "char_select"
    if re.search(r"\b(vanquished|consciousness fades|defeat|victory|game over|you died|slain)\b", texts):
        return "game_over"
    if "neow" in texts and not re.search(r"\bproceed\b", texts):
        return "neow"
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
        if 0.76 < fy < 0.93 and 0.18 < fx < 0.84 and re.match(r"^[A-Za-z][A-Za-z' !\-]{2,}\+?$", t):
            if t.lower() not in NOT_CARD_NAMES and t.split()[0].lower() not in TEXT_WORDS:
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
    player_slots: list[tuple[float, float, int]] = []
    for t, fx, fy in digits:
        if DIGITS.match(t) and abs(fy - 0.698) < 0.03 and player_x - 0.13 < fx < player_x - 0.04:
            block = int(t)
        elif DIGITS.match(t) and 0.712 < fy < 0.765 and abs(fx - player_x) < 0.1:
            player_slots.append((fx, fy, int(t)))

    # Enemy block (shield number left of the bar) and status stacks (small numbers under it).
    for t, fx, fy in digits:
        if not DIGITS.match(t) or not enemies:
            continue
        e = min(enemies, key=lambda e: abs(e.x - fx))
        if abs(fy - e.y) < 0.02 and e.x - 0.12 < fx < e.x - 0.035:
            e.block = int(t)
        elif 0.712 < fy < 0.765 and abs(fx - e.x) < 0.1:
            e.status_slots.append((fx, fy, int(t)))

    assign_intents(enemies, digits)

    # Cards: each name with the cost gem just left of it and a little higher.
    # A two-word name can come back as two words side by side ("Battle", "Trance"): join them.
    names.sort(key=lambda n: n[1])
    joined: list[tuple[str, float, float]] = []
    for name, fx, fy in names:
        if joined and fx - joined[-1][1] < 0.045 and abs(fy - joined[-1][2]) < 0.02:
            pn, px, py = joined[-1]
            joined[-1] = (f"{pn} {name}", (px + fx) / 2, (py + fy) / 2)
        else:
            joined.append((name, fx, fy))
    names = joined
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
    # A cost gem that was not read: another copy of the card in hand tells it.
    for c in hand:
        if c.cost is None:
            c.cost = next((o.cost for o in hand if o.name == c.name and o.cost is not None), None)
    return Combat(hp, max_hp, block, energy, max_energy, turn, hand, enemies, player_x, status_slots=player_slots)


def assign_intents(enemies: list[Enemy], digits: list[tuple[str, float, float]]):
    """Intent numbers sit above each enemy, next to the intent icon. digits: (text, fx, fy)."""
    for e in enemies:
        if e.intent_pos is not None:
            continue
        best = None
        for t, fx, fy in digits:
            m = INTENT.match(t.strip())
            if m and abs(fx - e.x) < 0.07 and 0.12 < fy < e.y - 0.08:
                if best is None or fy > best[2]:
                    best = (m, fx, fy)
        if best:
            e.intent_damage = int(best[0].group(1))
            e.intent_hits = int(best[0].group(2) or 1)
            e.intent_pos = (best[1], best[2])


def parse_intent_tooltip(text: str) -> tuple[bool, int, int]:
    """(is an attack, damage per hit, hits) from an intent tooltip."""
    attack = bool(re.search(r"\battack", text, re.I))
    dmg = re.search(r"(\d+)\s*damage", text)
    hits = re.search(r"(\d+)\s*times", text)
    return attack, int(dmg.group(1)) if dmg else 0, int(hits.group(1)) if hits else 1


def join_text(lines: list[Line], H: int, tol: float = 0.009) -> str:
    """Words read apart back into reading order: rows top to bottom, words left to right."""
    rows: list[list[Line]] = []
    for l in sorted(lines, key=lambda l: l.center[1]):
        if rows and abs(l.center[1] - rows[-1][0].center[1]) <= tol * H:
            rows[-1].append(l)
        else:
            rows.append([l])
    return " ".join(" ".join(w.text for w in sorted(r, key=lambda w: w.box[0])) for r in rows)


@dataclass
class Offer:
    name: str
    cost: int | None
    kind: str
    text: str
    x: float
    y: float


def read_card_choice(lines: list[Line], W: int, H: int) -> list[Offer]:
    """The cards on a "Choose a Card" screen, left to right, with their full text."""
    title = next((l for l in lines if "choose a card" in l.text.lower()), None)
    if title is None:
        return []
    ty = title.center[1] / H
    kinds = [(l, fx, fy) for l, fx, fy in _frac(lines, W, H)
             if l.text.strip().lower() in ("attack", "skill", "power", "curse", "status")]  # title may be above or below
    offers: list[Offer] = []
    for kl, kx, ky in sorted(kinds, key=lambda k: k[1]):
        name_l = None
        cost = None
        body: list[Line] = []
        for l, fx, fy in _frac(lines, W, H):
            if l is kl or abs(fx - kx) > 0.065:
                continue
            if ky - 0.2 < fy < ky - 0.1:
                if DIGITS.match(l.text.strip()) or re.match(r"^\d\D?$", l.text.strip()):
                    cost = int(l.text.strip()[0])
                elif re.search(r"[A-Za-z]{3}", l.text):
                    name_l = l
            elif ky + 0.01 < fy < ky + 0.16 and not FRAC.match(l.text.strip()):
                body.append(l)
        if name_l is None:
            continue
        nx, ny = name_l.center
        offers.append(Offer(name_l.text.strip(), cost, kl.text.strip().capitalize(), join_text(body, H),
                            nx / W, ny / H))
    return offers
