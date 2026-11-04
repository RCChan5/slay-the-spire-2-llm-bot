"""The bot loop: read the screen, plan, then advise (print) or play (Windows input).

    python -m stsbot              # advise only: prints the best plays, never touches the game
    python -m stsbot --play       # plays combat turns itself
    python -m stsbot --play --turns 3

Stops by itself when you move the mouse, when the game is not the window in front, or on Ctrl+C.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import re
import sys
import time
from pathlib import Path

import difflib

import cv2
import numpy as np

from . import inputs
from .cards import effects_for
from .ocr import Ocr
from .draft import choose
from .mapread import read_map
from .planner import describe, plan_turn
from .potions import choose_potion, filled_slots, from_tooltip, slot_count
from .builds import deck_builds
from .route import RunInfo, choose_room
from .run import Run, read_top_bar
from .screen import (DIGITS, FRAC, Card, Combat, assign_intents, join_text, parse_intent_tooltip,
                     read_card_choice, read_combat, screen_kind)
from .status import StatusBook, icon_center, name_from_tooltip, red_icon
from .window import GameWindow, find_game, grab, is_foreground, user32

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
END_TURN = (0.892, 0.825)
LOOT_PROCEED = (0.89, 0.76)
CHOICE_SKIP = (0.5, 0.85)
REST = (0.5, 0.3)  # where the pointer waits, away from cards and tooltips
KIND_WORDS = {"attack": "Attack", "skill": "Skill", "power": "Power", "curse": "Curse", "status": "Status"}


class UserTookOver(Exception):
    pass


class Stuck(Exception):
    """Something the bot cannot get past by itself; it stops so the user can look."""


class Bot:
    def __init__(self, play: bool, max_turns: int | None = None, resume: bool = True, still_secs: float = 5.0):
        self.play = play
        self.resume = resume
        self.still_secs = still_secs
        self.max_turns = max_turns
        self.ocr = Ocr()
        self.win: GameWindow | None = None
        self.text_cache: dict[tuple[int, str], tuple[str, str]] = {}
        self.last_pointer: tuple[int, int] | None = None
        self.turns_played = 0
        self.state = Run.load()
        self.last_note = None
        self.loot_clicks: dict[str, int] = {}
        self.map_tries = 0
        self.statuses = StatusBook()
        self.intent_cache: dict[tuple, tuple[bool, int, int]] = {}
        self.blocked: set[tuple[int, str]] = set()
        self.potion_cache: dict[tuple, object] = {}  # (turn, slot) -> Potion  # (turn, card) the game would not let it play
        LOGS.mkdir(exist_ok=True)
        self.log_path = LOGS / time.strftime("%Y%m%d.jsonl")

    # ---------- helpers
    def log(self, **rec):
        rec["t"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def say(self, msg: str):
        print(time.strftime("%H:%M:%S"), msg, flush=True)

    def pointer(self) -> tuple[int, int]:
        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def guard(self):
        """Stop if the user moved the mouse since the bot last did."""
        if self.last_pointer is not None:
            x, y = self.pointer()
            if abs(x - self.last_pointer[0]) > 25 or abs(y - self.last_pointer[1]) > 25:
                self.log(kind="stop", reason="pointer moved", left_at=self.last_pointer, now=(x, y))
                raise UserTookOver(f"mouse moved by hand (left at {self.last_pointer}, now at {(x, y)})")
        if not is_foreground(self.win):
            raise UserTookOver("game is not the window in front")

    def wait_until_free(self, why: str):
        """Paused because the user took the mouse: carry on once the game is in front and the mouse has
        been still for a few seconds."""
        self.say(f"paused: {why}. Resumes when the game is in front and the mouse is still for "
                 f"{self.still_secs:.0f} s (Ctrl+C to quit)")
        self.log(kind="pause", reason=why)
        last, still_since = self.pointer(), time.time()
        while True:
            time.sleep(0.25)
            now = self.pointer()
            if abs(now[0] - last[0]) > 3 or abs(now[1] - last[1]) > 3 or not is_foreground(self.win):
                last, still_since = now, time.time()
                continue
            if time.time() - still_since >= self.still_secs:
                break
        self.remember_pointer()
        self.text_cache.clear()  # the user may have played cards meanwhile
        self.intent_cache.clear()
        self.say("resumed")
        self.log(kind="resume")

    def remember_pointer(self):
        self.last_pointer = self.pointer()

    def move(self, fx, fy):
        self.guard()
        inputs.move(self.win, fx, fy)
        self.remember_pointer()

    def frame(self) -> np.ndarray:
        return grab(self.win)

    def settled_frame(self, timeout: float = 4.0) -> np.ndarray:
        """Wait until the picture stops changing (cards dealt, animations done)."""
        prev = cv2.resize(self.frame(), (320, 180))
        t0 = time.time()
        while True:
            time.sleep(0.25)
            cur_full = self.frame()
            cur = cv2.resize(cur_full, (320, 180))
            diff = float(np.mean(cv2.absdiff(prev, cur)))
            if diff < 1.2 or time.time() - t0 > timeout:
                return cur_full
            prev = cur

    def read(self, img):
        H, W = img.shape[:2]
        lines = self.ocr.read(img)
        return lines, W, H

    # ---------- card text
    def card_text(self, c: Combat, card: Card) -> tuple[str, str]:
        """Hover the card and read its kind and text from the raised card."""
        key = (c.turn, card.name)
        if key in self.text_cache:
            return self.text_cache[key]
        if not self.play:
            # Advise mode never moves the mouse; known starter text is used instead.
            return "", ""
        self.move(card.x, 0.9)
        time.sleep(0.35)
        img = self.frame()
        H, W = img.shape[:2]
        x0, x1 = int(max(0, card.x - 0.11) * W), int(min(1, card.x + 0.11) * W)
        y0, y1 = int(0.79 * H), int(0.975 * H)
        lines = self.ocr.read(img[y0:y1, x0:x1])
        kind, body_y, parts = "", None, []
        for l in lines:
            w = l.text.strip().lower()
            if w in KIND_WORDS and not kind:
                kind, body_y = KIND_WORDS[w], l.box[1] + l.box[3]
        for l in lines:
            if body_y is not None and l.box[1] >= body_y - 2 and l.text.strip().lower() not in KIND_WORDS:
                parts.append(l.text)
        out = (kind, " ".join(parts))
        self.text_cache[key] = out
        return out

    # ---------- combat details: small numbers, intents, statuses
    def crop_read(self, img, x0, x1, y0, y1, scale):
        """OCR a region (fractions) and return (text, fx, fy) in window fractions, health bars left out."""
        H, W = img.shape[:2]
        out = []
        for l in self.ocr.read(img[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)], scale=scale):
            if FRAC.match(l.text.strip()):
                continue
            out.append((l.text.strip(), x0 + l.center[0] / W, y0 + l.center[1] / H))
        return out

    def tooltip(self, fx, fy, region) -> str:
        """Hover a point and read the text in region (x0, x1, y0, y1 fractions)."""
        self.move(fx, fy)
        time.sleep(0.45)
        img = self.frame()
        H, W = img.shape[:2]
        x0, x1, y0, y1 = (max(0, region[0]), min(1, region[1]), max(0, region[2]), min(1, region[3]))
        lines = self.ocr.read(img[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)])
        return join_text(lines, H)

    def enrich(self, img, c: Combat):
        """Small numbers the full-screen read misses, intents as attack or not, and status names."""
        if c.enemies:
            assign_intents(c.enemies, self.crop_read(img, 0.45, 1.0, 0.12, 0.665, 2.0))
        owners = [(c.player_x, c)] + [(e.x, e) for e in c.enemies]
        for x, who in owners:
            if who.status_slots:
                continue
            for t, fx, fy in self.crop_read(img, max(0, x - 0.1), min(1, x + 0.1), 0.71, 0.77, 3.0):
                if DIGITS.match(t):
                    who.status_slots.append((fx, fy, int(t)))
        hovered = False
        for x, who in owners:
            for fx, fy, n in who.status_slots:
                name = self.statuses.identify(img, fx, fy)
                if name is None and self.play:
                    ix, iy = icon_center(fx, fy)
                    text = self.tooltip(ix, iy, (ix - 0.3, ix + 0.3, iy - 0.35, iy + 0.12))
                    hovered = True
                    name = name_from_tooltip(text)
                    if name:
                        self.statuses.learn(name, img, fx, fy)
                        self.say(f"  learned status icon: {name}")
                    else:
                        self.say(f"  status icon not recognized (tooltip: {text[:80]!r})")
                who.statuses[name or "?"] = who.statuses.get(name or "?", 0) + n
        for i, e in enumerate(c.enemies):
            if e.intent_pos is None:
                continue
            nx, ny = e.intent_pos
            key = (c.turn, i, e.intent_damage, e.hp)
            if key in self.intent_cache:
                e.intent_attack, dmg, hits = self.intent_cache[key]
            elif self.play:
                text = self.tooltip(nx + 0.016, ny - 0.02, (nx - 0.3, nx + 0.08, ny - 0.1, ny + 0.14))
                hovered = True
                attack, dmg, hits = parse_intent_tooltip(text)
                e.intent_text = text
                e.intent_attack = attack
                self.intent_cache[key] = (attack, dmg, hits)
            else:
                e.intent_attack, dmg, hits = red_icon(img, nx, ny), 0, 1
            if e.intent_attack and dmg:
                e.intent_damage, e.intent_hits = dmg, hits
        if hovered:
            self.move(*REST)
            time.sleep(0.2)

    def card_was_played(self, before: Combat) -> bool:
        """After a drag: did energy drop or the hand shrink? (A missed drop sends the card back.)"""
        img = self.settled_frame(timeout=2.5)
        lines, W, H = self.read(img)
        if screen_kind(lines, W, H) != "combat":
            return True  # the fight ended or a choice opened
        after = read_combat(lines, W, H)
        if after is None:
            return True
        return after.energy != before.energy or len(after.hand) < len(before.hand) or             [e.hp for e in after.enemies] != [e.hp for e in before.enemies]

    def potion_step(self, img, c: Combat, plan) -> bool:
        """Use a potion when the belt is full (keep one slot open) or to survive. True if one was used."""
        filled = filled_slots(img, self.state.ascension)
        if not filled:
            return False
        slots = slot_count(self.state.ascension)
        incoming = sum(e.incoming for e in c.enemies if e.hp > 0)
        if len(filled) < slots and max(0, incoming - plan.block_after) < c.hp:
            return False  # room on the belt and no danger: keep them
        potions = []
        for i in filled:
            key = (c.turn, i)
            if key not in self.potion_cache:
                from .potions import SLOT_X, SLOT_Y
                text = self.tooltip(SLOT_X[i], SLOT_Y, (SLOT_X[i] - 0.03, SLOT_X[i] + 0.32, 0.07, 0.26))
                self.potion_cache[key] = from_tooltip(i, text)
            potions.append(self.potion_cache[key])
        self.move(*REST)
        ch = choose_potion(potions, slots, incoming, plan.block_after, c.hp, c.max_hp, [e.hp for e in c.enemies])
        if ch.why:
            self.say("  potion: " + ch.why)
        if ch.potion is None:
            return False
        self.log(kind="potion", potion=ch.potion.name, text=ch.potion.text, why=ch.why)
        self.guard()
        inputs.click(self.win, ch.potion.x, 0.0356)
        self.remember_pointer()
        time.sleep(0.5)
        self.guard()
        inputs.click(self.win, *ch.potion.use_point)
        self.remember_pointer()
        time.sleep(0.5)
        if ch.target is not None:
            self.guard()
            inputs.click(self.win, *c.enemies[ch.target].body_point)
            self.remember_pointer()
        self.move(*REST)
        time.sleep(0.8)
        after = filled_slots(self.frame(), self.state.ascension)
        if ch.potion.slot in after:
            inputs.key(self.win, "esc")  # the menu or aiming is still open: back out
            self.say("  the potion was not used (menu closed); playing cards instead")
            self.potion_cache.clear()
            return False
        self.potion_cache.clear()
        return True

    # ---------- combat
    def combat_step(self, img, lines, W, H) -> bool:
        """One decision in combat. Returns True if the bot acted (so the screen will change)."""
        c = read_combat(lines, W, H)
        if c is None:
            return False
        # Names clipped by OCR ("Pommel Stril") are put right from the tracked deck.
        known = {d.name for d in self.state.deck.cards}
        for card in c.hand:
            if card.name not in known:
                match = difflib.get_close_matches(card.name, known, n=1, cutoff=0.75)
                if match:
                    card.name = match[0]
        self.enrich(img, c)
        saved = {d.name: (d.kind, d.text) for d in self.state.deck.cards}
        costs = {d.name: d.cost for d in self.state.deck.cards if d.cost is not None}
        for card in c.hand:
            kind, text = self.card_text(c, card)
            card.effects = effects_for(card.name, text, kind, saved)
            if card.cost is None and card.name in costs:
                card.cost = costs[card.name]
            if (c.turn, card.name) in self.blocked:
                card.effects.unplayable = True
        if self.play and c.hand:
            self.move(*REST)
            time.sleep(0.2)
        plan = plan_turn(c)
        self.say(c.summary())
        self.say("  plan: " + describe(c, plan))
        unknown = [x.name for x in c.hand if x.effects and not x.effects.known]
        if unknown:
            self.say(f"  not understood (left out): {', '.join(sorted(set(unknown)))}")
        self.log(kind="combat", state=c.summary(), plan=describe(c, plan), score=round(plan.score, 2),
                 cards={x.name: x.effects.text for x in c.hand if x.effects}, play=self.play)
        if not self.play:
            return False
        if self.potion_step(img, c, plan):
            return True
        if plan.actions:
            a = plan.actions[0]
            card = c.hand[a.card]
            drops = c.enemies[a.target].drop_points if a.target is not None else [(0.5, 0.42), (0.5, 0.3)]
            for i, target in enumerate(drops):
                self.guard()
                inputs.drag(self.win, card.grab_point, target)
                self.remember_pointer()
                self.move(*REST)
                if self.card_was_played(c):
                    break
                self.say(f"  {card.name} did not play (drop {i + 1} of {len(drops)} missed)")
            else:
                self.blocked.add((c.turn, card.name))
                self.say(f"  {card.name} would not play; leaving it out this turn")
                self.log(kind="play_failed", card=card.name, turn=c.turn)
        else:
            self.guard()
            inputs.click(self.win, *END_TURN)
            self.remember_pointer()
            self.move(*REST)
            self.turns_played += 1
            self.text_cache.clear()
            self.intent_cache.clear()
            time.sleep(1.0)
        return True

    # ---------- rewards
    def loot_step(self, lines, W, H) -> bool:
        """Loot screen: take each reward top to bottom (the card reward opens the card choice), then go on."""
        rows = [l for l in lines if 0.4 < l.center[0] / W < 0.62 and 0.33 < l.center[1] / H < 0.68
                and "loot" not in l.text.lower() and re.search(r"[A-Za-z]{3}", l.text)]
        rows.sort(key=lambda l: l.center[1])
        todo = [r for r in rows if self.loot_clicks.get(r.text, 0) < 2]
        self.say("loot: " + (", ".join(r.text for r in rows) or "nothing left"))
        if not self.play:
            return False
        self.guard()
        if todo:
            r = todo[0]
            self.loot_clicks[r.text] = self.loot_clicks.get(r.text, 0) + 1
            inputs.click(self.win, r.center[0] / W, r.center[1] / H)
        else:
            if rows:
                self.say("  left behind (could not take): " + ", ".join(r.text for r in rows))
            inputs.click(self.win, *LOOT_PROCEED)
            self.loot_clicks.clear()
        self.remember_pointer()
        self.move(*REST)
        time.sleep(0.8)
        return True

    def card_choice_step(self, img, lines, W, H) -> bool:
        offers = read_card_choice(lines, W, H)
        if not offers:
            return False
        # Card text is small: read each card's text again at 2x so small numbers are not lost.
        for o in offers:
            x0, x1 = int((o.x - 0.075) * W), int((o.x + 0.075) * W)
            y0, y1 = int((o.y + 0.15) * H), int((o.y + 0.3) * H)
            y0, y1 = int((o.y + 0.14) * H), int((o.y + 0.27) * H)
            body = [l for l in self.ocr.read(img[y0:y1, x0:x1], scale=2.0)
                    if l.text.strip().lower() not in ("attack", "skill", "power")
                    and not re.match(r"^\d+\s*/\s*\d*$", l.text.strip())]
            if body:
                o.text = join_text(body, H)
        can_skip = any(l.text.strip().lower() == "skip" for l in lines)
        ch = choose(offers, self.state.deck, self.state.floor, can_skip)
        for o, (v, why) in zip(offers, ch.values):
            self.say(f"  {o.name} ({o.cost}) {v}: {o.text}" + (f"  [{'; '.join(why)}]" if why else ""))
        self.say("  " + ch.why)
        self.log(kind="card_choice", offers=[o.__dict__ for o in offers], values=[v for v, _ in ch.values],
                 bar=ch.bar, pick=None if ch.pick is None else offers[ch.pick].name, why=ch.why,
                 deck=len(self.state.deck.cards), floor=self.state.floor, play=self.play)
        if not self.play:
            return False
        self.guard()
        if ch.pick is None:
            inputs.click(self.win, *CHOICE_SKIP)
        else:
            o = offers[ch.pick]
            inputs.click(self.win, o.x, o.y + 0.12)
            self.state.add(o.name, o.kind, o.text, o.cost)
        self.remember_pointer()
        self.move(*REST)
        time.sleep(1.0)
        return True

    # ---------- map
    def map_step(self, img, lines, W, H) -> bool:
        m = read_map(img)
        s = self.state
        if s.floor == 0 or not s.hp:
            return False
        info = RunInfo(s.hp, s.max_hp, s.gold, s.floor, s.ascension)
        ch = choose_room(m, info, s.deck)
        reach = [f"{m.rooms[i].kind}" for i, r in enumerate(m.rooms) if r.reachable]
        self.say(f"map: {len(m.rooms)} rooms, reachable {reach}; HP {s.hp}/{s.max_hp}, gold {s.gold}, "
                 f"floor {s.floor}, A{s.ascension}, deck {len(s.deck.cards)}; {deck_builds(s.deck.cards).describe()}")
        self.say("  route: " + ch.why)
        self.log(kind="map", reachable=reach, choice=None if ch.room is None else m.rooms[ch.room].kind,
                 why=ch.why, score=round(ch.score, 2), play=self.play)
        if not self.play or ch.room is None:
            return False
        if self.map_tries >= 3:
            self.say("  clicked the map 3 times without leaving it; stopping so you can look")
            raise Stuck("map click had no effect")
        r = m.rooms[ch.room]
        self.guard()
        inputs.click(self.win, r.x, r.y)
        self.remember_pointer()
        self.move(*REST)
        self.map_tries += 1
        time.sleep(1.5)
        return True

    # ---------- main loop
    def run(self):
        self.win = find_game()
        if self.win is None:
            sys.exit("Slay the Spire 2 is not running.")
        self.say(f"found {self.win.title!r} {self.win.width}x{self.win.height}; mode: {'PLAY' if self.play else 'advise'}")
        if self.play:
            user32.SetForegroundWindow(self.win.hwnd)
            time.sleep(0.3)
            self.move(*REST)
        self.last_summary = None
        self.idle_since = time.time()
        try:
            while True:
                try:
                    if self.step():
                        return
                except (UserTookOver, inputs.NotInFront) as e:
                    if not (self.play and self.resume):
                        raise
                    self.wait_until_free(str(e))
                    self.idle_since = time.time()
        except (Stuck, UserTookOver, inputs.NotInFront) as e:
            self.say(f"stopped: {e}")
        except KeyboardInterrupt:
            self.say("stopped (Ctrl+C)")

    def step(self) -> bool:
        """One look at the screen and at most one action. Returns True when the bot should stop."""
        if self.max_turns is not None and self.turns_played >= self.max_turns:
            self.say(f"played {self.turns_played} turn(s); stopping as asked")
            return True
        if self.play:
            self.guard()
        img = self.settled_frame()
        lines, W, H = self.read(img)
        kind = screen_kind(lines, W, H)
        bar = read_top_bar(lines, W, H)
        if bar.floor is None:  # the floor number is small: read it again larger
            got = [t for t, fx, fy in self.crop_read(img, 0.42, 0.47, 0.0, 0.065, 2.0) if DIGITS.match(t)]
            bar.floor = int(got[0]) if got else None
        note = self.state.see(bar)
        if kind != "map":
            self.map_tries = 0
        if note and note != self.last_note:
            self.say("note: " + note)
            self.log(kind="note", note=note)
            self.last_note = note
        if kind in ("loot", "card_choice"):
            # OCR of the same screen varies a little between frames; compare what matters only.
            if kind == "card_choice":
                sig = kind + "|" + "|".join(o.name for o in read_card_choice(lines, W, H))
            else:
                sig = kind + "|" + "|".join(sorted(l.text for l in lines if 0.33 < l.center[1] / H < 0.68
                                                   and 0.4 < l.center[0] / W < 0.62))
            if self.play or sig != self.last_summary:
                self.last_summary = sig
                step = self.loot_step(lines, W, H) if kind == "loot" else self.card_choice_step(img, lines, W, H)
                if step:
                    self.idle_since = time.time()
            time.sleep(0.4)
            return False
        if kind == "combat":
            if self.play:
                self.combat_step(img, lines, W, H)
                self.idle_since = time.time()
            else:
                c = read_combat(lines, W, H)
                s = c.summary() if c else None
                if s and s != self.last_summary:
                    self.last_summary = s
                    self.combat_step(img, lines, W, H)
                time.sleep(0.5)
            return False
        if kind == "map":
            sig = f"map|{self.state.floor}|{self.state.hp}"
            if self.play or sig != self.last_summary:
                self.last_summary = sig
                if self.map_step(img, lines, W, H):
                    self.idle_since = time.time()
            time.sleep(0.5)
            return False
        if kind == "proceed" and self.play:
            btn = next((l for l in lines if l.text.strip().lower() == "proceed"), None)
            if btn is not None:
                self.say("proceed")
                self.guard()
                inputs.click(self.win, btn.center[0] / W, btn.center[1] / H)
                self.remember_pointer()
                self.move(*REST)
                time.sleep(1.0)
                return False
        if kind != self.last_summary:
            self.say(f"screen: {kind}" + ("" if kind in ("enemy_turn",) else " (not handled yet; waiting)"))
            self.last_summary = kind
        if self.play and kind not in ("enemy_turn", "unknown") and time.time() - self.idle_since > 20:
            self.say("this screen needs you; stopping")
            return True
        time.sleep(0.6)
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(prog="stsbot", description="Slay the Spire 2 bot (screen pixels + OCR)")
    ap.add_argument("--play", action="store_true", help="play combat and rewards (default: advise only)")
    ap.add_argument("--turns", type=int, default=None, help="stop after this many turns")
    ap.add_argument("--no-resume", action="store_true",
                    help="stop for good when you move the mouse (default: pause, resume once it is still)")
    ap.add_argument("--still", type=float, default=5.0, help="seconds of a still mouse before resuming")
    args = ap.parse_args(argv)
    Bot(play=args.play, max_turns=args.turns, resume=not args.no_resume, still_secs=args.still).run()
