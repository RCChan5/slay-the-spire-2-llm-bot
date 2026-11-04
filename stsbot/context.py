"""The user's game knowledge in context/: every card, relic and monster, the card tier list, and the
Ironclad play guide. Looked up by name (OCR names are matched loosely), so each LLM decision gets only
the entries it needs: the whole folder is far too big for one prompt.
"""

from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTEXT = ROOT / "context"


def _load(name: str) -> dict:
    p = CONTEXT / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower().rstrip("+"))


@lru_cache(maxsize=1)
def _data():
    cards = _load("sts2_cards.json").get("cards", [])
    tiers = _load("sts2_card_tiers.json")
    monsters = _load("sts2_monsters.json").get("monsters", [])
    relics = _load("sts2_relics.json").get("relics", [])
    by_card = {_norm(c["name"]): c for c in cards}
    tier_by_id = tiers.get("by_id", {})
    by_monster = {_norm(m["name"]): m for m in monsters}
    by_relic = {_norm(r["name"]): r for r in relics}
    guide_path = CONTEXT / "ironclad_play_guide.md"
    guide = guide_path.read_text(encoding="utf-8") if guide_path.exists() else ""
    return by_card, tier_by_id, by_monster, by_relic, guide


def available() -> bool:
    return bool(_data()[0])


def _find(table: dict, name: str, cutoff: float = 0.8):
    key = _norm(name)
    if key in table:
        return table[key]
    m = difflib.get_close_matches(key, table.keys(), n=1, cutoff=cutoff)
    return table[m[0]] if m else None


def card(name: str) -> dict | None:
    return _find(_data()[0], name)


def proper_name(name: str) -> str:
    """The card's real name from an OCR read: "Body Slami" -> "Body Slam+" (the "+" is often read as t, i,
    l, f or 1), "Forgotten Ritu" -> "Forgotten Ritual". Unknown names come back unchanged."""
    name = name.strip()
    table = _data()[0]
    if _norm(name) in table:
        c = table[_norm(name)]
        return c["name"] + ("+" if name.endswith("+") else "")
    if len(name) > 3 and name[-1] in "tilf1|" and _norm(name[:-1]) in table:
        return table[_norm(name[:-1])]["name"] + "+"
    c = card(name)
    return c["name"] + ("+" if name.endswith("+") else "") if c else name


def tier(name: str) -> str | None:
    c = card(name)
    return _data()[1].get(c["id"]) if c else None


def monster(name: str) -> dict | None:
    return _find(_data()[2], name)


def relic(name: str) -> dict | None:
    return _find(_data()[3], name)


def card_line(name: str) -> str:
    """One line for a prompt: name, cost, type, tier, rules text (the upgraded text for "+" names)."""
    c = card(name)
    if c is None:
        return f"{name}: (not in the card list)"
    up = name.strip().endswith("+")
    cost = c.get("cost_upgraded" if up else "cost")
    text = c.get("text_upgraded" if up else "text") or ""
    t = tier(name)
    return (f"{name}: cost {cost if cost is not None else 'unplayable'}, {c.get('type', '?')}"
            + (f", tier {t}" if t else "") + f". {text}")


def monster_line(name: str) -> str:
    m = monster(name)
    if m is None:
        return ""
    moves = []
    for mv in (m.get("moves") or [])[:6]:
        if isinstance(mv, dict):
            label = mv.get("name") or mv.get("id") or ""
            desc = mv.get("text") or mv.get("description") or mv.get("effects") or ""
            moves.append(f"{label}: {json.dumps(desc, ensure_ascii=False)[:120] if not isinstance(desc, str) else desc[:120]}")
    powers = ", ".join(f"{p.get('power')} {p.get('amount')}" for p in (m.get("starting_powers") or [])
                       if isinstance(p, dict))
    return f"{m['name']} ({m.get('type', '?')})" + (f"; powers: {powers}" if powers else "") + \
        (f"; moves: {' | '.join(moves)}" if moves else "")


def relic_line(name: str) -> str:
    r = relic(name)
    return f"{r['name']}: {r.get('text', '')}" if r else ""


def guide_section(title_start: str) -> str:
    """A '## ...' section of the play guide whose title starts with the given words."""
    guide = _data()[4]
    parts = re.split(r"(?m)^## ", guide)
    for p in parts:
        if p.lower().startswith(title_start.lower()):
            return "## " + p.strip()
    return ""


BUILD_SECTIONS = {
    "Exhaust / infinite": "Build 1",
    "Self-damage": "Build 2",
    "Strength": "Build 3",
    "Barricade": "Build 4",
}


def bot_rules() -> str:
    return guide_section("Rules for the bot")


def build_overview() -> str:
    return guide_section("Build types at a glance")


def build_guide(build: str) -> str:
    key = BUILD_SECTIONS.get(build)
    return guide_section(key) if key else ""
