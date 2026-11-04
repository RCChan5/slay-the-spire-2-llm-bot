"""Card reward checks on made-up offers (run: python -m tests.test_draft)."""

import sys

from stsbot.draft import Deck, DeckCard, choose, value
from stsbot.screen import Offer

passed = failed = 0


def check(what, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


def offer(name, cost, kind, text):
    return Offer(name, cost, kind, text, 0.5, 0.4)


PERFECTED = offer("Perfected Strike", 2, "Attack",
                  'Deal 6 damage. Deals 2 additional damage for ALL your cards containing "Strike".')
TAUNT = offer("Taunt", 1, "Skill", "Gain 6 Block. Apply 1 Vulnerable.")
POMMEL = offer("Pommel Strike", 1, "Attack", "Deal 9 damage. Draw 1 card.")
WEAK_BLOCK = offer("Flimsy Guard", 1, "Skill", "Gain 4 Block.")
WEAK_HIT = offer("Poke", 1, "Attack", "Deal 4 damage.")
CLEAVE = offer("Wide Swing", 1, "Attack", "Deal 8 damage to ALL enemies.")
CURSE = offer("Bad Luck", 0, "Curse", "Unplayable.")

starter = Deck.starter()
ch = choose([PERFECTED, TAUNT, POMMEL], starter, floor=2)
check("starter deck takes Pommel Strike (S in the user's tier list in context/)",
      ch.pick is not None and [PERFECTED, TAUNT, POMMEL][ch.pick].name, "Pommel Strike")

ch = choose([WEAK_BLOCK, WEAK_HIT], starter, floor=2)
check("skips cards no better than basics", ch.pick, None)

check("curse is never wanted", value(CURSE.name, 0, "Curse", CURSE.text, starter)[0] < 0, True)

v_first = value(CLEAVE.name, 1, "Attack", CLEAVE.text, starter, 3)[0]
with_aoe = Deck(starter.cards + [DeckCard("Wide Swing", "Attack", CLEAVE.text, 1)])
v_second = value(CLEAVE.name, 1, "Attack", CLEAVE.text, with_aoe, 3)[0]
check("first AoE is worth more than a second copy", v_first > v_second, True)

strikes = Deck(starter.cards + [DeckCard("Pommel Strike", "Attack", POMMEL.text, 1),
                                DeckCard("Twin Strike", "Attack", "Deal 5 damage twice.", 1)])
check("Perfected Strike grows with Strike cards",
      value(PERFECTED.name, 2, "Attack", PERFECTED.text, strikes)[0] >
      value(PERFECTED.name, 2, "Attack", PERFECTED.text, starter)[0], True)

strength_deck = Deck(starter.cards + [DeckCard("Flex Up", "Skill", "Gain 2 Strength.", 0),
                                      DeckCard("Inflamer", "Power", "Gain 2 Strength.", 1)])
heavy = offer("Heavy Swing", 2, "Attack", "Deal 14 damage. Strength affects this card 3 times.")
check("Strength payoff valued higher in a Strength deck",
      value(heavy.name, 2, "Attack", heavy.text, strength_deck)[0] >
      value(heavy.name, 2, "Attack", heavy.text, starter)[0], True)

# A big deck is pickier: the same middling card is taken at 10 cards but skipped at 30.
mid = offer("Solid Hit", 1, "Attack", "Deal 9 damage.")
big = Deck(starter.cards + [DeckCard("Pommel Strike", "Attack", POMMEL.text, 1)] * 20)
check("middling card taken in a small deck", choose([mid], starter, 2).pick, 0)
check("middling card skipped in a big deck", choose([mid], big, 30).pick, None)

# Block cards: block per energy and extras (user rule).
shrug = value("Shrug It Off", 1, "Skill", "Gain 8 Block. Draw 1 card.", starter, 8)[0]
clunky = value("Clunky Wall", 2, "Skill", "Gain 9 Block.", starter, 8)[0]
check("8 block + draw for 1 beats 9 block for 2", shrug > clunky, True)
wall = value("Blood Wall", 1, "Skill", "Lose 2 HP. Gain 16 Block.", starter, 8)[0]
wall_free = value("Blood Wall", 1, "Skill", "Gain 16 Block.", starter, 8)[0]
check("losing HP to block costs value", wall < wall_free, True)

misread = value("Armaments", 1, "Skill", "Gain 51 Block. Upgrade a card in your Hand.", starter, 8)[0]
check("block misread (51) capped", misread < 15, True)

print(f"test_draft: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
