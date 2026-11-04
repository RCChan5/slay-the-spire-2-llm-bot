"""Card effects from card text (as read off the card by OCR).

The hovered card shows its live text (Strength and upgrades already counted), so effects are parsed from
what is on screen each turn. Starter cards are known in advance in case a hover read fails.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

KNOWN_TEXT = {
    "Strike": ("Attack", "Deal 6 damage."),
    "Defend": ("Skill", "Gain 5 Block."),
    "Bash": ("Attack", "Deal 8 damage. Apply 2 Vulnerable."),
}


@dataclass
class Effects:
    kind: str = ""  # Attack, Skill, Power, Curse, Status, or "" if unknown
    damage: int = 0
    hits: int = 1
    all_enemies: bool = False
    block: int = 0
    vulnerable: int = 0
    weak: int = 0
    strength: int = 0
    enemy_strength: int = 0
    draw: int = 0
    energy: int = 0
    exhaust: bool = False
    upgrades_hand: bool = False  # "Upgrade a card in your Hand" (Armaments)
    clears_hand: int = 0  # how many cards from the hand it discards or exhausts ("Exhaust 1 card", ...)
    unplayable: bool = False
    known: bool = False  # text was read and at least one effect understood
    text: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def needs_target(self) -> bool:
        return (self.damage > 0 or self.vulnerable > 0 or self.weak > 0) and not self.all_enemies


def _num(pattern: str, text: str) -> int:
    m = re.search(pattern, text, re.I)
    return int(m.group(1)) if m else 0


def _debuff(n: int) -> int:
    """Debuff stacks on cards are small; OCR sometimes doubles a digit ("Apply 11 Vulnerable" for 1)."""
    if n > 6:
        s = str(n)
        return int(s[0]) if len(set(s)) == 1 else min(n, 6)
    return n


def clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # Common OCR slips on the game's serif font.
    text = re.sub(r"\bIdamage\b", "damage", text)
    return text.replace("Biock", "Block").replace("BIock", "Block").replace("darnage", "damage")


def parse(text: str, kind: str = "") -> Effects:
    t = clean(text)
    e = Effects(kind=kind, text=t)
    e.damage = _num(r"Deal\s*(\d+)\s*damage", t)
    e.hits = _num(r"(\d+)\s*times", t) or (2 if re.search(r"damage twice", t, re.I) else 1)
    e.all_enemies = bool(re.search(r"ALL enem", t, re.I))
    e.block = _num(r"Gain\s*(\d+)\s*Block", t)
    e.vulnerable = _debuff(_num(r"Apply\s*(\d+)\s*Vulnerable", t))
    e.weak = _debuff(_num(r"Apply\s*(\d+)\s*Weak", t))
    e.strength = _num(r"Gain\s*(\d+)\s*Strength", t)
    e.enemy_strength = _num(r"enem\w* gains?\s*(\d+)\s*Strength", t)
    e.draw = _num(r"Draw\s*(\d+)\s*card", t) or (1 if re.search(r"Draw a card", t, re.I) else 0)
    e.energy = _num(r"Gain\s*(\d+)\s*Energy", t)
    e.exhaust = bool(re.search(r"\bExhaust\.", t))
    e.upgrades_hand = bool(re.search(r"Upgrade\s*(a|\d+|ALL)\s*cards?\s*in\s*your\s*Hand", t, re.I))
    m = re.search(r"(Exhaust|Discard)\s*(a|\d+)\s*(random\s*)?cards?", t, re.I)
    e.clears_hand = (1 if m.group(2).lower() == "a" else int(m.group(2))) if m else 0
    e.unplayable = bool(re.search(r"Unplayable", t, re.I)) or kind in ("Curse", "Status")
    e.known = e.unplayable or any((e.damage, e.block, e.vulnerable, e.weak, e.strength, e.draw, e.energy,
                                   e.upgrades_hand, e.clears_hand))
    if kind == "Power":
        e.known = True  # powers are valued as a whole by the planner
    return e


def effects_for(name: str, text: str, kind: str, known_text: dict[str, tuple[str, str]] | None = None) -> Effects:
    """Effects from the read text. When the read gave nothing usable, the text saved when the card was
    picked (known_text: name -> (kind, text)) is used, then the starter list."""
    e = parse(text, kind)
    if e.known:
        return e
    if known_text and name in known_text:
        k, t = known_text[name]
        saved = parse(t, k)
        if saved.known:
            saved.notes.append("text from the tracked deck")
            return saved
    base = name.rstrip("+")
    if base in KNOWN_TEXT:
        k, t = KNOWN_TEXT[base]
        e = parse(t, k)
        e.notes.append("starter text used")
    return e
