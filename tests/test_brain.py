"""The LLM layer with a stand-in model: answers are checked, bad ones retried or replaced (run: python -m tests.test_brain).
With --live it also asks the real local model a few questions."""

import sys

from stsbot import brain, llm
from stsbot.cards import effects_for
from stsbot.draft import Deck, DeckCard
from stsbot.planner import plan_turn
from stsbot.screen import Card, Combat, Enemy, Offer

passed = failed = 0


def check(what, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


def card(n, cost, text, kind):
    c = Card(n, cost, 0.4, 0.82)
    c.effects = effects_for(n, text, kind)
    return c


def fight():
    hand = [card("Strike", 1, "Deal 6 damage.", "Attack"), card("Defend", 1, "Gain 5 Block.", "Skill"),
            card("Bash", 2, "Deal 8 damage. Apply 2 Vulnerable.", "Attack")]
    c = Combat(40, 80, 0, 1, 3, 2, hand, [Enemy(30, 40, 0.65, 0.7, 13, 1), Enemy(10, 20, 0.85, 0.7, 4, 1)])
    opts = []
    best = plan_turn(c, opts)
    return c, opts, best


answers = []


def fake_ask(system, user, model=None):
    llm.last.update(seconds=0.0, error="", raw="")
    return answers.pop(0) if answers else None


real_ask = llm.ask
llm.ask = fake_ask

c, opts, best = fight()
answers[:] = [{"plan": [{"card": "Defend", "target": 0}], "reason": "block"}]
ch = brain.decide_fight(c, opts, ["Shrinker Beetle", ""], [], best)
check("legal LLM play is used", (ch.source, c.hand[ch.action.card].name), ("llm", "Defend"))

answers[:] = [{"plan": [{"card": "Bash", "target": 1}]}, {"plan": [{"card": "Strike", "target": 2}]}]
ch = brain.decide_fight(c, opts, [], [], best)
check("too expensive (Bash at 1 energy) is retried", (ch.source, c.hand[ch.action.card].name, ch.action.target),
      ("llm", "Strike", 1))

answers[:] = [{"plan": [{"card": "Whirlwind"}]}, {"plan": [{"card": "Inflame"}]}]
ch = brain.decide_fight(c, opts, [], [], best)
check("two illegal answers: the simulator plays", ch.source, "simulator")

answers[:] = [{"plan": [{"card": "Strike", "target": 9}]}]
ch = brain.decide_fight(c, opts, [], [], best)
check("a bad target becomes the weakest living enemy", ch.action.target, 1)

answers[:] = [{"plan": [], "reason": "nothing useful"}]
check("an empty plan ends the turn", brain.decide_fight(c, opts, [], [], best).action, None)

answers[:] = [None]
check("no answer (Ollama down): the simulator plays", brain.decide_fight(c, opts, [], [], best).source, "simulator")

deck = Deck.starter()
offers = [Offer("Burning Pact", 1, "Skill", "", 0.3, 0.4), Offer("Body Slam", 1, "Attack", "", 0.5, 0.4)]
answers[:] = [{"pick": "Burning Pact", "build": "Exhaust / infinite", "reason": "core"}]
p = brain.decide_pick(offers, deck, 5, "flexible", None, True, 60, 80, 1)
check("pick and build from the LLM", (p.pick, p.build), (0, "Exhaust / infinite"))

answers[:] = [{"pick": "skip", "build": "flexible"}]
p = brain.decide_pick(offers, deck, 2, "flexible", None, False, 60, 80, 1)
check("skip refused when the screen has no Skip: rules pick", (p.pick, p.source), (1, "rules"))

answers[:] = [{"pick": "Body Slam", "build": "Barricade"}]
p = brain.decide_pick(offers, deck, 9, "Exhaust / infinite", 6, True, 60, 80, None)
check("a committed build does not change", p.build, "Exhaust / infinite")

check("prompt has the deck summary", "deal damage" in brain.pick_prompt(offers, deck, 3, "flexible", None, True, 60, 80), True)
check("fight prompt has the incoming damage", "Incoming damage this enemy turn: 17" in brain.fight_prompt(c, opts, [], []),
      True)

answers[:] = [{"plan": [{"card": "Defend"}, {"card": "Strike", "target": 2}], "reason": "block then hit"}]
ch = brain.decide_fight(c, opts, [], [], best)
check("the rest of the LLM plan is kept", ch.rest, [("Strike", 1)])
a = brain.next_queued(c, ch.rest[0])
check("a queued play still legal is used", (c.hand[a.card].name, a.target), ("Strike", 1))
check("a queued card no longer in hand asks again", brain.next_queued(c, ("Inflame", None)), None)
check("new cards are named in the prompt", "Just drawn" in brain.fight_prompt(c, opts, [], [], ["Pommel Strike"]), True)

from stsbot import context as cx
check("OCR '+' read as i is put right", cx.proper_name("Body Slami"), "Body Slam+")
check("a clipped name is completed", cx.proper_name("Forgotten Ritu"), "Forgotten Ritual")
check("a plain name stays", cx.proper_name("Strike"), "Strike")
c.hand[0].name = "Midnight"
c.hand[0].effects.text = "Gain 3 Strength."
check("a card not in the list shows its screen text", "text read on screen" in brain.fight_prompt(c, opts, [], []), True)

llm.ask = real_ask
if "--live" in sys.argv:
    c, opts, best = fight()
    ch = brain.decide_fight(c, opts, ["Shrinker Beetle", ""], ["Burning Blood"], best)
    print("live fight:", ch.source, None if ch.action is None else c.hand[ch.action.card].name, "|", ch.reason,
          f"| {llm.last['seconds']:.1f}s")
    check("live fight answer is legal", ch.source, "llm")
    p = brain.decide_pick(offers, deck, 7, "flexible", None, True, 60, 80, None)
    print("live pick:", p.source, None if p.pick is None else offers[p.pick].name, p.build, "|", p.reason)
    check("live pick commits by floor 7", p.build != "flexible", True)

print(f"test_brain: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
