"""Read the whole deck from the deck view (the deck icon, top right) and put the tracked deck right.

The deck view is a card grid that scrolls. Pages overlap and OCR varies a little between them, so pages
are combined by name counts: each name keeps the most copies seen on any one page. The tracked deck is
only replaced when that total matches the deck count on the top bar.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter

from .builds import CARD_TIER
from .campfire import GridCard

DECK_ICON = (0.929, 0.035)
KNOWN_NAMES = set(CARD_TIER) | {"Strike", "Defend", "Bash", "Ascender's Bane"}
_BY_LOWER = {n.lower(): n for n in KNOWN_NAMES}


def clean_name(name: str) -> str:
    """OCR slips on card names: "+" read as "t" ("Basht"), and card text read where the name is."""
    name = re.sub(r"\s+", " ", name).strip()
    low = name.lower()
    if low in _BY_LOWER:  # known names regardless of capitals ("Shrug It off")
        return _BY_LOWER[low]
    for tail in ("t", "+"):
        if low.endswith(tail) and low[:-1].strip() in _BY_LOWER:
            return _BY_LOWER[low[:-1].strip()] + "+"
    words = name.split()
    if "," in name or "." in name or len(words) > 4 or (words and words[0][:1].islower()):
        return "Unknown card"  # its name was not readable: count it anyway
    return name


def merge_pages(pages: list[list[GridCard]], target: int | None = None) -> list[GridCard]:
    """All cards from pages read while scrolling: each name with the most copies seen on one page.
    target: the deck count on screen; extra "Unknown card" entries (an unreadable name standing in for a
    card already counted) are dropped down to it."""
    best: dict[str, list[GridCard]] = {}
    order: list[str] = []
    for page in pages:
        by_name: dict[str, list[GridCard]] = {}
        for c in page:
            c.name = clean_name(c.name)
            # One card read two ways on different pages ("Eastent" and "Fastent"): use the first spelling.
            same = difflib.get_close_matches(c.name, order, n=1, cutoff=0.8)
            if same and c.name not in order and same[0] != "Unknown card":
                c.name = same[0]
            by_name.setdefault(c.name, []).append(c)
        for name, cards in by_name.items():
            if name not in best:
                order.append(name)
            if len(cards) > len(best.get(name, [])):
                best[name] = cards
    cards = [c for name in order for c in best[name]]
    while target is not None and len(cards) > target and any(c.name == "Unknown card" for c in cards):
        cards.remove(next(c for c in cards if c.name == "Unknown card"))
    return cards


def page_names(cards: list[GridCard]) -> Counter:
    return Counter(clean_name(c.name) for c in cards)
