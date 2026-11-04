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
    ascension: int | None = None


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
            if cx < 0.05:
                t.ascension = int(txt)  # the number on the character badge
            elif 0.17 < cx < 0.26:
                t.gold = int(txt)
            elif 0.42 < cx < 0.5:  # one digit sits near 0.44, two digits near 0.48
                t.floor = int(txt)
            elif 0.92 < cx < 0.95:
                t.deck_count = int(txt)
    return t


@dataclass
class Run:
    character: str = "Ironclad"
    floor: int = 0
    deck: Deck = field(default_factory=Deck.starter)
    ascension: int = 0
    hp: int = 0
    max_hp: int = 0
    gold: int = 0
    drawn_images: list = field(default_factory=list)  # pictures drawn this run (no repeats until all used)
    drawn_floors: list = field(default_factory=list)  # floors whose fresh map got a picture

    def save(self):
        RUN_FILE.parent.mkdir(exist_ok=True)
        RUN_FILE.write_text(json.dumps({"character": self.character, "floor": self.floor, "ascension": self.ascension,
                                        "drawn_images": self.drawn_images, "drawn_floors": self.drawn_floors,
                                        "hp": self.hp, "max_hp": self.max_hp, "gold": self.gold,
                                        "deck": self.deck.to_json()}, indent=1), encoding="utf-8")

    @classmethod
    def load(cls) -> "Run":
        try:
            d = json.loads(RUN_FILE.read_text(encoding="utf-8"))
            r = cls(d["character"], d["floor"], Deck.from_json(d["deck"]), d.get("ascension", 0))
            r.drawn_images = d.get("drawn_images", [])
            r.drawn_floors = d.get("drawn_floors", [])
            r.hp, r.max_hp, r.gold = d.get("hp", 0), d.get("max_hp", 0), d.get("gold", 0)
            return r
        except (OSError, ValueError, KeyError):
            return cls()

    def see(self, bar: TopBar) -> str | None:
        """Update from the top bar. Returns a note when something looks off (new run, deck mismatch)."""
        note = None
        before = (self.hp, self.max_hp, self.gold)
        if bar.hp is not None:
            self.hp, self.max_hp = bar.hp, bar.max_hp
        if bar.gold is not None:
            self.gold = bar.gold
        if (self.hp, self.max_hp, self.gold) != before:
            self.save()  # the dashboard shows them
        if bar.ascension is not None and bar.ascension != self.ascension:
            self.ascension = bar.ascension
            self.save()
        if bar.floor is not None and self.floor and bar.floor > self.floor + 3:
            bar.floor = None  # a jump of several floors at once is a misread (5 read as 57 once)
        if bar.floor is not None:
            if bar.floor < self.floor and bar.floor <= 2:  # runs start at floor 1; a smaller misread is not a new run
                self.deck = Deck.starter(self.character, self.ascension)
                self.drawn_images, self.drawn_floors = [], []
                note = f"new run (floor {bar.floor} after {self.floor}); deck reset to the starter deck"
            if bar.floor != self.floor:
                self.floor = bar.floor
                self.save()
        if bar.deck_count is not None and bar.deck_count != len(self.deck.cards) and note is None:
            note = f"deck count on screen is {bar.deck_count}, tracked deck has {len(self.deck.cards)}"
        return note

    def new_run(self):
        """A new run was started: starter deck, floor 0, nothing drawn yet."""
        self.deck = Deck.starter(self.character, self.ascension)
        self.floor = 0
        self.drawn_images, self.drawn_floors = [], []
        self.save()

    def add(self, name: str, kind: str, text: str, cost: int | None):
        self.deck.cards.append(DeckCard(name, kind, text, cost))
        self.save()
