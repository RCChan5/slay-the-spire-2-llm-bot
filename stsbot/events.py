"""Choices with written options (Neow at the start of a run, and events): read each option and score it.

Upgrades, removals, relics, gold, max HP and healing count for an option; curses and losing HP, max HP or
gold count against it. Options the bot cannot judge score about zero, so a clearly good one wins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .ocr import Line
from .screen import join_text

CURSES = ["Curse", "Greed", "Ascender's Bane", "Doubt", "Regret", "Shame", "Pain", "Parasite", "Injury", "Clumsy",
          "Decay", "Normality", "Writhe"]


@dataclass
class Option:
    title: str
    text: str
    x: float  # where to click (the title), fractions of the window
    y: float


def option_value(text: str, hp: int, max_hp: int) -> tuple[float, list[str]]:
    v, why = 0.0, []

    def num(pat):
        m = re.search(pat, text, re.I)
        return int(m.group(1)) if m else 0

    if re.search(r"\bUpgrade", text):
        v += 3.0; why.append("upgrade")
    if re.search(r"\bRemove", text):
        v += 4.0; why.append("card removal")
    if re.search(r"\brelic\b", text, re.I):
        v += 4.0; why.append("relic")
    if re.search(r"\bTransform", text):
        v += 1.5; why.append("transform")
    if re.search(r"Choose\s*\d+\s*of|card reward|add .*cards? to your Deck", text, re.I):
        v += 2.0; why.append("card choice")
    if re.search(r"\bpotion", text, re.I):
        v += 1.0; why.append("potion")
    gold = num(r"Gain\s*(\d+)\s*Gold")
    if gold:
        v += gold / 45; why.append(f"+{gold} gold")
    mhp = num(r"Gain\s*(\d+)\s*Max HP") or num(r"Max HP by\s*(\d+)")
    if mhp:
        v += mhp / 2.5; why.append(f"+{mhp} max HP")
    heal = num(r"Heal\s*(\d+)")
    if heal:
        v += min(heal, max_hp - hp) / 5; why.append(f"heal {heal}")
    lose_hp = num(r"Lose\s*(\d+)\s*HP") or num(r"Take\s*(\d+)\s*damage")
    if lose_hp and not re.search(r"Lose\s*\d+\s*Max HP", text):
        v -= lose_hp / (3 if hp < 0.5 * max_hp else 5); why.append(f"-{lose_hp} HP")
    lose_mhp = num(r"Lose\s*(\d+)\s*Max HP")
    if lose_mhp:
        v -= lose_mhp / 1.5; why.append(f"-{lose_mhp} max HP")
    lose_gold = num(r"(?:Lose|Pay)\s*(\d+)\s*Gold")
    if lose_gold:
        v -= lose_gold / 45; why.append(f"-{lose_gold} gold")
    if any(re.search(rf"\b{re.escape(c)}\b", text) for c in CURSES):
        v -= 6.0; why.append("curse")
    if re.search(r"\b(Receive|Obtain) the\b", text) and not any(c in text for c in CURSES):
        v += 1.5; why.append("free item")
    if re.search(r"ignore\s*paths", text, re.I):
        v += 1.0; why.append("route freedom")
    return round(v, 2), why


def read_options(lines: list[Line], W: int, H: int, region=(0.24, 0.8, 0.6, 0.97)) -> list[Option]:
    """Options laid out as a title line with its description under it, top to bottom."""
    x0, x1, y0, y1 = region
    inside = [l for l in lines if x0 < l.center[0] / W < x1 and y0 < l.center[1] / H < y1
              and l.text.strip().lower() != "proceed"]
    inside.sort(key=lambda l: l.center[1])
    groups: list[list[Line]] = []
    for l in inside:
        if groups and l.center[1] - groups[-1][-1].center[1] < 0.035 * H:
            groups[-1].append(l)
        else:
            groups.append([l])
    out = []
    for g in groups:
        rows = sorted(g, key=lambda l: (l.center[1], l.box[0]))
        title = rows[0]
        rest = [l for l in rows[1:] if abs(l.center[1] - title.center[1]) > 0.01 * H]
        same_row = [l for l in rows[1:] if abs(l.center[1] - title.center[1]) <= 0.01 * H]
        title_text = " ".join(l.text for l in sorted([title] + same_row, key=lambda l: l.box[0]))
        out.append(Option(title_text, join_text(rest, H), title.center[0] / W, title.center[1] / H))
    return [o for o in out if o.text]


def best_option(options: list[Option], hp: int, max_hp: int) -> tuple[int | None, list[tuple[float, list[str]]]]:
    vals = [option_value(f"{o.title} {o.text}", hp, max_hp) for o in options]
    if not vals:
        return None, []
    return max(range(len(vals)), key=lambda i: vals[i][0]), vals
