"""Cards that make you choose a card from your hand mid-fight: upgrade one (Armaments), or discard or
exhaust one (True Grit, Burning Pact, and others).

Upgrade: Bash first if it is still to be played (more damage and Vulnerable), then a card the plan still
plays this turn (attacks, or block: the block-first rule), then the best of the rest; never a curse,
status or upgraded card.

Discard or exhaust: curses and status cards first (pure gain; Infection and Burn also hurt at the end of
the turn), then cards that cannot be paid for this turn, then the weakest (Strike before Defend: block
first); never a card the plan still needs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .cards import parse
from .screen import Card

BAD_CARDS = {"Injury", "Infection", "Slimed", "Wound", "Burn", "Dazed", "Doubt", "Regret", "Shame", "Pain",
             "Parasite", "Clumsy", "Decay", "Normality", "Writhe", "Ascender's Bane", "Greed"}
PROMPT = re.compile(r"(choose|select|confirm)\b.{0,40}?\b(upgrade|discard|exhaust)", re.I)


@dataclass
class Prompt:
    action: str  # "upgrade", "discard" or "exhaust"
    count: int
    confirm: bool = False  # "Confirm Card to Upgrade": the card is chosen, only the check mark is left


def read_prompt(text: str) -> Prompt | None:
    """'Choose a card to Upgrade.', 'Choose 2 cards to Discard.' and the like."""
    m = PROMPT.search(text)
    if not m:
        return None
    n = re.search(r"(choose|select)\s*(\d+)", text, re.I)
    return Prompt(m.group(2).lower(), int(n.group(2)) if n else 1, m.group(1).lower() == "confirm")


def _is_bad(card: Card) -> bool:
    e = card.effects
    return card.name.rstrip("+") in BAD_CARDS or bool(e and (e.unplayable or e.kind in ("Curse", "Status")))


def upgrade_pick(hand: list[Card], still_to_play: set[str]) -> tuple[int | None, str]:
    best, why_best, score_best = None, "", -1e9
    for i, c in enumerate(hand):
        if _is_bad(c) or c.name.endswith("+"):
            continue
        e = c.effects or parse("", "")
        s, why = 0.0, []
        if c.name.rstrip("+") == "Bash" and c.name in still_to_play:
            s += 10
            why.append("Bash still to play: more damage and Vulnerable")
        if c.name in still_to_play:
            s += 5
            why.append("played this turn")
        if e.block:
            s += 2
            why.append("block (block first)")
        if e.damage:
            s += 1.5
        if c.name.rstrip("+") in ("Strike", "Defend"):
            s -= 1  # small gains
        if s > score_best:
            best, why_best, score_best = i, ", ".join(why) or "best of the rest", s
    return best, why_best


def discard_pick(hand: list[Card], still_to_play: set[str], energy_left: int, count: int = 1) -> list[tuple[int, str]]:
    """The cards to discard or exhaust, best first."""
    scored = []
    for i, c in enumerate(hand):
        if _is_bad(c):
            scored.append((100.0, i, "curse or status card"))
            continue
        if c.name in still_to_play:
            scored.append((-100.0, i, "needed this turn"))
            continue
        cost = c.cost if c.cost is not None else 1
        if cost > energy_left:
            scored.append((50.0, i, "cannot be paid for this turn"))
            continue
        base = c.name.rstrip("+")
        s = {"Strike": 30.0, "Defend": 20.0}.get(base, 10.0)
        scored.append((s, i, "weakest card" if base in ("Strike", "Defend") else "least needed"))
    scored.sort(key=lambda t: -t[0])
    return [(i, why) for _, i, why in scored[:count]]
