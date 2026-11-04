"""Route choices on made-up maps, plus the saved map screenshots (run: python -m tests.test_route)."""

import sys
from pathlib import Path

import cv2

from stsbot.draft import Deck, DeckCard
from stsbot.mapread import MapView, Room, read_map
from stsbot.route import RunInfo, choose_room

passed = failed = 0


def check(what, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


def fork(left: list[str], right: list[str]) -> MapView:
    """Two reachable rooms, each leading straight up through its own list of rooms."""
    rooms: list[Room] = []

    def chain(kinds, x):
        start = len(rooms)
        for k, kind in enumerate(kinds):
            rooms.append(Room(kind, x, 0.8 - 0.13 * k, 1.0, reachable=(k == 0)))
            if k:
                rooms[-2].up.append(len(rooms) - 1)
        return start

    chain(left, 0.4)
    chain(right, 0.6)
    return MapView(rooms, [], None)


def pick(m, info, deck):
    ch = choose_room(m, info, deck)
    return None if ch.room is None else ("left" if m.rooms[ch.room].x < 0.5 else "right")


starter = Deck.starter()
strong = Deck(starter.cards + [
    DeckCard("Wide Swing", "Attack", "Deal 8 damage to ALL enemies.", 1),
    DeckCard("Inflamer", "Power", "Gain 2 Strength.", 1),
    DeckCard("Iron Wave", "Attack", "Gain 5 Block. Deal 5 damage.", 1),
    DeckCard("Pommel Strike", "Attack", "Deal 9 damage. Draw 1 card.", 1),
    DeckCard("Fight Me!", "Attack", "Deal 5 damage twice. Gain 3 Strength. The enemy gains 1 Strength.", 2),
])

elite_vs_easy = fork(["elite", "enemy"], ["enemy", "unknown"])
check("healthy strong deck takes the elite", pick(elite_vs_easy, RunInfo(70, 80, 100, 6, 0), strong), "left")
check("low HP avoids the elite", pick(elite_vs_easy, RunInfo(25, 80, 100, 6, 0), strong), "right")

rest_vs_fight = fork(["rest", "enemy"], ["enemy", "enemy"])
check("low HP goes to rest", pick(rest_vs_fight, RunInfo(22, 80, 100, 6, 0), starter), "left")

# Ascension makes fights cost more: a borderline elite at A0 becomes a skip at A9 with the starter deck.
borderline = fork(["elite", "enemy"], ["unknown", "enemy"])
a0 = pick(borderline, RunInfo(52, 80, 100, 6, 0), starter)
a9 = pick(borderline, RunInfo(52, 80, 100, 6, 9), starter)
check("A9 is more careful with elites than A0", (a0, a9) in (("left", "right"), ("left", "left"), ("right", "right"))
      and not (a0 == "right" and a9 == "left"), True)
check("A9 with starter deck at 52 HP skips the elite", a9, "right")

shop = fork(["merchant", "enemy"], ["enemy", "enemy"])
cursed = Deck.starter(ascension=5)
check("A5 curse and gold for removal: go to the shop", pick(shop, RunInfo(60, 80, 160, 8, 5), cursed), "left")
check("A6 removal unaffordable at 80 gold: no shop", pick(shop, RunInfo(60, 80, 80, 8, 6), starter), "right")
check("Ascender's Bane in the A5 starter deck", any(c.name == "Ascender's Bane" for c in cursed.cards), True)

# Saved screenshots: the bot must pick one of the reachable rooms.
SHOTS = Path(__file__).resolve().parent.parent / "shots"
for name in ("mapA0.png", "map2.png", "ev3.png", "map1b.png"):
    p = SHOTS / name
    if not p.exists():
        print(f"skip {name}")
        continue
    m = read_map(cv2.imread(str(p)))
    ch = choose_room(m, RunInfo(55, 80, 120, 4, 2), starter)
    check(f"{name}: picks a reachable room", ch.room is not None and m.rooms[ch.room].reachable, True)

print(f"test_route: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
