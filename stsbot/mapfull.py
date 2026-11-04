"""Read the whole act map by scrolling it, and draw on it (the user's route planning, 2026-11-04).

The act map is about three screens tall. It scrolls in steady steps (3 wheel notches = 0.222 of the
window height, measured at 2562x1440), so the screen is read from the bottom up, one step at a time, and
the step is checked against the picture itself (phase correlation). Every room is placed in map
coordinates: its y on screen plus how far the map was scrolled, in window heights (bigger = higher up).
Rooms seen on two screens are merged; paths between rooms are read on a screen where both are visible.

Drawing uses the map pen (right-drag), which draws red in single player, segment by segment, scrolling
when the next room is off screen.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from .mapread import Room, find_rooms, path_dots, ring

NOTCHES = 3  # wheel notches per step
STEP = 0.2222  # window heights the map moves per step (measured; checked on every step)
VIEW_Y0, VIEW_Y1 = 0.10, 0.90  # where rooms are trusted on screen (top bar and bottom tools left out)
MAX_STEPS = 16
ROW_GAP = 0.05  # rooms in one row sit within this of each other (window heights)
CLEAR_BUTTON = (0.1148, 0.9306)  # the broom: "Clear Drawings"
MAP_CENTER = (0.5, 0.5)


@dataclass
class FullMap:
    rooms: list[Room]  # y is in map coordinates: screen y minus the scroll (bottom of the act ~0.7)
    rows: list[list[int]]  # bottom row first
    offsets: list[float] = field(default_factory=list)  # scroll of each screen read (window heights)

    def screen_y(self, i: int, scroll: float) -> float:
        """Where room i is on screen when the map is scrolled up by `scroll` window heights."""
        return self.rooms[i].y + scroll


def _gray_band(img: np.ndarray) -> np.ndarray:
    H, W = img.shape[:2]
    return cv2.cvtColor(img[int(0.1 * H):int(0.95 * H), int(0.2 * W):int(0.8 * W)],
                        cv2.COLOR_BGR2GRAY).astype(np.float32)


def measured_shift(prev: np.ndarray, cur: np.ndarray) -> float:
    """How far the picture moved down between two screens, in window heights (0 = it did not move)."""
    a, b = _gray_band(prev), _gray_band(cur)
    (_, dy), _ = cv2.phaseCorrelate(a, b)
    return dy / prev.shape[0]


def capture(win, inputs, grab, settle: float = 0.6) -> tuple[list[np.ndarray], list[float]]:
    """Scroll to the bottom, then read screens going up until the map stops moving. Returns the screens
    and their scroll offsets (window heights). Leaves the map scrolled back to the bottom."""
    inputs.move(win, *MAP_CENTER)
    time.sleep(0.15)
    inputs.wheel(win, -NOTCHES * MAX_STEPS)
    time.sleep(settle)
    frames, offsets = [grab(win)], [0.0]
    for _ in range(MAX_STEPS):
        inputs.wheel(win, NOTCHES)
        time.sleep(settle)
        img = grab(win)
        shift = measured_shift(frames[-1], img)
        if abs(shift) < 0.01:
            break  # the top of the map
        if abs(shift - STEP) > 0.03:
            shift = STEP  # a poor correlation (big plain areas): the known step is safer
        frames.append(img)
        offsets.append(offsets[-1] + shift)
    inputs.wheel(win, -NOTCHES * MAX_STEPS)
    time.sleep(settle)
    return frames, offsets


def build(frames: list[np.ndarray], offsets: list[float], min_path: float = 0.3) -> FullMap:
    """Rooms and paths from the screens, merged in map coordinates."""
    rooms: list[Room] = []
    seen_in: list[list[tuple[int, Room]]] = []  # per room: (frame, the room as found on that frame)
    for f, (img, off) in enumerate(zip(frames, offsets)):
        H, W = img.shape[:2]
        for r in find_rooms(img):
            if not (VIEW_Y0 < r.y < VIEW_Y1):
                continue
            my = r.y - off
            match = next((k for k, q in enumerate(rooms) if q.kind == r.kind and abs(q.x - r.x) < 0.02
                          and abs(q.y - my) < 0.025), None)
            if match is None:
                r.visited = ring(img, r.x, r.y) > 0.5
                r.reachable = not r.visited and r.dark > 0.3
                rooms.append(Room(r.kind, r.x, my, r.score, r.dark, r.reachable, r.visited))
                seen_in.append([(f, r)])
            else:
                seen_in[match].append((f, r))
    # Rows: rooms within ROW_GAP of each other in map y, bottom first (largest y first).
    order = sorted(range(len(rooms)), key=lambda i: -rooms[i].y)
    rows: list[list[int]] = []
    for i in order:
        if rows and abs(rooms[rows[-1][0]].y - rooms[i].y) < ROW_GAP:
            rows[-1].append(i)
        else:
            rows.append([i])
    # Paths between neighbouring rows, read on a screen showing both rooms.
    for lo, hi in zip(rows, rows[1:]):
        for i in lo:
            for j in hi:
                if abs(rooms[i].x - rooms[j].x) > 0.2:
                    continue
                frames_i = {f: r for f, r in seen_in[i]}
                both = [(f, frames_i[f], r) for f, r in seen_in[j] if f in frames_i]
                if any(path_dots(frames[f], a, b) >= min_path for f, a, b in both):
                    rooms[i].up.append(j)
    return FullMap(rooms, rows, list(offsets))


def scroll_to(win, inputs, steps_up: int, settle: float = 0.5, moved=None):
    """From the bottom of the map, scroll up this many steps. `moved` is called after the pointer moves
    (the bot records where it left the mouse, so its own moves are not taken for the user's)."""
    inputs.move(win, *MAP_CENTER)
    if moved:
        moved()
    time.sleep(0.1)
    inputs.wheel(win, -NOTCHES * MAX_STEPS)
    time.sleep(settle)
    if steps_up > 0:
        inputs.wheel(win, NOTCHES * steps_up)
        time.sleep(settle)


def draw_route(win, inputs, fm: FullMap, route: list[int], start: tuple[float, float] | None = None,
               guard=None, after_stroke=None, clear: bool = True, step_time: float = 0.012) -> int:
    """Draw a red line through the rooms of the route (bottom to top), scrolling as needed. `start` is an
    optional point in map coordinates to begin at (the room the player stands on). Returns segments drawn.
    Ends scrolled back to the bottom."""
    if clear:
        inputs.click(win, *CLEAR_BUTTON)  # old route lines (and pictures) go
        if after_stroke:
            after_stroke()
        time.sleep(0.4)
    pts = ([start] if start else []) + [(fm.rooms[i].x, fm.rooms[i].y) for i in route]
    steps, drawn = 0, 0
    scroll_to(win, inputs, 0, moved=after_stroke)
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        # Scroll up until both ends of the segment are on screen.
        while by + steps * STEP < VIEW_Y0 + 0.03 and steps < MAX_STEPS:
            steps += 1
            inputs.move(win, *MAP_CENTER)
            if after_stroke:
                after_stroke()
            inputs.wheel(win, NOTCHES)
            time.sleep(0.45)
        sa, sb = ay + steps * STEP, by + steps * STEP
        if sa > 0.97:  # the start fell off the bottom: begin the segment at the screen edge
            t = (sa - 0.97) / max(1e-6, sa - sb)
            ax, sa = ax + (bx - ax) * t, 0.97
        if guard:
            guard()
        n = max(8, int(abs(sb - sa) * 60 + abs(bx - ax) * 60))
        line = [(ax + (bx - ax) * k / n, sa + (sb - sa) * k / n) for k in range(n + 1)]
        inputs.polyline(win, line, step_time=step_time, right=True)
        if after_stroke:
            after_stroke()
        drawn += 1
    scroll_to(win, inputs, 0, moved=after_stroke)
    return drawn
