"""The LLM's decisions: which card to play next in a fight, and which card to take (or skip) as a reward.

The user's rules: the LLM has the final say. In fights it sees the whole hand with the real card text
(context/), the enemies' intents and known moves, and the simulator's best few orders with the damage
each would take and deal; it should avoid HP loss when attacks come, spend all energy and cards unless a
play is harmful, and is asked again after every play (a drawn or added card changes the hand). Its
answer must be legal (a card in hand, energy to pay, a living target); after two illegal answers the
simulator's choice is played.

Card picks: it leans toward a build early, commits by floor 4-6 (the play guide's build rules), then
skips cards that do not serve the build, watching what the deck lacks (damage, block, AoE, draw).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from . import context as cx
from . import llm
from .cards import parse
from .planner import Action, Plan, describe
from .screen import Combat

BUILDS = ["Exhaust / infinite", "Self-damage", "Strength", "Barricade", "flexible"]
COMMIT_BY_FLOOR = 6


# ---------- fights
FIGHT_SYSTEM = """You are playing Slay the Spire 2 as the Ironclad. Decide the order to play the cards in hand this turn.

Rules, in priority order:
1. Avoid losing HP. If enemies will attack, block enough to take as little damage as possible, unless killing an attacker this turn prevents at least as much damage as blocking would.
2. Spend all energy and play every useful card by the end of the turn. Only hold a card if playing it is harmful (for example self-damage that would leave HP unsafe).
3. Play Powers first unless lethal or a big incoming attack needs an answer now. Play draw cards before spending energy on attacks.
4. Apply Vulnerable before attacks; finish enemies that can die.
5. Only play cards that are in the hand and whose cost fits the energy left. Unplayable cards cannot be played.

The simulator lists its best orders with predicted results; use them as advice, you decide.
Reply with JSON only: {"plan": [{"card": "<card name from hand>", "target": <enemy number or 0 for none>}, ...], "reason": "<one short sentence>"}.
An empty plan means end the turn now."""


def _enemy_lines(c: Combat, names: list[str]) -> list[str]:
    out = []
    for i, e in enumerate(c.enemies, 1):
        name = names[i - 1] if i - 1 < len(names) and names[i - 1] else "enemy"
        intent = (f"attacks for {e.intent_damage}" + (f" x{e.intent_hits}" if e.intent_hits > 1 else "")
                  if e.incoming else ("not attacking" if e.intent_attack is False else "intent unknown"))
        st = ", ".join(f"{k} {v}" for k, v in e.statuses.items())
        out.append(f"{i}. {name}: {e.hp}/{e.max_hp} HP" + (f", {e.block} block" if e.block else "")
                   + f", {intent}" + (f", statuses: {st}" if st else ""))
        known = cx.monster_line(name) if name != "enemy" else ""
        if known:
            out.append(f"   known: {known}")
    return out


def fight_prompt(c: Combat, options: list[Plan], names: list[str], relics: list[str], new_cards: list[str] = ()) -> str:
    incoming = sum(e.incoming for e in c.enemies if e.hp > 0)
    lines = [f"Turn {c.turn}. HP {c.hp}/{c.max_hp}, block {c.block}, energy {c.energy}/{c.max_energy}."
             + (f" Your statuses: {', '.join(f'{k} {v}' for k, v in c.statuses.items())}." if c.statuses else ""),
             f"Incoming damage this enemy turn: {incoming}.", "", "Hand:"]
    for card in c.hand:
        lines.append(f"- {cx.card_line(card.name)}" + (f" (cost read on screen: {card.cost})" if card.cost is not None else ""))
    if new_cards:
        lines.append(f"Just drawn (new since your last plan): {', '.join(new_cards)}. Re-plan the order with them.")
    lines += ["", "Enemies:"] + _enemy_lines(c, names)
    if relics:
        lines += ["", "Relics: " + "; ".join(cx.relic_line(r) or r for r in relics)]
    lines += ["", "Simulator's best orders:"]
    for k, p in enumerate(options[:4], 1):
        lines.append(f"{k}. {describe(c, p)}")
    return "\n".join(lines)


@dataclass
class FightChoice:
    action: Action | None  # None: end the turn
    reason: str
    source: str  # "llm" or "simulator"
    rest: list = field(default_factory=list)  # the LLM's later plays this turn: [(card name, target 0-based or None)]


def _match_card(name: str, c: Combat, energy: int) -> int | None:
    names = [h.name for h in c.hand]
    if name in names:
        i = names.index(name)
    else:
        m = difflib.get_close_matches(name, names, n=1, cutoff=0.7)
        if not m:
            return None
        i = names.index(m[0])
    card = c.hand[i]
    e = card.effects or parse("", "")
    if e.unplayable or (card.cost if card.cost is not None else 99) > energy:
        return None
    return i


def _rest(plan) -> list:
    out = []
    for step in plan[1:]:
        if isinstance(step, dict) and step.get("card"):
            try:
                t = int(step.get("target")) - 1
            except (TypeError, ValueError):
                t = None
            out.append((str(step["card"]), t))
    return out


def decide_fight(c: Combat, options: list[Plan], names: list[str], relics: list[str], fallback: Plan,
                 new_cards: list[str] = ()) -> FightChoice:
    user = fight_prompt(c, options, names, relics, new_cards)
    for attempt in range(2):
        ans = llm.ask(FIGHT_SYSTEM, user)
        if not isinstance(ans, dict):
            break
        plan = ans.get("plan")
        reason = str(ans.get("reason", ""))[:200]
        if plan == [] or plan is None:
            return FightChoice(None, reason or "end turn", "llm")
        first = plan[0] if isinstance(plan, list) and plan else None
        if isinstance(first, dict):
            i = _match_card(str(first.get("card", "")), c, c.energy)
            if i is not None:
                e = c.hand[i].effects
                alive = [j for j, en in enumerate(c.enemies) if en.hp > 0]
                t = None
                if e is not None and e.needs_target and alive:
                    try:
                        t = int(first.get("target", 0)) - 1
                    except (TypeError, ValueError):
                        t = -1
                    if t not in alive:
                        t = min(alive, key=lambda j: c.enemies[j].hp)  # a bad target: the weakest living enemy
                return FightChoice(Action(i, t), reason, "llm", _rest(plan))
        user += ("\n\nYour last answer was not a legal play (card not in hand, too expensive, or unplayable). "
                 "Choose again from the hand above.")
    a = fallback.actions[0] if fallback.actions else None
    return FightChoice(a, "simulator (the LLM gave no legal play)", "simulator")


# ---------- card rewards
PICK_SYSTEM = """You choose card rewards in Slay the Spire 2 as the Ironclad, following the play guide below.

Decide which build the deck is going for (one of: Exhaust / infinite, Self-damage, Strength, Barricade), using the guide's build rules. Before floor 4 you may stay "flexible" and pick for Act 1 survival (front-loaded damage and AoE, S and A tier first). By floor 6 at the latest, commit to one build and stick with it: from then on take only cards that serve that build or fill a real gap the deck shows (damage, block, AoE, draw), and skip everything else. Skipping is often right: every extra card makes the deck slower. Never take D or F tier cards unless they are core to the current build.

Reply with JSON only: {"pick": "<exact card name from the offer>" or "skip", "build": "<build name or flexible>", "reason": "<one short sentence>"}."""


def deck_stats(deck) -> str:
    dmg = blk = aoe = draw = scaling = 0
    for d in deck.cards:
        e = parse(d.text, d.kind)
        dmg += bool(e.damage)
        blk += bool(e.block)
        aoe += bool(e.all_enemies and e.damage)
        draw += bool(e.draw)
        scaling += bool(e.strength or d.kind == "Power")
    return (f"{len(deck.cards)} cards: {dmg} deal damage, {blk} give block, {aoe} hit all enemies, {draw} draw, "
            f"{scaling} scale (Strength or Powers).")


def pick_prompt(offers, deck, floor: int, build: str, committed_at: int | None, can_skip: bool, hp: int, max_hp: int) -> str:
    guide = "\n\n".join(x for x in (cx.build_overview(), cx.bot_rules()) if x)
    if build in cx.BUILD_SECTIONS:
        guide += "\n\n" + cx.build_guide(build)
    names = ", ".join(sorted(d.name for d in deck.cards))
    lines = [guide, "", f"Floor {floor}. HP {hp}/{max_hp}.",
             f"Current build: {build}" + (f" (committed on floor {committed_at}; stick to it)" if committed_at else ""),
             f"Deck: {names}", "Deck summary: " + deck_stats(deck), "", "Offered cards:"]
    for o in offers:
        lines.append(f"- {cx.card_line(o.name)}")
    if not can_skip:
        lines.append("\nThis offer cannot be skipped: you must pick one card.")
    elif floor >= COMMIT_BY_FLOOR and build == "flexible":
        lines.append(f"\nIt is floor {floor}: commit to a build now.")
    return "\n".join(lines)


@dataclass
class PickChoice:
    pick: int | None  # index into offers, None = skip
    build: str
    reason: str
    source: str


def decide_pick(offers, deck, floor: int, build: str, committed_at: int | None, can_skip: bool, hp: int,
                max_hp: int, fallback_pick: int | None) -> PickChoice:
    ans = llm.ask(PICK_SYSTEM, pick_prompt(offers, deck, floor, build, committed_at, can_skip, hp, max_hp))
    if isinstance(ans, dict):
        new_build = str(ans.get("build", build))
        new_build = next((b for b in BUILDS if b.lower() in new_build.lower() or new_build.lower() in b.lower()), build)
        if committed_at and build != "flexible":
            new_build = build  # committed: the build does not change
        reason = str(ans.get("reason", ""))[:200]
        pick = str(ans.get("pick", "")).strip()
        if pick.lower() == "skip":
            if can_skip:
                return PickChoice(None, new_build, reason, "llm")
        else:
            names = [o.name for o in offers]
            m = difflib.get_close_matches(pick, names, n=1, cutoff=0.6)
            if m:
                return PickChoice(names.index(m[0]), new_build, reason, "llm")
    return PickChoice(fallback_pick, build, "rules (the LLM gave no usable answer)", "rules")


def next_queued(c: Combat, queued: tuple) -> Action | None:
    """The next play of the LLM's plan, if it is still legal in this hand (else None: ask again)."""
    name, t = queued
    i = _match_card(name, c, c.energy)
    if i is None:
        return None
    e = c.hand[i].effects
    alive = [j for j, en in enumerate(c.enemies) if en.hp > 0]
    if e is not None and e.needs_target and alive:
        if t not in alive:
            t = min(alive, key=lambda j: c.enemies[j].hp)
    else:
        t = None
    return Action(i, t)
