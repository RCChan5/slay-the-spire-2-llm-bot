"""Route planning on a made-up act map (run: python -m tests.test_pathplan)."""

import sys

from stsbot import llm, pathplan as pp

passed = failed = 0


def check(what, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


# Two lanes from the bottom to a campfire row, with a crossing in the middle.
#   row 0: A enemy        B enemy
#   row 1: C enemy        D unknown
#   row 2: E enemy        F rest
#   row 3: G enemy        H elite
#   row 4: I elite        J rest      (G can cross to J, H to I)
#   row 5: K rest
kinds = ["enemy", "enemy", "enemy", "unknown", "enemy", "rest", "enemy", "elite", "elite", "rest", "rest"]
ups = [[2], [3], [4], [5], [6], [7], [8, 9], [8, 9], [10], [10], []]
nodes = [pp.Node(k, 0, 0.0, list(u)) for k, u in zip(kinds, ups)]
st = pp.State(act=1, hp=70, max_hp=80, gold=99, strong=False)

routes = pp.routes_from(nodes, [0, 1])
check("every route is found", len(routes), 4)
check("routes end at the top", all(r[-1] == 10 for r in routes), True)

left = pp.facts(nodes, [0, 2, 4, 6, 8, 10], st)
check("four enemies: three easy, one hard", (left.easy, left.hard), (3, 1))
check("left lane has no campfire before its elite", left.rest_before_elite, False)
right = pp.facts(nodes, [1, 3, 5, 7, 8, 10], st)
check("right lane: campfire before the first elite", right.rest_before_elite, True)
check("two elites counted", right.elites, 2)
check("an event counted", right.events, 1)
check("a fork after the first elite is a pivot", right.pivots >= 1, True)

hard = pp.facts(nodes, [0, 2, 4, 6, 8, 10], pp.State(1, 70, 80, 99, False, fights_done=2))
check("fights already taken make later ones hard", (hard.easy, hard.hard), (1, 3))
check("two hard fights in a row with no campfire are flagged", hard.hard_stretch, True)

best = pp.top_routes(nodes, [0, 1], st)
check("the guide's shape wins: campfire before two elites", best[0].nodes, [1, 3, 5, 7, 8, 10])
check("routes with the same rooms are listed once", len({tuple(r.kinds) for r in best}), len(best))
check("summary names the facts", "campfire before the first elite" in best[0].summary(), True)
check("act 2 guide section is used for act 2", "Act 2 rules" in pp.guide_text(2), True)

answers = []
real = llm.ask
llm.ask = lambda system, user, model=None, kind="", options=None: answers.pop(0) if answers else None
answers[:] = [{"route": 2, "reason": "safer"}]
p = pp.pick_route(best, st, "starter")
check("the LLM's pick is used", (p.source, p.route is best[1]), ("llm", True))
answers[:] = [{"route": 9}]
check("a pick out of range falls back to the best score", pp.pick_route(best, st, "starter").source, "rules")
answers[:] = [None]
check("no answer: the best score", pp.pick_route(best, st, "starter").route is best[0], True)
llm.ask = real

last = pp.State(1, 70, 80, 99, False)
check("after an elite: re-plan", pp.should_replan(pp.State(1, 60, 80, 99, False), last, "elite"), "after an elite")
check("HP falls below half: re-plan", pp.should_replan(pp.State(1, 35, 80, 99, False), last, "enemy"),
      "HP fell below half")
check("gold reaches the shop plan: re-plan", pp.should_replan(pp.State(1, 70, 80, 300, False), last, "enemy"),
      "gold changed the shop plan")
check("nothing changed: keep the plan", pp.should_replan(pp.State(1, 66, 80, 120, False), last, "enemy"), None)

print(f"test_pathplan: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
