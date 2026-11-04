"""Choosing a card from the hand: upgrade, discard, exhaust (run: python -m tests.test_handpick)."""

import sys

from stsbot.cards import effects_for
from stsbot.handpick import discard_pick, read_prompt, upgrade_pick
from stsbot.screen import Card

passed = failed = 0


def check(what, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


TEXT = {"Strike": ("Attack", "Deal 6 damage."), "Defend": ("Skill", "Gain 5 Block."),
        "Bash": ("Attack", "Deal 8 damage. Apply 2 Vulnerable."), "Shrug It Off": ("Skill", "Gain 8 Block. Draw 1 card."),
        "Injury": ("Curse", "Unplayable."), "Infection": ("Status", "Unplayable. At the end of your turn, take 3 damage."),
        "Bash+": ("Attack", "Deal 10 damage. Apply 3 Vulnerable.")}


def hand(*names, costs=None):
    out = []
    for i, n in enumerate(names):
        kind, text = TEXT[n]
        c = Card(n, (costs or {}).get(n, 2 if n.startswith("Bash") else (None if kind in ("Curse", "Status") else 1)),
                 0.3 + 0.08 * i, 0.82)
        c.effects = effects_for(n, text, kind)
        out.append(c)
    return out


check("prompt: upgrade", read_prompt("Choose a card to Upgrade."), read_prompt("Choose a card to upgrade"))
p = read_prompt("Choose 2 cards to Discard.")
check("prompt: discard 2", (p.action, p.count), ("discard", 2))
check("prompt: exhaust", read_prompt("Select a card to Exhaust.").action, "exhaust")
check("no prompt in normal text", read_prompt("Deal 6 damage."), None)

h = hand("Strike", "Bash", "Defend", "Injury")
check("upgrade Bash when it is still to play", h[upgrade_pick(h, {"Bash", "Strike"})[0]].name, "Bash")
h = hand("Strike", "Shrug It Off", "Injury")
check("upgrade a block card it still plays", h[upgrade_pick(h, {"Shrug It Off"})[0]].name, "Shrug It Off")
h = hand("Injury", "Bash+")
check("never upgrade a curse or an upgraded card", upgrade_pick(h, set())[0], None)

h = hand("Strike", "Defend", "Infection")
check("discard the status card first", h[discard_pick(h, set(), 3)[0][0]].name, "Infection")
h = hand("Strike", "Defend", "Bash")
check("then what cannot be paid for", h[discard_pick(h, set(), 1)[0][0]].name, "Bash")
h = hand("Strike", "Defend")
check("Strike before Defend (block first)", h[discard_pick(h, set(), 3)[0][0]].name, "Strike")
h = hand("Strike", "Defend")
check("never a card the plan needs", h[discard_pick(h, {"Strike"}, 3)[0][0]].name, "Defend")
h = hand("Injury", "Infection", "Strike")
check("two to discard: both bad cards", sorted(h[i].name for i, _ in discard_pick(h, set(), 3, 2)), ["Infection", "Injury"])

print(f"test_handpick: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
