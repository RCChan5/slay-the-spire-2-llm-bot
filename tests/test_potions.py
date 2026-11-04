"""Potion rules on made-up belts (run: python -m tests.test_potions)."""

import sys

from stsbot.potions import choose_potion, from_tooltip, slot_count

passed = failed = 0


def check(what, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


bomb = from_tooltip(0, "Explosive Ampoule Deal 10 damage to ALL enemies.")
memory = from_tooltip(1, "Liquid Memories Choose a card in your Discard Pile and return it to your Hand.")
guard = from_tooltip(2, "Block Potion Gain 12 Block.")
fire = from_tooltip(1, "Fire Potion Deal 20 damage.")

check("name and effect split", (bomb.name, bomb.effects.damage, bomb.effects.all_enemies),
      ("Explosive Ampoule", 10, True))
check("A4 has two slots", (slot_count(3), slot_count(4)), (3, 2))
check("room on the belt: keep potions", choose_potion([bomb, memory], 3, 12, 0, 40, 80, [30]).potion, None)
check("full belt: use one", choose_potion([bomb, memory, guard], 3, 12, 0, 40, 80, [30]).potion is not None, True)
check("full belt: never the one it cannot judge",
      choose_potion([memory, guard, bomb], 3, 0, 0, 70, 80, [30]).potion.name != "Liquid Memories", True)
check("emergency with room: finish the enemy", choose_potion([bomb, memory], 3, 20, 0, 17, 80, [5]).potion.name,
      "Explosive Ampoule")
check("emergency: block when nothing can kill", choose_potion([memory, guard], 3, 20, 5, 10, 80, [30]).potion.name,
      "Block Potion")
ch = choose_potion([fire, guard, bomb], 3, 0, 0, 70, 80, [30, 8])
check("single-target potion aims at the weakest enemy", (ch.potion.name, ch.target), ("Fire Potion", 1))
check("A4 full at two", choose_potion([bomb, guard], 2, 6, 0, 60, 80, [30]).potion is not None, True)

print(f"test_potions: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
