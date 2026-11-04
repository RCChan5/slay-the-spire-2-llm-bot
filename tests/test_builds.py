"""Build-aware card picks (run: python -m tests.test_builds)."""

import sys

from stsbot.builds import deck_builds
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


def card(name, kind="Skill", text="", cost=1):
    return DeckCard(name, kind, text, cost)


def offer(name, kind="Skill", text="", cost=1):
    return Offer(name, cost, kind, text, 0.5, 0.4)


def pick(offers, deck, floor=8, can_skip=True):
    ch = choose(offers, deck, floor, can_skip)
    return None if ch.pick is None else offers[ch.pick].name


starter = Deck.starter()

strength = Deck(starter.cards + [card("Inflame", "Power", "Gain 3 Strength."),
                                 card("Demon Form", "Power", "At the start of your turn, gain 2 Strength.", 3)])
check("Inflame + Demon Form commits to Strength", deck_builds(strength.cards).committed, "strength")
check("Strength deck takes Twin Strike over Shrug It Off",
      pick([offer("Shrug It Off", "Skill", "Gain 8 Block. Draw 1 card."),
            offer("Twin Strike", "Attack", "Deal 5 damage twice.")], strength), "Twin Strike")

block = Deck(starter.cards + [card("Barricade", "Power", "Block is not removed at the start of your turn.", 3),
                              card("Body Slam", "Attack", "Deal damage equal to your Block.")])
check("Barricade + Body Slam commits to Block", deck_builds(block.cards).committed, "block")
check("Block deck takes its key card Entrench over Inflame (another build's key card)",
      pick([offer("Inflame", "Power", "Gain 3 Strength."),
            offer("Entrench", "Skill", "Double your Block.", 2)], block), "Entrench")
check("...but a first AoE at S tier (Whirlwind) still beats Entrench",
      pick([offer("Whirlwind", "Attack", "Deal 5 damage to ALL enemies X times.", 0),
            offer("Entrench", "Skill", "Double your Block.", 2)], block), "Whirlwind")

exhaust = Deck(starter.cards + [card("Feel No Pain", "Power", "Whenever a card is Exhausted, gain 3 Block."),
                                card("Dark Embrace", "Power", "Whenever a card is Exhausted, draw 1 card.", 2)])
check("Feel No Pain + Dark Embrace commits to Exhaust", deck_builds(exhaust.cards).committed, "exhaust")
check("Exhaust deck takes True Grit over an off-plan Demon Form",
      pick([offer("Demon Form", "Power", "At the start of your turn, gain 2 Strength.", 3),
            offer("True Grit", "Skill", "Gain 7 Block. Exhaust a random card in your hand.")], exhaust), "True Grit")

mixed = Deck(starter.cards + [card("Inflame", "Power", "Gain 3 Strength."),
                              card("Barricade", "Power", "Block is not removed at the start of your turn.", 3)])
st = deck_builds(mixed.cards)
check("one key card in each of two builds: not committed", st.committed, None)
check("...but leaning toward both", sorted(st.leaning), ["block", "strength"])

check("Fight Me! (D tier) skipped by the starter deck",
      pick([offer("Fight Me!", "Attack", "Deal 5 damage twice. Gain 3 Strength. The enemy gains 1 Strength.", 2)],
           starter, 3), None)
check("starter deck takes Taunt from the live offer (efficient block with an extra)",
      pick([offer("Perfected Strike", "Attack", 'Deal 6 damage. Deals 2 additional damage for ALL your cards '
                                                'containing "Strike".', 2),
            offer("Taunt", "Skill", "Gain 6 Block. Apply 1 Vulnerable."),
            offer("Pommel Strike", "Attack", "Deal 9 damage. Draw 1 card.")], starter, 2), "Taunt")

vuln = Deck(starter.cards + [card("Dismantle", "Attack", "Deal 8 damage. If the enemy is Vulnerable, hit twice."),
                             card("Molten Fist", "Attack", "Deal 10 damage. Double the enemy's Vulnerable.")])
v_shrug, why = value("Shrug It Off", 1, "Skill", "Gain 8 Block. Draw 1 card.", vuln, 8)
check("committed Vulnerable deck values block it needs", any("needs block" in w for w in why), True)

ch = choose([offer("Twin Strike", "Attack", "Deal 5 damage twice.")], strength, 8)
check("the reason names the build", "Strength stacking" in ch.why, True)

print(f"test_builds: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
