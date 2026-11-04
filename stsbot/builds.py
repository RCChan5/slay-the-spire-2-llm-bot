"""Ironclad builds: which cards make each build work, how far the deck is into each, and which one it commits to.

Card lists and tiers come from Slay the Spire 2 build guides (FinalBoss 2026-06-25, PCGamesN 2026-04-08,
slay-the-spire-2.pages.dev); where the guides disagree the majority is used. A card not listed falls back
to keywords in its text, so new or unknown cards still lean toward a build.

Commitment: progress in a build = 3 per key card + 1 per support card (+0.5 per keyword-only match). The
deck commits to the leading build once it has at least COMMIT_AT progress and leads the next build by
COMMIT_LEAD. Before that it only leans toward the two leading builds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

COMMIT_AT = 5.0
COMMIT_LEAD = 2.0


@dataclass(frozen=True)
class Build:
    name: str
    key: frozenset
    support: frozenset
    keywords: str  # regex on card text for cards the lists do not name
    needs: tuple = ()  # what the build still has to find: "aoe", "block", "draw", "energy"


BUILDS = {
    "strength": Build("Strength stacking",
                      frozenset({"Demon Form", "Limit Break", "Inflame", "Spot Weakness"}),
                      frozenset({"Whirlwind", "Twin Strike", "Heavy Blade", "Reaper", "Double Tap", "Brand",
                                 "Sword Boomerang"}),
                      r"\bStrength\b(?!.*enemy gains)", ("aoe",)),
    "vulnerable": Build("Vulnerable",
                        frozenset({"Molten Fist", "Tremble", "Dismantle", "Uppercut", "Cruelty"}),
                        frozenset({"Taunt", "Colossus", "Dominate", "Thunderclap"}),
                        r"\bVulnerable\b", ("block",)),
    "block": Build("Barricade / Body Slam",
                   frozenset({"Barricade", "Body Slam", "Entrench", "Juggernaut"}),
                   frozenset({"Shrug It Off", "Flame Barrier", "Blood Wall", "Impervious", "Unmovable",
                              "Crimson Mantle", "Stone Armor", "Taunt", "Iron Wave"}),
                   r"\bBlock\b", ("draw",)),
    "exhaust": Build("Exhaust engine",
                     frozenset({"Corruption", "Feel No Pain", "Dark Embrace"}),
                     frozenset({"True Grit", "Burning Pact", "Second Wind", "Fiend Fire", "Ashen Strike",
                                "Pact's End", "Evil Eye", "Forgotten Ritual", "Havoc", "Brand", "Offering"}),
                     r"\bExhaust", ("aoe", "block")),
    "self_damage": Build("Self-damage / Rupture",
                         frozenset({"Rupture", "Inferno", "Crimson Mantle"}),
                         frozenset({"Bloodletting", "Offering", "Hemokinesis", "Brand", "Blood Wall", "Feed",
                                    "Berserk"}),
                         r"\b[Ll]ose \d+ HP", ("block",)),
    "strike": Build("Strike",
                    frozenset({"Perfected Strike", "Hellraiser"}),
                    frozenset({"Pommel Strike", "Twin Strike", "Ashen Strike", "Setup Strike", "Wild Strike"}),
                    r"Strike", ()),
}

# Generic strength of known Ironclad cards, on the draft value scale (basics are about 3).
TIER_VALUE = {"S": 8.0, "A": 6.5, "B": 5.0, "C": 3.5, "D": 2.5}
TIERS = {
    "S": ["Body Slam", "Headbutt", "Second Wind", "Feel No Pain", "Thrash", "Brand", "Offering", "Dark Embrace",
          "Barricade", "Demon Form", "Break", "Battle Trance", "Corruption", "Limit Break", "Whirlwind"],
    "A": ["Bloodletting", "Armaments", "Shrug It Off", "True Grit", "Ashen Strike", "Dismantle", "Burning Pact",
          "Taunt", "Pact's End", "Feed", "Fiend Fire", "Impervious", "Aggression", "Unmovable", "Inflame",
          "Pommel Strike", "Flame Barrier", "Blood Wall", "Rupture", "Inferno", "Crimson Mantle"],
    "B": ["Perfected Strike", "Twin Strike", "Uppercut", "Molten Fist", "Tremble", "Iron Wave", "Hellraiser",
          "Spot Weakness", "Heavy Blade", "Hemokinesis", "Entrench", "Juggernaut", "Evil Eye", "Cruelty"],
    "C": ["Wild Strike", "Reckless Charge", "Havoc", "Setup Strike"],
    "D": ["Sword Boomerang", "Thunderclap", "Grapple", "Rampage", "Fight Me!", "Mangle"],
}
CARD_TIER = {name: tier for tier, names in TIERS.items() for name in names}


def tier_value(name: str) -> float | None:
    """The card's tier as a value: from the user's tier list in context/ when it rates the card, else
    the built-in list."""
    base = name.rstrip("+")
    from . import context as cx
    t = cx.tier(base) if cx.available() else None
    if t == "F":
        t = "D"
    t = t or CARD_TIER.get(base)
    if t is None:
        return None
    return TIER_VALUE[t] + (0.8 if name.endswith("+") else 0.0)


def roles(name: str, text: str) -> dict[str, str]:
    """For each build this card belongs to: "key", "support" or "keyword"."""
    base = name.rstrip("+")
    out: dict[str, str] = {}
    for bid, b in BUILDS.items():
        if base in b.key:
            out[bid] = "key"
        elif base in b.support:
            out[bid] = "support"
        elif b.keywords and re.search(b.keywords, f"{base} {text}"):
            out[bid] = "keyword"
    return out


ROLE_POINTS = {"key": 3.0, "support": 1.0, "keyword": 0.5}
BASICS = {"Strike", "Defend", "Bash", "Ascender's Bane"}


@dataclass
class BuildState:
    progress: dict[str, float] = field(default_factory=dict)
    pieces: dict[str, list[str]] = field(default_factory=dict)
    committed: str | None = None
    leaning: list[str] = field(default_factory=list)

    def describe(self) -> str:
        if self.committed:
            b = BUILDS[self.committed]
            return f"build: {b.name} ({', '.join(self.pieces[self.committed])})"
        if self.leaning:
            return "build: not committed, leaning " + " / ".join(
                f"{BUILDS[b].name} {self.progress[b]:.1f}" for b in self.leaning)
        return "build: not committed yet"


def deck_builds(cards) -> BuildState:
    """cards: objects with name and text."""
    s = BuildState({b: 0.0 for b in BUILDS}, {b: [] for b in BUILDS})
    for c in cards:
        if c.name.rstrip("+") in BASICS:
            continue
        for bid, role in roles(c.name, c.text).items():
            s.progress[bid] += ROLE_POINTS[role]
            if role != "keyword":
                s.pieces[bid].append(c.name)
    order = sorted(BUILDS, key=lambda b: -s.progress[b])
    top, second = order[0], order[1]
    if s.progress[top] >= COMMIT_AT and s.progress[top] - s.progress[second] >= COMMIT_LEAD:
        s.committed = top
    s.leaning = [b for b in order[:2] if s.progress[b] > 0]
    return s


def build_bonus(name: str, text: str, state: BuildState, deck_needs: set[str]) -> tuple[float, list[str]]:
    """Extra value for a card in this deck's build, with reasons."""
    r = roles(name, text)
    why: list[str] = []
    bonus = 0.0
    if state.committed:
        b = state.committed
        role = r.get(b)
        if role == "key":
            bonus += 4.0
            why.append(f"key card for {BUILDS[b].name}")
        elif role == "support":
            bonus += 2.5
            why.append(f"supports {BUILDS[b].name}")
        elif role == "keyword":
            bonus += 1.0
            why.append(f"fits {BUILDS[b].name}")
        elif any(v == "key" for v in r.values()):
            bonus -= 1.5
            why.append(f"off-plan (another build's key card, deck is {BUILDS[b].name})")
        for need in BUILDS[b].needs:
            if need in deck_needs and _meets(need, text):
                bonus += 1.5
                why.append(f"{BUILDS[b].name} needs {need}")
    else:
        for b in state.leaning:
            role = r.get(b)
            if role:
                bonus += {"key": 2.0, "support": 1.0, "keyword": 0.5}[role] + 0.3 * state.progress[b]
                why.append(f"{role} for {BUILDS[b].name} (leaning)")
                break
        else:
            if any(v == "key" for v in r.values()):
                bonus += 0.8  # opens a build
                why.append("could start " + BUILDS[next(b for b, v in r.items() if v == "key")].name)
    return bonus, why


def _meets(need: str, text: str) -> bool:
    return {"aoe": bool(re.search(r"ALL enem", text, re.I)),
            "block": bool(re.search(r"Gain\s*\d+\s*Block", text)),
            "draw": bool(re.search(r"Draw\s*\d|Draw a card", text)),
            "energy": bool(re.search(r"Gain\s*\d+\s*Energy|\[E\]", text))}.get(need, False)
