"""Choose the next room: score every path through the visible map and walk the best one's first step.

Each path is simulated room by room (HP, gold), so a rest is worth what it heals at that point and an
elite is only good while the HP left after it stays safe. How much a fight costs depends on the deck the
bot has built (damage, AoE, block and scaling beyond the starter deck) and on the ascension level.

Ascension effects used (Slay the Spire 2, A1 to A10, cumulative):
  A1 more elites (more chances; each is still judged on its own), A2 lower max HP and Ancients heal less
  (max HP is read from the screen), A3 25% less gold, A4 one fewer potion slot (fights a bit costlier),
  A5 Ascender's Bane curse in the deck (removal worth more), A6 removal costs 100 then +50,
  A7 fewer rare and upgraded cards (elite relics matter more), A8 enemies have more HP,
  A9 enemies hit harder, A10 two Act 3 bosses (save HP late in Act 3).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .draft import BASICS, Deck, deck_average, load_ratings
from .cards import parse
from .mapread import MapView

STARTER_AVERAGE = 3.1  # the Ironclad starter deck's average card value (draft.value scale)
REST_HEAL = 0.30  # rest sites heal 30% of max HP
STEP_DECAY = 0.92  # rooms further ahead count a little less (the map may change plans)


@dataclass
class RunInfo:
    hp: int
    max_hp: int
    gold: int
    floor: int
    ascension: int
    act: int = 1


@dataclass
class DeckPower:
    quality: float  # deck average minus the starter's (0 = starter deck)
    aoe: bool
    block: int  # cards that gain Block beyond the basics
    scaling: int  # Strength, powers
    basics: int  # Strikes and Defends left (what a removal would cut)
    curses: int


def deck_power(deck: Deck, floor: int) -> DeckPower:
    ratings = load_ratings()
    q = deck_average(deck, floor, ratings) - STARTER_AVERAGE
    aoe = block = scaling = basics = curses = 0
    for c in deck.cards:
        e = parse(c.text, c.kind)
        base = c.name.rstrip("+")
        if base in BASICS:
            basics += 1
            continue
        if e.unplayable or c.kind == "Curse":
            curses += 1
        aoe += bool(e.all_enemies and e.damage)
        block += bool(e.block)
        scaling += bool(e.strength or c.kind == "Power")
    return DeckPower(q, aoe > 0, block, scaling, basics, curses)


def fight_cost(kind: str, info: RunInfo, p: DeckPower) -> float:
    """Expected HP lost in a fight of this kind."""
    base = {"enemy": 7.0, "elite": 20.0}[kind] * (1 + 0.25 * (info.act - 1))
    if info.ascension >= 8:
        base *= 1.12  # more enemy HP: longer fights
    if info.ascension >= 9:
        base *= 1.15  # enemies hit harder
    if info.ascension >= 4:
        base *= 1.03  # one fewer potion to bail out a bad fight
    strength = 1 + 0.12 * max(-1.0, p.quality) + 0.08 * min(p.scaling, 3) + 0.06 * min(p.block, 3)
    if p.aoe:
        strength += 0.1 if kind == "enemy" else 0.03  # hallway fights often have several enemies
    if kind == "elite" and info.floor <= 4 and p.quality < 0.5:
        base *= 1.3  # an unimproved starter deck: take two or three normal fights before the first elite
    return base / max(0.6, strength)


def death_risk(hp: float, cost: float) -> float:
    """Chance a fight costs more than the HP left, with the real cost spread around the expected one."""
    sd = max(2.0, 0.5 * cost)
    z = (hp - cost) / sd
    return 0.5 * math.erfc(z / math.sqrt(2))


def room_value(kind: str, info: RunInfo, hp: float, gold: float, p: DeckPower) -> tuple[float, float, float, str]:
    """(value, HP after, gold after, note) for entering a room with this HP and gold."""
    gold_mult = 0.75 if info.ascension >= 3 else 1.0
    if kind in ("enemy", "elite"):
        cost = fight_cost(kind, info, p)
        hp_after = hp - cost + 6  # Burning Blood heals 6 after every fight
        reward = 3.0 if kind == "enemy" else 10.0  # a card choice; an elite adds a guaranteed relic
        if kind == "elite" and info.ascension >= 7:
            reward += 1.0  # fewer rares elsewhere: relics carry more of the run
        if kind == "enemy" and info.floor <= 4:
            reward += 1.0  # early cards shape the deck
        g = (15 if kind == "enemy" else 30) * gold_mult
        reward -= death_risk(hp, cost) * 200
        return reward, hp_after, gold + g, f"-{cost:.0f} HP"
    if kind == "rest":
        missing = info.max_hp - hp
        heal = min(missing, REST_HEAL * info.max_hp)
        upgrade = 3.5
        if hp / info.max_hp < 0.55:
            return heal * 0.35, hp + heal, gold, f"heal {heal:.0f}"
        return max(upgrade, heal * 0.2), hp, gold, "upgrade"
    if kind == "merchant":
        removal_price = 100 if info.ascension >= 6 else 75
        v = 1.0
        note = "shop"
        if gold >= removal_price and (p.basics > 4 or p.curses):
            v += 3.0 + (2.0 if p.curses else 0.0)  # Ascender's Bane (A5) makes removal worth more
            gold -= removal_price
            note = "shop: removal"
        if gold >= 120:
            v += 2.0
            gold -= 75
            note += " + buy"
        return v, hp, gold, note
    if kind == "treasure":
        return 7.0, hp, gold + 40 * gold_mult, "relic"
    if kind == "unknown":
        return 3.5, hp - 2, gold + 10, "event"
    return 0.0, hp, gold, ""


def hp_penalty(hp: float, info: RunInfo) -> float:
    """What ending a path at this HP costs: little while healthy, a lot near death."""
    r = hp / info.max_hp
    pen = 0.0
    if r < 0.5:
        pen += (0.5 - r) * 40
    if r < 0.25:
        pen += (0.25 - r) * 120  # the next fight could end the run
    if hp <= 0:
        pen += 200
    if info.ascension >= 10 and info.act == 3:
        pen *= 1.3  # two bosses at the end of Act 3
    return pen


@dataclass
class RouteChoice:
    room: int | None
    path: list[int]
    score: float
    why: str


def choose_room(m: MapView, info: RunInfo, deck: Deck) -> RouteChoice:
    p = deck_power(deck, info.floor)
    starts = [i for i, r in enumerate(m.rooms) if r.reachable]
    if not starts and m.current is not None:
        starts = list(m.rooms[m.current].up)
    if not starts:
        return RouteChoice(None, [], 0.0, "no reachable room found on screen")
    best: RouteChoice | None = None

    def walk(i: int, hp: float, gold: float, depth: int, path: list[int], total: float, notes: list[str],
             low: float = 1e9):
        nonlocal best
        r = m.rooms[i]
        v, hp2, gold2, note = room_value(r.kind, info, hp, gold, p)
        total += v * (STEP_DECAY ** depth)
        if r.kind in ("enemy", "elite"):
            low = min(low, hp2 - 6)  # lowest point: right after the fight, before Burning Blood
        path = path + [i]
        notes = notes + [f"{r.kind}({note})"]
        if hp2 <= 0:
            total -= 200
        ups = r.up
        if not ups or depth >= 7:
            score = total - hp_penalty(hp2, info) - 0.5 * hp_penalty(min(low, hp2), info)
            if best is None or score > best.score:
                best = RouteChoice(path[0], path, score, " > ".join(notes) + f", ends at {hp2:.0f}/{info.max_hp} HP")
            return
        for j in ups:
            walk(j, hp2, gold2, depth + 1, path, total, notes, low)

    for s in starts:
        walk(s, float(info.hp), float(info.gold), 0, [], 0.0, [])
    best.why = (f"deck {p.quality:+.1f} vs starter" + (", AoE" if p.aoe else "") + f", A{info.ascension}: "
                + best.why)
    return best
