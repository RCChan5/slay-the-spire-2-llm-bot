"""After a run ends (death or win): turn the run's log into a short story, let the local LLM find the
mistakes and what worked, append that to context/what_i_learned.md, and rewrite the top 10 rules in
context/learned_rules.md. Those rules go into every fight and card-pick prompt (see brain.py).

    python -m stsbot.review            # review the last run in the logs now (also how the bot calls it)
    python -m stsbot.review --story    # only print the run story, no LLM

The full log is far too long for an 8B model, so code writes the story first: each fight with its enemies,
HP lost and the turns where more was lost than the plan predicted, the card picks and skips with their
reasons, campfires, events, potions, and what killed the bot.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import llm

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
CONTEXT = ROOT / "context"
LESSONS_FILE = CONTEXT / "what_i_learned.md"
RULES_FILE = CONTEXT / "learned_rules.md"
MAX_RULES = 10
STORY_CHARS = 9000  # what the story is cut to (the model's context is 8192 tokens, about 4 characters each)
REVIEW_OPTIONS = {**llm.OPTIONS, "num_predict": 1200}

STATE = re.compile(r"turn (\d+)\s+HP (\d+)/(\d+) block (\d+)")
ENEMIES = re.compile(r"enemies \[(.*)\]")
TAKE = re.compile(r"take (\d+) of (\d+)")
# Records that belong to a fight; anything else between two combat records means a new fight.
FIGHT_KINDS = {"combat", "llm_fight", "timing", "play_failed", "potion", "hand_prompt", "pause", "resume", "stop",
               "note", "upgrade"}


# ---------- reading the log
def load_records(days: int = 2) -> list[dict]:
    files = sorted(LOGS.glob("*.jsonl"))[-days:] if LOGS.exists() else []
    out = []
    for f in files:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def last_run(records: list[dict]) -> list[dict]:
    """The records of the last run: from the last new run start to the end (game over included)."""
    end = len(records)
    while end > 0 and records[end - 1].get("kind") in ("game_over", "pause", "resume", "stop", "note"):
        end -= 1
    while end < len(records) and records[end].get("kind") != "game_over":
        end += 1
    end = min(len(records), end + 1)
    start = 0
    for i in range(end - 1, -1, -1):
        r = records[i]
        if r.get("kind") == "new_run" or (r.get("kind") == "note" and str(r.get("note", "")).startswith("new run")):
            start = i
            break
    return records[start:end]


@dataclass
class Fight:
    floor: int | None = None
    enemies: str = ""
    names: list = field(default_factory=list)
    records: list = field(default_factory=list)


def split_fights(run: list[dict]) -> list[Fight]:
    fights: list[Fight] = []
    current: Fight | None = None
    for r in run:
        k = r.get("kind")
        if k == "combat":
            if current is None:
                current = Fight(floor=r.get("floor"))
                m = ENEMIES.search(r.get("state", ""))
                current.enemies = m.group(1) if m else ""
                fights.append(current)
            current.records.append(r)
        elif k in FIGHT_KINDS:
            if current is not None:
                current.records.append(r)
                if k == "llm_fight" and r.get("enemies") and not current.names:
                    current.names = [n for n in r["enemies"] if n]
        else:
            current = None
    return fights


def _turns(f: Fight) -> list[tuple[int, int, int, str]]:
    """(turn, hp at the first decision of the turn, hp at the last, the last plan) for each turn."""
    turns: dict[int, list] = {}
    for r in f.records:
        if r.get("kind") != "combat":
            continue
        m = STATE.search(r.get("state", ""))
        if not m:
            continue
        t, hp = int(m.group(1)), int(m.group(2))
        if t not in turns:
            turns[t] = [hp, hp, r.get("plan", "")]
        turns[t][1], turns[t][2] = hp, r.get("plan", "")
    return [(t, a, b, p) for t, (a, b, p) in sorted(turns.items())]


def fight_story(f: Fight, n: int, final_hp: int | None, is_last: bool) -> str:
    turns = _turns(f)
    if not turns:
        return ""
    start_hp, end_hp = turns[0][1], (final_hp if is_last and final_hp is not None else turns[-1][2])
    who = ", ".join(f.names) if f.names else f.enemies
    head = f"Fight {n}" + (f" (floor {f.floor})" if f.floor else "") + f": {who}. "
    head += f"HP {start_hp} -> {end_hp} over {len(turns)} turn(s)."
    lines = [head]
    last_state = next((r.get("state", "") for r in reversed(f.records) if r.get("kind") == "combat"), "")
    m = ENEMIES.search(last_state)
    if m and m.group(1) != f.enemies:
        lines.append(f"  enemies at the last decision: {m.group(1)}")
    lost_all, pred_all = [], []
    for (t, a, b, plan), nxt in zip(turns, turns[1:] + [None]):
        after = nxt[1] if nxt else (final_hp if is_last else None)
        if after is not None:
            m = TAKE.search(plan)
            lost_all.append(str(max(0, b - after)))
            pred_all.append(m.group(1) if m else "?")
    if any(x != "0" for x in lost_all):
        lines.append(f"  HP lost each enemy turn: {', '.join(lost_all)} (the plans predicted {', '.join(pred_all)})")
    for (t, a, b, plan), nxt in zip(turns, turns[1:] + [None]):
        after = nxt[1] if nxt else (final_hp if is_last else None)
        if after is None:
            continue
        lost = b - after
        m = TAKE.search(plan)
        predicted = int(m.group(1)) if m else None
        if lost > 0 and (predicted is None or lost > predicted + 2):
            lines.append(f"  turn {t}: lost {lost} HP in the enemy turn"
                         + (f" (the plan predicted {predicted})" if predicted is not None else "")
                         + f". Last plan: {plan[:160]}")
    plays = [r for r in f.records if r.get("kind") == "llm_fight"]
    sim = sum(1 for r in plays if r.get("source") == "simulator")
    if sim:
        lines.append(f"  the LLM gave no legal play {sim} time(s); the simulator played instead")
    failed = [r.get("card") for r in f.records if r.get("kind") == "play_failed"]
    if failed:
        lines.append(f"  cards that would not play: {', '.join(failed)}")
    for r in f.records:
        if r.get("kind") == "potion":
            lines.append(f"  potion: {r.get('potion')} ({r.get('why', '')[:80]})")
    if is_last and final_hp is not None and final_hp <= 0:
        last = next((r for r in reversed(f.records) if r.get("kind") == "combat"), None)
        if last:
            lines.append(f"  DIED here. Last state: {last.get('state', '')[:220]}")
            lines.append(f"  last plan: {last.get('plan', '')[:200]}")
    return "\n".join(lines)


def run_story(run: list[dict], deck: list[str] | None = None, build: str = "", won: bool | None = None) -> str:
    over = next((r for r in reversed(run) if r.get("kind") == "game_over"), None)
    final_hp = over.get("hp") if over else None
    floor = over.get("floor") if over else None
    if won is None:
        won = bool(over and over.get("won"))
    asc = next((r.get("ascension") for r in run if r.get("kind") == "new_run"), None)
    committed = next((r for r in run if r.get("kind") == "llm_pick" and r.get("committed_at")), None)
    if not build or build == "flexible":
        build = (f"{committed.get('build')} (committed on floor {committed.get('committed_at')})" if committed
                 else "flexible (never committed to a build)")
    out = [f"Result: {'WON' if won else 'DIED'}" + (f" on floor {floor}" if floor else "")
           + (f", ascension {asc}" if asc not in (None, "?") else "") + (f". Build: {build}." if build else ".")]
    if deck:
        out.append("Final deck: " + ", ".join(sorted(deck)))
    fights = split_fights(run)
    fight_ids = {id(r): (i, f) for i, f in enumerate(fights) for r in f.records}
    told = set()
    n_fight = 0
    for r in run:
        k = r.get("kind")
        if id(r) in fight_ids:
            i, f = fight_ids[id(r)]
            if i not in told:
                told.add(i)
                n_fight += 1
                s = fight_story(f, n_fight, final_hp, i == len(fights) - 1 and not won)
                if s:
                    out.append(s)
            continue
        if k == "card_choice":
            offers = ", ".join(o.get("name", "?") for o in r.get("offers", []))
            out.append(f"Card reward (floor {r.get('floor')}): offered {offers}; took {r.get('pick') or 'nothing (skip)'}. "
                       f"Why: {str(r.get('why', ''))[:160]}")
        elif k == "llm_pick" and r.get("committed_at"):
            out.append(f"Build: {r.get('build')} (committed on floor {r.get('committed_at')})")
        elif k == "campfire":
            out.append(f"Campfire at HP {r.get('hp')}/{r.get('max_hp')}: {r.get('pick')}")
        elif k == "upgrade":
            out.append(f"Upgraded {r.get('card')}")
        elif k == "remove":
            out.append(f"Removed {r.get('card')}")
        elif k == "event":
            out.append(f"Event {r.get('title')}: picked {r.get('pick')} of {r.get('options')}")
        elif k == "neow":
            out.append(f"Neow: picked {r.get('pick')}")
        elif k == "map" and r.get("choice"):
            out.append(f"Map: went to {r.get('choice')} ({str(r.get('why', ''))[:100]})")
    story = "\n".join(out)
    if len(story) > STORY_CHARS:  # keep the start (deck, build) and the end (the death)
        story = story[:STORY_CHARS // 3] + "\n[... middle of the run left out ...]\n" + story[-2 * STORY_CHARS // 3:]
    return story


# ---------- the LLM's review
REVIEW_SYSTEM = """You review a finished Slay the Spire 2 run that a bot played as the Ironclad. The bot reads the
screen; an LLM chooses card picks and the order of cards in fights, with a simulator's options to help.

Find what went wrong and what went right, from the run story below. Look at: card picks (off-build cards,
weak cards, skipping when the deck needed something), when and which build it committed to, fights where it
lost HP it could have blocked (turns where it lost more than the plan predicted), elite and boss fights,
campfire choices (rest or upgrade), potion use, and what killed it. Be concrete: name cards, enemies, floors.
State only facts the story shows: do not invent builds, upgrades, relics or cards that are not in it. An
enemy whose Strength rises over the fight is scaling: the lesson there is usually to kill it faster.

Reply with JSON only:
{"summary": "<two sentences on what happened>",
 "mistakes": ["<a concrete mistake>", ...],
 "what_worked": ["<something that worked>", ...],
 "lessons": ["<a short rule to follow next time, written as an instruction>", ...]}
Give at most 5 of each. Lessons must fit the player's strategy in the play guide rules (commit to a build
early and skip cards that do not serve it): a lesson against that strategy is wrong."""

RULES_SYSTEM = f"""You keep a bot's list of the most important rules it has learned from playing Slay the Spire 2 as
the Ironclad. You get the current list and the lessons from the run that just ended. Write the new list:
keep the rules that still matter, add the new lessons that matter most, merge rules that say the same thing,
drop vague ones. Never keep a rule that goes against the player's own strategy in the play guide rules
(pick a build early, stick with it, and skip cards that do not serve it). Each rule is one short instruction the bot can follow in a fight or a card pick. At most
{MAX_RULES} rules, the most important first.

Reply with JSON only: {{"rules": ["<rule>", ...]}}"""


def learned_rules() -> list[str]:
    try:
        return [l[2:].strip() for l in RULES_FILE.read_text(encoding="utf-8").splitlines() if l.startswith("- ")]
    except OSError:
        return []


def _clean(t) -> str:
    return str(t).replace(" \u2014 ", ": ").replace("\u2014", ", ").strip()


def _strs(x) -> list[str]:
    return [_clean(v) for v in x if _clean(v)][:5] if isinstance(x, list) else []


def review(story: str, won: bool, floor: int | None, build: str) -> dict | None:
    guide = ""
    from . import context as cx
    if cx.available():
        guide = cx.bot_rules()
    user = (f"The bot's play guide rules:\n{guide}\n\n" if guide else "") + "Run story:\n" + story
    rules = learned_rules()
    if rules:
        user += "\n\nRules it already had from earlier runs:\n" + "\n".join(f"- {r}" for r in rules)
    ans = llm.ask(REVIEW_SYSTEM, user, kind="run review", options=REVIEW_OPTIONS)
    if not isinstance(ans, dict):
        return None
    out = {k: _strs(ans.get(k)) for k in ("mistakes", "what_worked", "lessons")}
    out["summary"] = _clean(ans.get("summary", ""))
    return out


def update_rules(lessons: list[str]) -> list[str]:
    old = learned_rules()
    if not lessons:
        return old
    from . import context as cx
    guide = cx.bot_rules() if cx.available() else ""
    user = ((f"The player's play guide rules (the strategy to keep):\n{guide}\n\n" if guide else "")
            + "Current rules:\n" + ("\n".join(f"- {r}" for r in old) if old else "(none yet)")
            + "\n\nLessons from the run that just ended:\n" + "\n".join(f"- {l}" for l in lessons))
    ans = llm.ask(RULES_SYSTEM, user, kind="rules update", options=REVIEW_OPTIONS)
    rules = [_clean(r) for r in ans.get("rules", []) if _clean(r)] if isinstance(ans, dict) else []
    if not rules:  # no usable answer: keep the old rules and add the new lessons until the list is full
        rules = (old + [l for l in lessons if l not in old])
    return rules[:MAX_RULES]


def write_lessons(r: dict, won: bool, floor: int | None, build: str, asc) -> None:
    CONTEXT.mkdir(exist_ok=True)
    new = not LESSONS_FILE.exists()
    head = (f"## {time.strftime('%Y-%m-%d %H:%M')}: {'won' if won else 'died'}"
            + (f" on floor {floor}" if floor else "") + (f", {build}" if build and build != "flexible" else "")
            + (f", ascension {asc}" if asc not in (None, "?", "") else ""))
    parts = [head, ""]
    if r.get("summary"):
        parts += [r["summary"], ""]
    for title, key in (("Mistakes", "mistakes"), ("What worked", "what_worked"), ("Lessons", "lessons")):
        if r.get(key):
            parts.append(f"**{title}**")
            parts += [f"- {x}" for x in r[key]]
            parts.append("")
    with LESSONS_FILE.open("a", encoding="utf-8") as f:
        if new:
            f.write("# What I learned\n\nWritten by the bot's local LLM after each run (death or win), newest at the "
                    "bottom. The top rules it keeps from these are in learned_rules.md and go into its prompts.\n\n")
        f.write("\n".join(parts) + "\n")


def write_rules(rules: list[str]) -> None:
    CONTEXT.mkdir(exist_ok=True)
    RULES_FILE.write_text("# Rules learned from past runs\n\nRewritten by the bot after each run from "
                          "what_i_learned.md; they go into every fight and card-pick prompt. Edit or delete freely.\n\n"
                          + "\n".join(f"- {r}" for r in rules) + "\n", encoding="utf-8")


def review_last_run(deck: list[str] | None = None, build: str = "", won: bool | None = None,
                    say=print) -> bool:
    """The whole step: story, review, lessons file, rules file. True if lessons were written."""
    run = last_run(load_records())
    if not run:
        say("review: no run found in the logs")
        return False
    over = next((r for r in reversed(run) if r.get("kind") == "game_over"), {})
    if won is None:
        won = bool(over.get("won"))
    floor = over.get("floor")
    asc = next((r.get("ascension") for r in run if r.get("kind") == "new_run"), None)
    story = run_story(run, deck, build, won)
    say(f"review: reading the run ({len(run)} log records, story of {len(story)} characters)")
    t = time.time()
    r = review(story, won, floor, build)
    if r is None:
        say(f"review: the LLM gave no answer ({llm.last['error'] or 'unreadable'}); nothing written")
        return False
    write_lessons(r, won, floor, build, asc)
    rules = update_rules(r.get("lessons", []))
    write_rules(rules)
    say(f"review: lessons added to context/what_i_learned.md, {len(rules)} rules kept [{time.time() - t:.0f}s]")
    for l in r.get("lessons", []):
        say(f"  lesson: {l}")
    return True


def main():
    if "--story" in sys.argv:
        print(run_story(last_run(load_records())))
        return
    from .run import Run
    st = Run.load()
    review_last_run([c.name for c in st.deck.cards], st.build)


if __name__ == "__main__":
    main()
