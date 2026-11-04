"""Plan the whole act's route at the start of each act (the user's map_pathing_guide.md, 2026-11-04).

The full map (every room and path, read by scrolling, see mapread.read_full_map) is a graph of rows from
the bottom to the boss. Every route from a start room to the top is listed with the facts the guide
plans around: elites, campfires (and whether one comes before the first elite), the easy hallway fights
(the first 3 normal fights in Act 1, 2 in Acts 2 and 3) and the hard ones after them, shops and when,
events, treasure, pivots (forks after the first elite) and stretches of hard fights with no campfire.
Each route is scored with the guide's decision rules (section 11) and the local LLM picks from the top 5
with the guide in front of it (pick_route).

The plan is followed room by room and re-planned at forks when things change: after an elite, when HP
drops below half, or when gold changes the shop plan (the guide's pivot rules, section 6).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import context as cx
from . import llm

EASY_POOL = {1: 3, 2: 2, 3: 2}  # normal fights per act that come from the easy pool
ELITE_TARGET = {1: (3, 2), 2: (3, 2), 3: (2, 2)}  # (strong deck, weak deck)
MAX_ROUTES = 20000  # a safety cap on enumeration (real maps have a few hundred routes)


@dataclass
class Node:
    kind: str  # enemy, elite, rest, merchant, unknown, treasure, boss
    row: int  # 0 = the bottom row of the act
    x: float  # horizontal position (fraction of the window)
    up: list[int] = field(default_factory=list)  # nodes in the next row this one leads to


@dataclass
class State:
    act: int
    hp: int
    max_hp: int
    gold: int
    strong: bool  # deck clearly better than the starter (draft quality, AoE, scaling)
    fights_done: int = 0  # normal fights already taken this act
    elites_done: int = 0  # elites already taken this act


@dataclass
class Route:
    nodes: list[int]
    kinds: list[str]
    elites: int = 0
    rests: int = 0
    rest_before_elite: bool = False
    easy: int = 0
    hard: int = 0
    shops: list[int] = field(default_factory=list)  # step numbers of shops
    events: int = 0
    treasure: int = 0
    pivots: int = 0
    hard_stretch: bool = False  # 2+ hard fights between elites with no campfire
    score: float = 0.0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        seq = " > ".join(k.replace("merchant", "shop").replace("unknown", "?") for k in self.kinds)
        facts = [f"{self.elites} elite(s)", f"{self.rests} campfire(s)",
                 "campfire before the first elite" if self.rest_before_elite else "no campfire before the first elite",
                 f"{self.easy} easy + {self.hard} hard hallway fight(s)", f"{self.events} event(s)"]
        if self.shops:
            facts.append("shop at step " + ", ".join(str(s + 1) for s in self.shops))
        if self.treasure:
            facts.append(f"{self.treasure} treasure")
        facts.append(f"{self.pivots} pivot(s) after the first elite")
        if self.hard_stretch:
            facts.append("a stretch of 2+ hard fights with no campfire")
        return f"{seq}\n   {'; '.join(facts)}"


def routes_from(nodes: list[Node], starts: list[int]) -> list[list[int]]:
    """Every route from a start node to a node with nothing above it (the boss row)."""
    out: list[list[int]] = []

    def walk(i: int, path: list[int]):
        if len(out) >= MAX_ROUTES:
            return
        path = path + [i]
        if not nodes[i].up:
            out.append(path)
            return
        for j in nodes[i].up:
            walk(j, path)

    for s in starts:
        walk(s, [])
    return out


def facts(nodes: list[Node], path: list[int], st: State) -> Route:
    kinds = [nodes[i].kind for i in path]
    r = Route(path, kinds)
    fights = st.fights_done
    pool = EASY_POOL.get(st.act, 2)
    seen_elite = st.elites_done > 0
    hard_since_rest = 0
    for step, i in enumerate(path):
        k = nodes[i].kind
        if k == "enemy":
            fights += 1
            if fights <= pool:
                r.easy += 1
            else:
                r.hard += 1
                hard_since_rest += 1
                if hard_since_rest >= 2:
                    r.hard_stretch = True
        elif k == "elite":
            if not seen_elite and r.rests and r.elites == 0:
                r.rest_before_elite = True
            r.elites += 1
            seen_elite = True
            hard_since_rest = 0
        elif k == "rest":
            r.rests += 1
            hard_since_rest = 0
        elif k == "merchant":
            r.shops.append(step)
        elif k == "unknown":
            r.events += 1
        elif k == "treasure":
            r.treasure += 1
        if seen_elite and len(nodes[i].up) > 1:
            r.pivots += 1
    return r


def score(r: Route, st: State) -> Route:
    """The guide's decision rules (section 11) as points. Thresholds are the guide's bot notes."""
    strong_t, weak_t = ELITE_TARGET.get(st.act, (2, 2))
    target = strong_t if st.strong else weak_t
    hp_ratio = st.hp / max(1, st.max_hp)
    elites = r.elites + st.elites_done
    s = 0.0
    notes = []
    # Elites: the main source of power, up to the act's target.
    s += 6.0 * min(elites, target) - 3.0 * max(0, elites - target)
    if elites < 2 and st.act in (1, 2):
        s -= 10.0  # hard constraint 1: fewer than 2 elites in Acts 1 and 2
        notes.append("fewer than 2 elites")
    if hp_ratio < 0.4 and r.elites and not r.rest_before_elite:
        s -= 6.0
        notes.append("low HP and no campfire before the elite")
    # Campfires: one before the first elite is ideal (an upgrade lands on the card that wins it).
    s += 2.0 * min(r.rests, 3) + (4.0 if r.rest_before_elite else 0.0)
    # Hallway fights: the easy ones are cheap cards, hard ones cost HP for only a card.
    s += 1.5 * r.easy - 2.5 * r.hard
    if r.hard_stretch:
        s -= 6.0  # hard constraint 2
        notes.append("2+ hard fights without a campfire")
    # Events are strong in STS2, more so in Act 1.
    s += (2.0 if st.act == 1 else 1.2) * r.events
    s += 3.0 * r.treasure
    # Shops by timing and gold (section 5).
    for step in r.shops:
        if st.act == 1:
            s += 2.0 if step <= 4 else -0.5
        elif st.act == 2:
            s += 3.0 if st.gold >= 280 else (1.0 if step >= 8 else 0.0)
        else:
            s += 1.0 + 0.2 * step  # Act 3: the furthest shop spends all the gold
    # Pivots: an out after the first elite (hard constraint 3).
    s += 1.5 * min(r.pivots, 3)
    if r.pivots == 0 and r.elites >= 2 and not (st.strong and hp_ratio > 0.6):
        s -= 5.0  # hard constraint 4: no-pivot path only for a strong, healthy deck
        notes.append("no pivots")
    r.score = round(s, 1)
    r.notes = notes
    return r


def top_routes(nodes: list[Node], starts: list[int], st: State, n: int = 5) -> list[Route]:
    """The n best routes by score, each with a different sequence of room kinds."""
    scored = [score(facts(nodes, p, st), st) for p in routes_from(nodes, starts)]
    scored.sort(key=lambda r: -r.score)
    out, seen = [], set()
    for r in scored:
        key = tuple(r.kinds)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= n:
            break
    return out


# ---------- the LLM's pick
ROUTE_SYSTEM = """You plan the route through one act of Slay the Spire 2 for a bot playing the Ironclad, using the
map pathing guide below. You get the run's state and the best candidate routes (bottom to boss), each with
its facts. Choose the route that best follows the guide: elites up to the act's target, a campfire before
the first elite, the easy hallway fights and few hard ones, events, shops at the right time for the gold,
and pivots to bail out. Weigh the deck's strength and HP.

Reply with JSON only: {"route": <route number>, "reason": "<one or two short sentences>"}."""


def guide_text(act: int) -> str:
    """The parts of the map guide that matter for this act (the whole file is too long for every call)."""
    parts = [cx.map_guide_section(n) for n in ("1.", "3.", "6.", "11.")]
    parts.insert(2, cx.map_guide_section({1: "4.", 2: "7.", 3: "8."}.get(act, "4.")))
    parts.insert(3, cx.map_guide_section("5."))
    return "\n\n".join(p for p in parts if p)


def route_prompt(routes: list[Route], st: State, deck_note: str) -> str:
    lines = [guide_text(st.act), "",
             f"Act {st.act}. HP {st.hp}/{st.max_hp}, gold {st.gold}. Deck: {deck_note} "
             f"({'strong' if st.strong else 'weak'} for now). Normal fights already taken this act: "
             f"{st.fights_done}; elites: {st.elites_done}.", "", "Candidate routes:"]
    for k, r in enumerate(routes, 1):
        lines.append(f"{k}. {r.summary()}")
    return "\n".join(lines)


@dataclass
class RoutePick:
    route: Route | None
    reason: str
    source: str  # "llm" or "rules"


def pick_route(routes: list[Route], st: State, deck_note: str) -> RoutePick:
    if not routes:
        return RoutePick(None, "no route found", "rules")
    if len(routes) == 1:
        return RoutePick(routes[0], "the only route", "rules")
    ans = llm.ask(ROUTE_SYSTEM, route_prompt(routes, st, deck_note), kind=f"route, act {st.act}",
                  options={**llm.OPTIONS, "num_predict": 200})
    if isinstance(ans, dict):
        try:
            k = int(ans.get("route"))
        except (TypeError, ValueError):
            k = 0
        if 1 <= k <= len(routes):
            return RoutePick(routes[k - 1], str(ans.get("reason", ""))[:300], "llm")
    return RoutePick(routes[0], "highest score by the guide's rules (the LLM gave no usable answer)", "rules")


def should_replan(st: State, last: State | None, came_from: str) -> str | None:
    """Why the route should be planned again at this fork, or None to keep following it."""
    if last is None:
        return "no plan yet"
    if came_from == "elite":
        return "after an elite"
    if st.hp / max(1, st.max_hp) < 0.5 <= last.hp / max(1, last.max_hp):
        return "HP fell below half"
    if (st.gold >= 280) != (last.gold >= 280):
        return "gold changed the shop plan"
    return None
