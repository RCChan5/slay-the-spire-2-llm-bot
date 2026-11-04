"""The run review with a fake log and a stand-in model (run: python -m tests.test_review).
With --live the real local model reviews the fake run (files go to a temporary folder, never context/)."""

import sys
import tempfile
from pathlib import Path

from stsbot import brain, llm, review
from stsbot.screen import Card, Combat, Enemy

passed = failed = 0


def check(what, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


def combat(turn, hp, enemies, plan, floor=5):
    return {"kind": "combat", "floor": floor, "state": f"turn {turn}  HP {hp}/80 block 0  energy 3/3  hand [Strike(1)]  "
            f"enemies [{enemies}]", "plan": plan}


RECORDS = [
    {"kind": "combat", "state": "turn 3  HP 70/80 block 0  energy 3/3  hand []  enemies [1/9 intent 0]", "plan": ""},
    {"kind": "game_over", "floor": 2, "hp": 0, "won": False},  # an older run
    {"kind": "new_run", "ascension": "1"},
    {"kind": "neow", "pick": "Lava Rock"},
    combat(1, 80, "20/20 intent 6", "Defend, end turn (deal 0, kill 0, take 0 of 6)", 1),
    {"kind": "llm_fight", "choice": "Defend", "reason": "block", "source": "llm", "enemies": ["Shrinker Beetle"]},
    combat(2, 78, "20/20 intent 6", "Strike -> enemy 1, end turn (deal 6, kill 0, take 6 of 6)", 1),
    {"kind": "card_choice", "floor": 2, "offers": [{"name": "Body Slam"}, {"name": "Twin Strike"}], "pick": "Body Slam",
     "why": "llm: take Body Slam (Barricade)"},
    {"kind": "llm_pick", "pick": "Body Slam", "build": "Barricade", "committed_at": 5},
    {"kind": "campfire", "hp": 40, "max_hp": 80, "pick": "rest"},
    combat(1, 40, "53/53 Strength 3 intent 12", "Defend, end turn (deal 0, kill 0, take 2 of 12)", 6),
    {"kind": "llm_fight", "choice": "Defend", "reason": "block", "source": "simulator", "enemies": ["Byrdpip"]},
    combat(2, 38, "40/53 Strength 9 intent 18", "Strike -> enemy 1, end turn (deal 6, kill 0, take 18 of 18)", 6),
    combat(3, 20, "34/53 Strength 15 intent 24", "End turn (deal 0, kill 0, take 14 of 24)", 6),
    {"kind": "game_over", "floor": 6, "hp": 0, "won": False},
    {"kind": "game_over", "floor": 6, "hp": 0, "won": False},  # the screen is logged on every look
]

run = review.last_run(RECORDS)
check("the last run starts at its new_run record", run[0]["kind"], "new_run")
check("the last run ends at its game over", run[-1]["kind"], "game_over")
fights = review.split_fights(run)
check("two fights found", len(fights), 2)
check("enemy names come from the LLM records", fights[0].names, ["Shrinker Beetle"])

story = review.run_story(run, ["Strike", "Body Slam"], "")
check("the story says how it ended", story.startswith("Result: DIED on floor 6, ascension 1"), True)
check("the story names the committed build", "Barricade (committed on floor 5)" in story, True)
check("HP lost per enemy turn is listed", "HP lost each enemy turn: 2, 18, 20" in story, True)
check("a turn worse than predicted is called out", "turn 3: lost 20 HP" in story, True)
check("the scaling enemy shows at the end", "Strength 15" in story, True)
check("the death is marked", "DIED here" in story, True)
check("card picks with reasons", "took Body Slam" in story, True)
check("simulator fallbacks are counted", "simulator played instead" in story, True)

tmp = Path(tempfile.mkdtemp())
review.LESSONS_FILE, review.RULES_FILE = tmp / "what_i_learned.md", tmp / "learned_rules.md"
review.load_records = lambda days=2: RECORDS

answers = []
real_ask = llm.ask


def fake_ask(system, user, model=None, kind="", options=None):
    llm.last.update(seconds=0.0, error="", raw="")
    return answers.pop(0) if answers else None


llm.ask = fake_ask
answers[:] = [{"summary": "Died to a scaling enemy — too slow.", "mistakes": ["Blocked while Byrdpip scaled"],
               "what_worked": ["Body Slam pick"], "lessons": ["Kill Strength-scaling enemies fast"]},
              {"rules": ["Kill Strength-scaling enemies fast", "Block big hits"]}]
check("review writes lessons", review.review_last_run(["Strike"], "Barricade", False, say=lambda m: None), True)
text = review.LESSONS_FILE.read_text(encoding="utf-8")
check("lessons file has the run heading", "died on floor 6, Barricade" in text, True)
check("lessons file has the mistakes", "- Blocked while Byrdpip scaled" in text, True)
check("no em dashes written", "—" in text, False)
check("rules file is rewritten", review.learned_rules(), ["Kill Strength-scaling enemies fast", "Block big hits"])

answers[:] = [{"summary": "Won.", "lessons": ["Barricade with Body Slam works"]}, None]
review.review_last_run([], "", True, say=lambda m: None)
check("a second run is appended", review.LESSONS_FILE.read_text(encoding="utf-8").count("## "), 2)
check("no rules answer: old rules kept, new lesson added", review.learned_rules()[-1], "Barricade with Body Slam works")

answers[:] = [None]
check("no answer from the model: nothing written", review.review_last_run([], "", False, say=lambda m: None), False)

c = Combat(40, 80, 0, 1, 3, 3, [Card("Strike", 1, 0.4, 0.82)], [Enemy(30, 40, 0.65, 0.7, 13, 1)])
brain.learned_rules = review.learned_rules
check("learned rules go into the fight prompt", "Kill Strength-scaling enemies fast" in brain.fight_prompt(c, [], [], []),
      True)

llm.ask = real_ask
if "--live" in sys.argv:
    ok = review.review_last_run(["Strike", "Body Slam"], "Barricade", False)
    check("live review writes lessons", ok, True)
    print(review.LESSONS_FILE.read_text(encoding="utf-8")[-1500:])

print(f"test_review: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
