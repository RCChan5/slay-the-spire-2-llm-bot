"""Read the whole deck from the deck view (the deck icon, top right) and put the tracked deck right.

The deck view is a card grid that scrolls. Each page is read as rows of cards; pages overlap when
scrolled, so rows are merged by the longest overlap between the end of what was read so far and the start
of the next page. The tracked deck is only replaced when the count matches the deck count on the top bar.
"""

from __future__ import annotations

from .campfire import GridCard

DECK_ICON = (0.929, 0.035)


def rows_of(cards: list[GridCard], tol: float = 0.03) -> list[tuple[GridCard, ...]]:
    rows: list[list[GridCard]] = []
    for c in sorted(cards, key=lambda c: (c.y, c.x)):
        if rows and abs(rows[-1][0].y - c.y) < tol:
            rows[-1].append(c)
        else:
            rows.append([c])
    return [tuple(sorted(r, key=lambda c: c.x)) for r in rows]


def _key(row) -> tuple:
    return tuple(c.name for c in row)


def merge_pages(pages: list[list[GridCard]]) -> list[GridCard]:
    """All cards from pages read top to bottom while scrolling down, overlapping rows counted once."""
    merged: list[tuple] = []
    for page in pages:
        rows = rows_of(page)
        best = 0
        for k in range(min(len(merged), len(rows)), 0, -1):
            if [_key(r) for r in merged[-k:]] == [_key(r) for r in rows[:k]]:
                best = k
                break
        merged.extend(rows[best:])
    return [c for r in merged for c in r]
