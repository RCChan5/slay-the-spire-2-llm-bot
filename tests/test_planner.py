"""Planner checks on made-up combat states (run: python -m tests.test_planner)."""

import sys

from stsbot.cards import effects_for, parse
from stsbot.planner import plan_turn
from stsbot.screen import Card, Combat, Enemy

passed = failed = 0


def check(what, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


def hand(*cards):
    out = []
    for i, (name, cost, text, kind) in enumerate(cards):
        c = Card(name, cost, 0.3 + i * 0.08, 0.82)
        c.effects = effects_for(name, text, kind)
        out.append(c)
    return out


S = ("Strike", 1, "Deal 6 damage.", "Attack")
D = ("Defend", 1, "Gain 5 Block.", "Skill")
B = ("Bash", 2, "Deal 8 damage. Apply 2 Vulnerable.", "Attack")

# Card text parsing.
e = parse("Deal 5 damage 3 times.", "Attack")
check("multi-hit", (e.damage, e.hits, e.needs_target), (5, 3, True))
e = parse("Deal 8 damage to ALL enemies.", "Attack")
check("all enemies", (e.damage, e.all_enemies, e.needs_target), (8, True, False))
e = parse("Gain 8 Biock. Draw 1 card.", "Skill")
check("block + draw with OCR slip", (e.block, e.draw), (8, 1))
check("unreadable starter falls back", effects_for("Strike+", "", "Attack").damage, 6)
check("curse is unplayable", parse("Unplayable.", "Curse").unplayable, True)

# A lethal hit beats blocking.
c = Combat(50, 80, 0, 1, 3, 3, hand(S, D), [Enemy(5, 40, 0.75, 0.7, 20, 1)])
p = plan_turn(c)
check("kill instead of block", [(a.card, a.target) for a in p.actions], [(0, 0)])

# Enemy attacking hard and out of reach: block first, then attack with what is left.
c = Combat(50, 80, 0, 2, 3, 3, hand(S, D), [Enemy(40, 40, 0.75, 0.7, 12, 1)])
p = plan_turn(c)
check("block a big hit", sorted(c.hand[a.card].name for a in p.actions), ["Defend", "Strike"])

# Bash before Strikes so they hit the Vulnerable enemy.
c = Combat(50, 80, 0, 3, 3, 1, hand(S, B), [Enemy(40, 40, 0.75, 0.7, 0, 1)])
p = plan_turn(c)
check("bash first", [c.hand[a.card].name for a in p.actions], ["Bash", "Strike"])

# Two enemies: finish the one that can die.
c = Combat(50, 80, 0, 1, 3, 2, hand(S), [Enemy(30, 30, 0.65, 0.7, 6, 1), Enemy(6, 20, 0.8, 0.7, 6, 1)])
p = plan_turn(c)
check("finish the weaker one", [(a.card, a.target) for a in p.actions], [(0, 1)])

# No energy: end turn.
c = Combat(50, 80, 0, 0, 3, 2, hand(S, D), [Enemy(30, 30, 0.75, 0.7, 6, 1)])
check("no energy ends turn", plan_turn(c).actions, [])

# Enemy block soaks damage: with 6 block on the 8 HP enemy, Strike cannot kill it, so hit the other.
c = Combat(50, 80, 0, 1, 3, 2, hand(S), [Enemy(30, 30, 0.65, 0.7, 6, 1), Enemy(6, 20, 0.8, 0.7, 6, 1, block=6)])
check("block soaks damage", [(a.card, a.target) for a in plan_turn(c).actions], [(0, 0)])

# Vulnerable already on the enemy (read from its status icon): Strike deals 9 and kills a 9 HP enemy.
c = Combat(50, 80, 0, 1, 3, 2, hand(S, D), [Enemy(9, 30, 0.75, 0.7, 20, 1, statuses={"Vulnerable": 1})])
check("existing Vulnerable counted", [(a.card, a.target) for a in plan_turn(c).actions], [(0, 0)])

# A non-attack intent brings no damage: no reason to block, so attack.
c = Combat(50, 80, 0, 1, 3, 2, hand(S, D), [Enemy(30, 30, 0.75, 0.7, 1, 1, intent_attack=False)])
check("non-attack intent", [c.hand[a.card].name for a in plan_turn(c).actions], ["Strike"])

# User rule: block first at any HP; kill only when that saves at least as much HP.
c = Combat(80, 80, 0, 1, 3, 2, hand(S, D), [Enemy(30, 30, 0.75, 0.7, 8, 1)])
check("full HP, 8 coming: Defend over Strike", [c.hand[a.card].name for a in plan_turn(c).actions], ["Defend"])

c = Combat(60, 80, 0, 2, 3, 2, hand(S, S, D), [Enemy(30, 30, 0.75, 0.7, 4, 1)])
check("small hit: block it, then attack with the rest",
      sorted(c.hand[a.card].name for a in plan_turn(c).actions), ["Defend", "Strike"])

# Killing a non-attacker while another enemy hits for 6: block instead.
c = Combat(60, 80, 0, 1, 3, 2, hand(S, D), [Enemy(5, 20, 0.65, 0.7, 0, 1, intent_attack=False),
                                           Enemy(30, 30, 0.8, 0.7, 6, 1)])
check("no kill that costs HP elsewhere", [c.hand[a.card].name for a in plan_turn(c).actions], ["Defend"])

# Killing the attacker saves 9 HP, blocking saves 5: kill.
c = Combat(60, 80, 0, 1, 3, 2, hand(S, D), [Enemy(6, 20, 0.75, 0.7, 9, 1)])
check("kill when it saves more HP than blocking", [(c.hand[a.card].name, a.target) for a in plan_turn(c).actions],
      [("Strike", 0)])

# Nothing coming: attack with everything.
c = Combat(60, 80, 0, 2, 3, 2, hand(S, D, S), [Enemy(30, 30, 0.75, 0.7, 0, 1, intent_attack=False)])
check("no attack coming: all damage", sorted(c.hand[a.card].name for a in plan_turn(c).actions), ["Strike", "Strike"])

# Infection in hand: 3 damage at the end of the turn counts as coming damage, so it blocks for it.
inf = Card("Infection", None, 0.6, 0.82)
inf.effects = effects_for("Infection", "Unplayable. At the end of your turn, if this is in your Hand, take 3 damage.",
                          "Status")
c = Combat(20, 80, 0, 1, 3, 2, hand(S, D) + [inf], [Enemy(30, 30, 0.75, 0.7, 0, 1, intent_attack=False)])
check("end-of-turn status damage is blocked", [c.hand[a.card].name for a in plan_turn(c).actions], ["Defend"])

# Two ways to stop 5 damage: Defend (5 for 1) or a 2-energy 8-block card. Take the efficient one.
WALL = ("Clunky Wall", 2, "Gain 8 Block.", "Skill")
c = Combat(60, 80, 0, 2, 3, 2, hand(WALL, D), [Enemy(30, 30, 0.75, 0.7, 5, 1)])
check("cheapest block that stops the hit", [c.hand[a.card].name for a in plan_turn(c).actions], ["Defend"])

# A card that exhausts from the hand is worth playing when a curse or status card is in hand.
TG = ("True Grit", 1, "Gain 7 Block. Exhaust a random card in your Hand.", "Skill")
inj = Card("Injury", None, 0.7, 0.82)
inj.effects = effects_for("Injury", "Unplayable.", "Curse")
c = Combat(60, 80, 0, 1, 3, 2, hand(TG, S) + [inj], [Enemy(30, 30, 0.75, 0.7, 0, 1, intent_attack=False)])
check("exhaust the curse rather than Strike", [c.hand[a.card].name for a in plan_turn(c).actions], ["True Grit"])

print(f"test_planner: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
