"""Card rewards: value each offered card for this deck, and skip when none is worth a slot.

A card's value is what it does per energy (damage, block, draw, energy, debuffs, scaling), plus synergy
with what the deck is already building toward, plus what the deck lacks right now (early damage, AoE,
block). Every card added makes the good cards come up less often, so a pick must beat the deck's current
average by a margin that grows with deck size; otherwise skip.

Ratings in data/card_ratings.json (name -> value, the same scale as `value`) override the formula, so
the user can teach it cards it misjudges.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .builds import build_bonus, deck_builds, tier_value
from .cards import parse

ROOT = Path(__file__).resolve().parent.parent
RATINGS = ROOT / "data" / "card_ratings.json"

BASICS = {"Strike", "Defend"}
STARTER = {"Ironclad": ["Strike"] * 5 + ["Defend"] * 4 + ["Bash"]}
STARTER_TEXT = {"Strike": ("Attack", "Deal 6 damage."), "Defend": ("Skill", "Gain 5 Block."),
                "Bash": ("Attack", "Deal 8 damage. Apply 2 Vulnerable."),
                "Ascender's Bane": ("Curse", "Unplayable. Ethereal.")}

@dataclass
class DeckCard:
    name: str
    kind: str
    text: str
    cost: int | None = None


@dataclass
class Deck:
    cards: list[DeckCard] = field(default_factory=list)

    @classmethod
    def starter(cls, character: str = "Ironclad", ascension: int = 0) -> "Deck":
        names = STARTER[character] + (["Ascender's Bane"] if ascension >= 5 else [])  # A5 adds the curse
        return cls([DeckCard(n, *STARTER_TEXT[n], cost={"Bash": 2, "Ascender's Bane": None}.get(n, 1))
                    for n in names])

    def count(self, pred) -> int:
        return sum(1 for c in self.cards if pred(c))

    def to_json(self) -> list[dict]:
        return [c.__dict__ for c in self.cards]

    @classmethod
    def from_json(cls, rows: list[dict]) -> "Deck":
        return cls([DeckCard(**r) for r in rows])


def load_ratings() -> dict[str, float]:
    try:
        return {k: float(v) for k, v in json.loads(RATINGS.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        return {}


def value(name: str, cost: int | None, kind: str, text: str, deck: Deck, floor: int = 1,
          ratings: dict[str, float] | None = None, in_deck: bool = False) -> tuple[float, list[str]]:
    """How much this card is worth in this deck, with the reasons.

    in_deck: valuing a card already in the deck (for the deck's average), so no bonus for what the deck
    lacks and no penalty for copies.
    """
    ratings = ratings if ratings is not None else load_ratings()
    if name in ratings:
        return ratings[name], ["your rating"]
    e = parse(text, kind)
    why: list[str] = []
    if e.unplayable:
        return -5.0, ["unplayable"]
    tv = tier_value(name)
    c = cost if cost is not None else 1
    per = max(c, 0.5)
    dmg = e.damage * e.hits
    strikes = deck.count(lambda d: "Strike" in d.name)
    m = re.search(r"(\d+) additional \S*damage", text) if "Strike" in text and "containing" in text else None
    if m:
        dmg += int(m.group(1)) * (strikes + 1)
        why.append(f"{strikes} Strike cards")
    if e.all_enemies:
        dmg *= 1.6
    v = 0.5 * dmg / per + 0.55 * e.block / per
    v += 2.0 * e.draw + 3.0 * e.energy + 1.5 * e.vulnerable + 1.5 * e.weak + 4.0 * e.strength - 3.0 * e.enemy_strength
    if kind == "Power":
        v += 3.0
        why.append("power: lasts the whole fight")
    if c == 0:
        v += 1.0
    if e.exhaust and kind != "Power":
        v -= 0.5
    if tv is not None:
        # Known card: the guides' tier is the base; Perfected Strike still grows with more Strike cards.
        extra = 0.4 * max(0, strikes - 5) if m else 0.0
        v = tv + extra
        why = [w for w in why if "Strike cards" in w] + [f"tier {tv:.1f}"]
    if e.block:
        # User rule: block cards are judged by block per energy (Defend's 5 per energy is the baseline) and by
        # what they do besides blocking. The text formula above already counts block per energy for unknown
        # cards, so the ratio is added only on top of a tier.
        ratio = e.block / per
        extras = [n for n, on in (("draw", e.draw), ("damage", e.damage), ("Vulnerable", e.vulnerable),
                                  ("Weak", e.weak), ("energy", e.energy), ("Strength", e.strength)) if on]
        b = 0.8 * len(extras) + (0.35 * (ratio - 5) if tv is not None else 0.0)
        hp_cost = re.search(r"Lose\s*(\d+)\s*HP", text)
        if hp_cost:
            b -= 0.4 * int(hp_cost.group(1))  # the user wants as little HP lost as possible
        v += b
        why.append(f"{ratio:.0f} block per energy" + (f" + {', '.join(extras)}" if extras else ""))

    if in_deck:
        return round(v, 2), why

    # The build the deck is going for.
    state = deck_builds(deck.cards)
    needs = set()
    if not deck.count(lambda d: parse(d.text, d.kind).all_enemies):
        needs.add("aoe")
    if deck.count(lambda d: d.name.rstrip("+") not in BASICS and parse(d.text, d.kind).block) < 3:
        needs.add("block")
    if deck.count(lambda d: parse(d.text, d.kind).draw) < 2:
        needs.add("draw")
    bonus, bwhy = build_bonus(name, text, state, needs)
    v += bonus
    why += bwhy

    # What the deck lacks now.
    attacks = deck.count(lambda d: parse(d.text, d.kind).damage > 0 and d.name.rstrip("+") not in BASICS)
    if floor <= 8 and dmg and attacks < 3:
        v += 1.0
        why.append("early fights need damage")
    has_aoe = deck.count(lambda d: parse(d.text, d.kind).all_enemies)
    if e.all_enemies and dmg and not has_aoe:
        v += 1.5
        why.append("first AoE")
    copies = deck.count(lambda d: d.name.rstrip("+") == name.rstrip("+"))
    if copies:
        v -= 0.7 * copies
        why.append(f"{copies} already in deck")
    return round(v, 2), why


def deck_average(deck: Deck, floor: int, ratings: dict[str, float]) -> float:
    vals = [value(c.name, c.cost, c.kind, c.text, Deck([d for d in deck.cards if d is not c]), floor, ratings,
                  in_deck=True)[0] for c in deck.cards]
    return sum(vals) / max(1, len(vals))


@dataclass
class Choice:
    pick: int | None  # index of the offer, or None to skip
    values: list[tuple[float, list[str]]]
    bar: float
    why: str


def choose(offers, deck: Deck, floor: int = 1, can_skip: bool = True) -> Choice:
    """offers: objects with name, cost, kind, text. can_skip=False when the screen has no Skip."""
    ratings = load_ratings()
    vals = [value(o.name, o.cost, o.kind, o.text, deck, floor, ratings) for o in offers]
    avg = deck_average(deck, floor, ratings)
    margin = 0.5 + 0.1 * max(0, len(deck.cards) - 10)
    bar = round(avg + margin, 2)
    if not vals:
        return Choice(None, [], bar, "no cards offered")
    best = max(range(len(vals)), key=lambda i: vals[i][0])
    if vals[best][0] < bar and can_skip:
        return Choice(None, vals, bar, f"skip: best is {offers[best].name} at {vals[best][0]}, "
                                        f"below the bar {bar} (deck of {len(deck.cards)}, average {avg:.2f}). "
                                        + deck_builds(deck.cards).describe())
    reasons = "; ".join(vals[best][1]) or "strongest card"
    reasons += ". " + deck_builds(deck.cards).describe()
    if vals[best][0] < bar:
        return Choice(best, vals, bar, f"take {offers[best].name} ({vals[best][0]}, below bar {bar} but no skip): {reasons}")
    return Choice(best, vals, bar, f"take {offers[best].name} ({vals[best][0]} over bar {bar}): {reasons}")
