"""What the bot knows about the current run: character, floor, deck. Saved in data/run.json.

The deck starts as the character's starter deck and grows with every card the bot picks. The deck
count on the top bar is compared with it, so a card added some other way (an event, a shop, the user
playing) shows up as a mismatch in the log.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .draft import Deck, DeckCard
from .ocr import Line

ROOT = Path(__file__).resolve().parent.parent
RUN_FILE = ROOT / "data" / "run.json"


@dataclass
class TopBar:
    hp: int | None = None
    max_hp: int | None = None
    gold: int | None = None
    floor: int | None = None
    deck_count: int | None = None


def read_top_bar(lines: list[Line], W: int, H: int) -> TopBar:
    t = TopBar()
    for l in lines:
        cx, cy = l.center[0] / W, l.center[1] / H
        if cy > 0.07:
            continue
        txt = l.text.strip()
        m = re.match(r"^(\d{1,3})\s*/\s*(\d{1,3})$", txt)
        if m and cx < 0.2:
            t.hp, t.max_hp = int(m.group(1)), int(m.group(2))
        elif re.match(r"^\d{1,4}$", txt):
            if 0.17 < cx < 0.26:
                t.gold = int(txt)
            elif 0.42 < cx < 0.46:
                t.floor = int(txt)
            elif 0.92 < cx < 0.95:
                t.deck_count = int(txt)
    return t


@dataclass
class Run:
    character: str = "Ironclad"
    floor: int = 0
    deck: Deck = field(default_factory=Deck.starter)

    def save(self):
        RUN_FILE.parent.mkdir(exist_ok=True)
        RUN_FILE.write_text(json.dumps({"character": self.character, "floor": self.floor,
                                        "deck": self.deck.to_json()}, indent=1), encoding="utf-8")

    @classmethod
    def load(cls) -> "Run":
        try:
            d = json.loads(RUN_FILE.read_text(encoding="utf-8"))
            return cls(d["character"], d["floor"], Deck.from_json(d["deck"]))
        except (OSError, ValueError, KeyError):
            return cls()

    def see(self, bar: TopBar) -> str | None:
        """Update from the top bar. Returns a note when something looks off (new run, deck mismatch)."""
        note = None
        if bar.floor is not None:
            if bar.floor < self.floor:
                self.deck = Deck.starter(self.character)
                note = f"new run (floor {bar.floor} after {self.floor}); deck reset to the starter deck"
            if bar.floor != self.floor:
                self.floor = bar.floor
                self.save()
        if bar.deck_count is not None and bar.deck_count != len(self.deck.cards) and note is None:
            note = f"deck count on screen is {bar.deck_count}, tracked deck has {len(self.deck.cards)}"
        return note

    def add(self, name: str, kind: str, text: str, cost: int | None):
        self.deck.cards.append(DeckCard(name, kind, text, cost))
        self.save()
