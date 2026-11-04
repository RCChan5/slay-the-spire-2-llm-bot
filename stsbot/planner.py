"""Choose this turn's plays by trying every order of playable cards and scoring the result.

The simulation is deliberately simple: damage (x1.5 on Vulnerable), block against the enemies' shown
intents (x0.75 when they are Weak), Strength added to later hits, and rough future values for debuffs,
powers and draws. Cards whose text was not understood are left out rather than guessed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .screen import Combat

ENERGY_LEFT = 0.02  # tie-breaker only: far below a point of damage or HP
KILL_BONUS = 3.0  # a tie-breaker: a kill counts mainly through the damage that enemy no longer deals
HP_LOSS_WEIGHT = 10.0  # user rule: block first at any HP; HP lost outweighs damage dealt
VULN_VALUE = 2.0  # per stack per living enemy (extra damage on later turns)
WEAK_VALUE = 1.5
POWER_VALUE = 7.0
STRENGTH_VALUE = 3.0
DRAW_VALUE = 1.5


@dataclass(frozen=True)
class Action:
    card: int  # index into the hand as read
    target: int | None  # enemy index, or None


@dataclass
class Plan:
    actions: list[Action] = field(default_factory=list)
    score: float = 0.0
    why: str = ""
    block_after: int = 0  # block once the plan is played (for the potion emergency check)


@dataclass
class _Foe:
    hp: int
    incoming: int
    vuln: int = 0
    weak: int = 0  # applied this turn only: the shown intent already counts Weak it had before
    block: int = 0


def _score(foes: list[_Foe], start: list[_Foe], block: int, strength: int, powers: int, draws: int,
           self_damage: int = 0) -> tuple[float, str]:
    dealt = sum(max(0, s.hp - f.hp) for s, f in zip(start, foes))
    kills = sum(1 for s, f in zip(start, foes) if s.hp > 0 and f.hp <= 0)
    incoming = sum(int(f.incoming * (0.75 if f.weak else 1.0)) for f in foes if f.hp > 0)
    incoming += self_damage  # status cards in hand that hurt at the end of the turn (Infection, Burn)
    loss = max(0, incoming - block)
    alive = [f for f in foes if f.hp > 0]
    debuffs = sum(min(f.vuln, 3) * VULN_VALUE + min(f.weak, 3) * WEAK_VALUE for f in alive)
    if not alive:
        loss = 0  # the fight ends before they act
        debuffs = 0
    s = dealt + kills * KILL_BONUS - loss * HP_LOSS_WEIGHT + debuffs + powers * POWER_VALUE \
        + strength * STRENGTH_VALUE + draws * DRAW_VALUE
    why = f"deal {dealt}, kill {kills}, take {loss} of {incoming}"
    return s, why


def plan_turn(c: Combat) -> Plan:
    start = [_Foe(e.hp, e.incoming, e.statuses.get("Vulnerable", 0), 0, e.block) for e in c.enemies]
    self_damage = 0
    for card in c.hand:
        m = re.search(r"end of your turn.*?take\s*(\d+)\s*damage", card.effects.text if card.effects else "", re.I)
        if m:
            self_damage += int(m.group(1))
    hand = c.hand
    best = Plan(score=_score(start, start, c.block, 0, 0, 0, self_damage)[0], why="end turn", block_after=c.block)
    best.why = _score(start, start, c.block, 0, 0, 0, self_damage)[1]
    seen: set = set()

    def go(used: frozenset, energy: int, foes: list[_Foe], block: int, strength: int, powers: int, draws: int,
           actions: list[Action]):
        nonlocal best
        key = (tuple(sorted(hand[i].name for i in used)), energy, tuple((f.hp, f.vuln, f.weak, f.block) for f in foes),
               block, strength)
        if key in seen:
            return
        seen.add(key)
        s, why = _score(foes, start, block, strength, powers, draws, self_damage)
        s += ENERGY_LEFT * energy  # equal outcome for less energy: the most efficient block (user rule)
        if s > best.score + 1e-9:
            best = Plan(list(actions), s, why, block)
        if all(f.hp <= 0 for f in foes):
            return
        tried: set = set()
        for i, card in enumerate(hand):
            e = card.effects
            if i in used or e is None or not e.known or e.unplayable:
                continue
            cost = card.cost if card.cost is not None else 99
            if cost > energy:
                continue
            targets = [j for j, f in enumerate(foes) if f.hp > 0] if e.needs_target else [None]
            for t in targets:
                sig = (card.name, t)
                if sig in tried:
                    continue  # two copies of a card at one target lead to the same states
                tried.add(sig)
                nf = [_Foe(f.hp, f.incoming, f.vuln, f.weak, f.block) for f in foes]
                hit_targets = [j for j, f in enumerate(nf) if f.hp > 0] if e.all_enemies else ([t] if t is not None else [])
                if e.damage:
                    for j in hit_targets:
                        per = e.damage + strength
                        if nf[j].vuln:
                            per = int(per * 1.5)
                        for _ in range(e.hits):
                            soak = min(nf[j].block, per)
                            nf[j].block -= soak
                            nf[j].hp -= per - soak
                for j in hit_targets:
                    nf[j].vuln += e.vulnerable
                    nf[j].weak += e.weak
                go(used | {i}, energy - cost + e.energy, nf, block + e.block, strength + e.strength,
                   powers + (1 if e.kind == "Power" else 0), draws + e.draw, actions + [Action(i, t)])

    go(frozenset(), c.energy, start, c.block, 0, 0, 0, [])
    return best


def describe(c: Combat, p: Plan) -> str:
    if not p.actions:
        return f"End turn ({p.why})"
    steps = []
    for a in p.actions:
        name = c.hand[a.card].name
        steps.append(name if a.target is None else f"{name} -> enemy {a.target + 1}")
    return " , ".join(steps) + f", end turn ({p.why})"
