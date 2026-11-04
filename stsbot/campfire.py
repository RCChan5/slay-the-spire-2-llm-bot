"""Campfires: rest or upgrade, and which card to upgrade.

Screens (Slay the Spire 2): "What shall I do?" with option labels under pictures (Rest, Smith, and others
some relics add); then "Choose a card to Upgrade." with the whole deck as a grid; clicking a card shows a
before and after preview with a check mark to confirm.

Rest when HP is under REST_BELOW of max (the same line the route planner uses). Otherwise upgrade:
Bash first early (the guides' advice, and it is the deck's Vulnerable), then key cards of the build the
deck has committed to, then the best non-basic cards (block cards a little higher: block-first rule),
Defend before Strike, never a card already upgraded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .builds import BUILDS, deck_builds
from .cards import parse
from .draft import Deck, value
from .ocr import Line
from .screen import join_text

REST_BELOW = 0.55
CONFIRM = (0.954, 0.72)
KINDS = ("attack", "skill", "power", "curse", "status")


@dataclass
class GridCard:
    name: str
    kind: str
    text: str
    x: float  # click point (the card's art), fractions of the window
    y: float


def campfire_options(lines: list[Line], W: int, H: int) -> dict[str, tuple[float, float]]:
    """Option labels under the pictures, e.g. {"rest": (x, y), "smith": (x, y)}."""
    out = {}
    for l in lines:
        fx, fy = l.center[0] / W, l.center[1] / H
        # The middle only: overlays (Discord names) sit at the left edge.
        if 0.3 < fy < 0.5 and 0.25 < fx < 0.75 and re.match(r"^[A-Za-z]{3,12}$", l.text.strip()):
            out[l.text.strip().lower()] = (fx, fy - 0.09)  # click the picture above the label
    return out


def should_rest(hp: int, max_hp: int) -> bool:
    return max_hp > 0 and hp / max_hp < REST_BELOW


def read_grid(lines: list[Line], W: int, H: int) -> list[GridCard]:
    """Cards on the deck grid: each kind label with the name above it and the text below it."""
    cards = []
    for k in lines:
        kind = k.text.strip().lower()
        if kind not in KINDS:
            continue
        kx, ky = k.center[0] / W, k.center[1] / H
        name = None
        best = 9.0
        text_lines = []
        for l in lines:
            fx, fy = l.center[0] / W, l.center[1] / H
            if abs(fx - kx) > 0.065 or l is k:
                continue
            if 0.1 < ky - fy < 0.19 and re.search(r"[A-Za-z]{3}", l.text):
                d = abs(ky - fy - 0.146) + abs(fx - kx)
                if d < best:
                    best, name = d, l
            elif 0.02 < fy - ky < 0.12:
                text_lines.append(l)
        if name is not None:
            # A two-word name can come back as two words: take the words on the name's row.
            row = sorted([l for l in lines if abs(l.center[1] - name.center[1]) < 0.012 * H
                          and abs(l.center[0] / W - kx) < 0.07 and re.search(r"[A-Za-z]", l.text)],
                         key=lambda l: l.box[0])
            cards.append(GridCard(" ".join(l.text.strip() for l in row), kind.capitalize(),
                                  join_text(text_lines, H), kx, ky - 0.03))
    # Names close to the bottom edge may have no kind label on screen yet (the next row); left out.
    return sorted(cards, key=lambda c: (round(c.y, 2), c.x))


def upgrade_score(card: GridCard, deck: Deck, floor: int) -> tuple[float, str]:
    if card.name.endswith("+"):
        return -100.0, "already upgraded"
    if card.kind in ("Curse", "Status"):
        return -100.0, "cannot upgrade"
    base = card.name.rstrip("+")
    if base == "Strike":
        return 1.0, "basic"
    if base == "Defend":
        return 2.0, "basic block (block first)"
    v, _ = value(card.name, None, card.kind, card.text, deck, floor, in_deck=True)
    why = [f"value {v:.1f}"]
    if base == "Bash" and floor <= 25:
        v += 3.5
        why.append("Bash first (the deck's Vulnerable)")
    st = deck_builds(deck.cards)
    if st.committed and base in BUILDS[st.committed].key:
        v += 2.0
        why.append(f"key card for {BUILDS[st.committed].name}")
    if parse(card.text, card.kind).block:
        v += 1.0
        why.append("block (block first)")
    return v, ", ".join(why)


def best_upgrade(cards: list[GridCard], deck: Deck, floor: int) -> tuple[int | None, list[tuple[float, str]]]:
    scores = [upgrade_score(c, deck, floor) for c in cards]
    if not scores:
        return None, []
    i = max(range(len(scores)), key=lambda k: scores[k][0])
    return (i if scores[i][0] > -100 else None), scores
