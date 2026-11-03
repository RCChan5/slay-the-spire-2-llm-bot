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

import cv2
import numpy as np

from . import inputs
from .cards import effects_for
from .ocr import Ocr
from .planner import describe, plan_turn
from .screen import Card, Combat, read_combat, screen_kind
from .window import GameWindow, find_game, grab, is_foreground, user32

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
END_TURN = (0.892, 0.825)
REST = (0.5, 0.3)  # where the pointer waits, away from cards and tooltips
KIND_WORDS = {"attack": "Attack", "skill": "Skill", "power": "Power", "curse": "Curse", "status": "Status"}


class UserTookOver(Exception):
    pass


class Bot:
    def __init__(self, play: bool, max_turns: int | None = None):
        self.play = play
        self.max_turns = max_turns
        self.ocr = Ocr()
        self.win: GameWindow | None = None
        self.text_cache: dict[tuple[int, str], tuple[str, str]] = {}
        self.last_pointer: tuple[int, int] | None = None
        self.turns_played = 0
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
                raise UserTookOver("mouse moved by hand")
        if not is_foreground(self.win):
            raise UserTookOver("game is not the window in front")

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

    # ---------- combat
    def combat_step(self, img, lines, W, H) -> bool:
        """One decision in combat. Returns True if the bot acted (so the screen will change)."""
        c = read_combat(lines, W, H)
        if c is None:
            return False
        for card in c.hand:
            kind, text = self.card_text(c, card)
            card.effects = effects_for(card.name, text, kind)
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
        if plan.actions:
            a = plan.actions[0]
            card = c.hand[a.card]
            target = c.enemies[a.target].body_point if a.target is not None else (0.5, 0.42)
            self.guard()
            inputs.drag(self.win, card.grab_point, target)
            self.remember_pointer()
            self.move(*REST)
            time.sleep(0.5)
        else:
            self.guard()
            inputs.click(self.win, *END_TURN)
            self.remember_pointer()
            self.move(*REST)
            self.turns_played += 1
            self.text_cache.clear()
            time.sleep(1.0)
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
        last_summary = None
        idle_since = time.time()
        try:
            while True:
                if self.max_turns is not None and self.turns_played >= self.max_turns:
                    self.say(f"played {self.turns_played} turn(s); stopping as asked")
                    return
                if self.play:
                    self.guard()
                img = self.settled_frame()
                lines, W, H = self.read(img)
                kind = screen_kind(lines, W, H)
                if kind == "combat":
                    if self.play:
                        self.combat_step(img, lines, W, H)
                        idle_since = time.time()
                    else:
                        c = read_combat(lines, W, H)
                        s = c.summary() if c else None
                        if s and s != last_summary:
                            last_summary = s
                            self.combat_step(img, lines, W, H)
                        time.sleep(0.5)
                    continue
                if kind != last_summary:
                    self.say(f"screen: {kind}" + ("" if kind in ("enemy_turn",) else " (not handled yet; waiting)"))
                    last_summary = kind
                if self.play and kind not in ("enemy_turn", "unknown") and time.time() - idle_since > 20:
                    self.say("combat is over or this screen needs you; stopping")
                    return
                time.sleep(0.6)
        except UserTookOver as e:
            self.say(f"stopped: {e}")
        except inputs.NotInFront as e:
            self.say(f"stopped: {e}")
        except KeyboardInterrupt:
            self.say("stopped (Ctrl+C)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="stsbot", description="Slay the Spire 2 bot (screen pixels + OCR)")
    ap.add_argument("--play", action="store_true", help="play combat turns (default: advise only)")
    ap.add_argument("--turns", type=int, default=None, help="stop after this many turns")
    args = ap.parse_args(argv)
    Bot(play=args.play, max_turns=args.turns).run()
