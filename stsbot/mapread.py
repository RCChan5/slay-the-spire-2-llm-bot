"""Read the map: room icons and their types, which rooms are reachable, and the dotted paths between rooms.

Icons are found by matching the legend's own icons (cut from the same screen, so any resolution works)
against the map at a few sizes. Reachable rooms are drawn fully dark; the rest are faded. Visited rooms
carry an ink ring. Paths are the dotted lines: a straight line between two rooms in neighboring rows that
runs over enough dark dots is a path.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

KINDS = ["unknown", "merchant", "treasure", "rest", "enemy", "elite"]
# Legend icons, centers as fractions of the window (measured at 2562x1440).
LEGEND_X = 0.850
LEGEND_Y = {"unknown": 0.385, "merchant": 0.429, "treasure": 0.474, "rest": 0.518, "enemy": 0.563, "elite": 0.607}
LEGEND_HALF = 0.0115  # half the icon's height, as a fraction of the window height
MAP_X0, MAP_X1 = 0.17, 0.81  # the parchment, left of the legend
MAP_Y0, MAP_Y1 = 0.075, 1.0
SCALES = (1.15, 1.25, 1.35, 1.45, 1.55, 1.7, 1.85)  # reachable rooms pulse larger


@dataclass
class Room:
    kind: str
    x: float  # center, fractions of the window
    y: float
    score: float
    dark: float = 0.0  # how dark the icon is drawn (reachable rooms are darkest)
    reachable: bool = False
    visited: bool = False
    up: list[int] = field(default_factory=list)  # indices of rooms one row above that a path leads to


def legend_templates(img: np.ndarray) -> dict[str, np.ndarray]:
    H, W = img.shape[:2]
    h = int(LEGEND_HALF * H)
    out = {}
    for k, fy in LEGEND_Y.items():
        cx, cy = int(LEGEND_X * W), int(fy * H)
        out[k] = img[cy - h:cy + h, cx - h:cx + h]
    return out


def _gray(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def find_rooms(img: np.ndarray, min_score: float = 0.7) -> list[Room]:
    H, W = img.shape[:2]
    temps = legend_templates(img)
    x0, x1, y0, y1 = int(MAP_X0 * W), int(MAP_X1 * W), int(MAP_Y0 * H), int(MAP_Y1 * H)
    area = _gray(img[y0:y1, x0:x1])
    hits: list[Room] = []
    for kind, t in temps.items():
        tg = _gray(t)
        for s in SCALES:
            ts = cv2.resize(tg, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
            res = cv2.matchTemplate(area, ts, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res >= min_score)
            for yy, xx in zip(ys, xs):
                cx = (x0 + xx + ts.shape[1] / 2) / W
                cy = (y0 + yy + ts.shape[0] / 2) / H
                hits.append(Room(kind, cx, cy, float(res[yy, xx])))
    # Keep the best hit per spot.
    hits.sort(key=lambda r: -r.score)
    rooms: list[Room] = []
    r_min = 0.022  # rooms are farther apart than this (fraction of width)
    for h in hits:
        if all(abs(h.x - r.x) > r_min or abs(h.y - r.y) * H / W > r_min for r in rooms):
            rooms.append(h)
    for r in rooms:
        r.dark = darkness(img, r.x, r.y)
    return sorted(rooms, key=lambda r: (-r.y, r.x))


def darkness(img: np.ndarray, fx: float, fy: float, half: float = 0.012) -> float:
    """Share of clearly dark pixels on the icon: faded (unreachable) icons have few."""
    H, W = img.shape[:2]
    hw, hh = int(half * W), int(half * W)
    cx, cy = int(fx * W), int(fy * H)
    patch = _gray(img[max(0, cy - hh):cy + hh, max(0, cx - hw):cx + hw])
    return float((patch < 70).mean()) if patch.size else 0.0


def ring(img: np.ndarray, fx: float, fy: float) -> float:
    """Share of dark pixels on a circle around the icon: visited rooms carry an ink ring there."""
    H, W = img.shape[:2]
    g = _gray(img)
    cx, cy = fx * W, fy * H
    hits = n = 0
    for r in (0.021, 0.023, 0.025):
        for a in np.linspace(0, 2 * np.pi, 72, endpoint=False):
            x, y = int(cx + r * W * np.cos(a)), int(cy + r * W * np.sin(a))
            if 0 <= x < W and 0 <= y < H:
                n += 1
                hits += g[y, x] < 70
    return hits / max(1, n)


def rows_of(rooms: list[Room], gap: float = 0.07) -> list[list[int]]:
    """Rooms grouped into map rows, bottom row first."""
    order = sorted(range(len(rooms)), key=lambda i: -rooms[i].y)
    rows: list[list[int]] = []
    for i in order:
        if rows and abs(rooms[rows[-1][0]].y - rooms[i].y) < gap:
            rows[-1].append(i)
        else:
            rows.append([i])
    return rows


def path_dots(img: np.ndarray, a: Room, b: Room, skip: float = 0.017) -> float:
    """Share of points along the straight line a -> b (icons left out) that sit on a dark dot."""
    H, W = img.shape[:2]
    g = _gray(img)
    ax, ay, bx, by = a.x * W, a.y * H, b.x * W, b.y * H
    length = float(np.hypot(bx - ax, by - ay))
    if length < 1:
        return 0.0
    s0 = skip * W / length
    ts = np.linspace(s0, 1 - s0, 60)
    hit = 0
    for t in ts:
        x, y = int(ax + (bx - ax) * t), int(ay + (by - ay) * t)
        patch = g[max(0, y - 3):y + 4, max(0, x - 3):x + 4]
        hit += patch.size > 0 and patch.min() < 128  # faded dots ~117, parchment ~142
    return hit / len(ts)


@dataclass
class MapView:
    rooms: list[Room]
    rows: list[list[int]]
    current: int | None  # the room the player stands on (None before the first room)


def read_map(img: np.ndarray, min_path: float = 0.3) -> MapView:
    rooms = find_rooms(img)
    for r in rooms:
        r.visited = ring(img, r.x, r.y) > 0.5  # real rings 0.7+, the dark top bar alone ~0.3
        r.reachable = not r.visited and r.dark > 0.3
    rows = rows_of(rooms)
    for lo, hi in zip(rows, rows[1:]):
        for i in lo:
            for j in hi:
                if abs(rooms[i].x - rooms[j].x) < 0.2 and path_dots(img, rooms[i], rooms[j]) >= min_path:
                    rooms[i].up.append(j)
    visited = [i for i, r in enumerate(rooms) if r.visited]
    current = min(visited, key=lambda i: rooms[i].y) if visited else None
    return MapView(rooms, rows, current)


def boss_point(img: np.ndarray, region=(0.33, 0.67, 0.12, 0.6), min_share: float = 0.04) -> tuple[float, float] | None:
    """The boss: the large dark drawing at the top of the map. Its centre, or None if there is none."""
    H, W = img.shape[:2]
    x0, x1, y0, y1 = region
    g = _gray(img[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)])
    dark = (g < 60).astype(np.uint8)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, labels, stats, cent = cv2.connectedComponentsWithStats(dark)
    h, w = dark.shape
    # The black background around the parchment touches the edges of the search area; the boss does not.
    inner = [i for i in range(1, n) if stats[i, cv2.CC_STAT_TOP] > 0 and stats[i, cv2.CC_STAT_LEFT] > 0
             and stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH] < w
             and stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] < h]
    # The boss drawing breaks into several dark pieces (wings, middle): take them together.
    inner = [i for i in inner if stats[i, cv2.CC_STAT_AREA] > 0.003 * dark.size]
    total = sum(stats[i, cv2.CC_STAT_AREA] for i in inner)
    if total < min_share * dark.size:
        return None
    cx = sum(cent[i][0] * stats[i, cv2.CC_STAT_AREA] for i in inner) / total
    cy = sum(cent[i][1] * stats[i, cv2.CC_STAT_AREA] for i in inner) / total
    return x0 + cx / W, y0 + cy / H
