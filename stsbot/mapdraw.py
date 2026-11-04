"""Draw a picture on the map with the game's pen (user's request).

At the start of each act's map, one picture is picked at random from the images/ folder (no repeats in
a run until every picture has been used) and drawn with right-button drags (the map draws on right-drag,
so no room is chosen by accident). The pen has one color, so detail comes from shading by hatching:
the outlines first, then parallel lines over darker parts and crossed lines over the darkest.

Pictures with "flag" in the file name also get the flag of Israel drawn behind the person (the user's
request for the portrait it was made for).

    python -m stsbot.mapdraw --preview [file]   # writes data/draw_preview.png: the strokes it would draw
"""

from __future__ import annotations

import argparse
import random
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
IMAGES = ROOT / "images"
PICTURE_TYPES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
BOX = (0.22, 0.12, 0.62, 0.66)  # where the picture goes: x0, y0, x1, y1 as fractions (the parchment's left half)
MAX_OUTLINE = 220
MAX_HATCH = 300
MIN_LENGTH = 25  # px in the working picture: shorter outlines are noise
HATCH_SPACING = 9  # px between hatch lines
MID_TONE, DARK_TONE = 115, 70  # grey levels: one direction of hatching below MID, crossed below DARK


def pictures() -> list[Path]:
    if not IMAGES.exists():
        return []
    return sorted(p for p in IMAGES.iterdir() if p.suffix.lower() in PICTURE_TYPES)


def pick_picture(used: list[str]) -> Path | None:
    """A random picture not drawn yet this run; once all are used, any of them."""
    pics = pictures()
    if not pics:
        return None
    fresh = [p for p in pics if p.name not in used]
    return random.choice(fresh or pics)


def _subject(color: np.ndarray) -> np.ndarray:
    """Mask of the subject: GrabCut seeded with a box a little inside the frame (subjects sit in the middle)."""
    H, W = color.shape[:2]
    mask = np.zeros((H, W), np.uint8)
    rect = (int(0.08 * W), int(0.02 * H), int(0.84 * W), int(0.97 * H))
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(color, mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
    person = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    return cv2.morphologyEx(person, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))


def _hatch(region: np.ndarray, angle_deg: float, spacing: int, min_run: int = 8) -> list[np.ndarray]:
    """Parallel lines at an angle, kept only where region is set; each run is one stroke (pixel coords)."""
    H, W = region.shape
    a = np.deg2rad(angle_deg)
    d = np.array([np.cos(a), np.sin(a)])  # along the line
    n = np.array([-d[1], d[0]])  # across the lines
    diag = int(np.hypot(H, W)) + 2
    c = np.array([W / 2, H / 2])
    out = []
    for off in range(-diag // 2, diag // 2, spacing):
        base = c + n * off
        ts = np.arange(-diag / 2, diag / 2, 1.0)
        pts = base + np.outer(ts, d)
        inside = (pts[:, 0] >= 0) & (pts[:, 0] < W) & (pts[:, 1] >= 0) & (pts[:, 1] < H)
        on = np.zeros(len(ts), bool)
        idx = np.where(inside)[0]
        on[idx] = region[pts[idx, 1].astype(int), pts[idx, 0].astype(int)] > 0
        start = None
        for i, v in enumerate(np.append(on, False)):
            if v and start is None:
                start = i
            elif not v and start is not None:
                if i - start >= min_run:
                    out.append(np.array([pts[start], pts[i - 1]], np.float32))
                start = None
    return out


def strokes_from_picture(path: Path, detail: bool = True) -> list[np.ndarray]:
    """Strokes in fractions of the picture (the flag may reach past its left edge)."""
    color = cv2.imread(str(path))
    if color is None:
        return []
    h, w = color.shape[:2]
    scale = 600 / max(h, w)
    color = cv2.resize(color, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    H, W = color.shape[:2]
    person = _subject(color)
    gray = cv2.GaussianBlur(cv2.cvtColor(color, cv2.COLOR_BGR2GRAY), (5, 5), 0)

    # Outlines: features inside the subject and the subject's own edge.
    edges = cv2.Canny(gray, 50, 130)
    edges[cv2.erode(person, np.ones((7, 7), np.uint8)) == 0] = 0
    edges = cv2.bitwise_or(edges, cv2.Canny(person, 50, 150))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    contours = sorted((c for c in contours if cv2.arcLength(c, False) >= MIN_LENGTH),
                      key=lambda c: -cv2.arcLength(c, False))
    px_strokes = [cv2.approxPolyDP(c, 1.5, False).reshape(-1, 2).astype(np.float32) for c in contours[:MAX_OUTLINE]]
    px_strokes = [s for s in px_strokes if len(s) >= 2]

    # Shading: darker parts of the subject get hatching, the darkest crossed hatching.
    if detail:
        inside = cv2.erode(person, np.ones((5, 5), np.uint8)) > 0
        mid = ((gray < MID_TONE) & inside).astype(np.uint8)
        dark = ((gray < DARK_TONE) & inside).astype(np.uint8)
        mid = cv2.morphologyEx(mid, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        hatch = _hatch(mid, 45, HATCH_SPACING) + _hatch(dark, -45, HATCH_SPACING)
        hatch.sort(key=lambda s: -float(np.hypot(*(s[1] - s[0]))))
        px_strokes += hatch[:MAX_HATCH]

    out = [np.stack([s[:, 0] / W, s[:, 1] / H], axis=1) for s in px_strokes]
    if "flag" in path.stem.lower():
        out += flag_strokes(person, detail)
    return out


def _line(a, b, step=0.004):
    n = max(2, int(np.hypot(b[0] - a[0], b[1] - a[1]) / step))
    return np.linspace(a, b, n)


def _visible_runs(points, person) -> list[np.ndarray]:
    """Split a line where the person stands in front of it."""
    H, W = person.shape
    out, run = [], []
    for x, y in points:
        px, py = int(x * W), int(y * H)
        if 0 <= px < W and 0 <= py < H and person[py, px] > 0:
            if len(run) > 1:
                out.append(np.array(run, np.float32))
            run = []
        else:
            run.append((x, y))
    if len(run) > 1:
        out.append(np.array(run, np.float32))
    return out


def flag_strokes(person: np.ndarray, detail: bool = True, x0=-0.55, x1=0.5, y0=0.02, y1=0.58) -> list[np.ndarray]:
    """The flag of Israel (outline, two stripes, Star of David) behind the person, in picture fractions.
    With detail, the blue stripes and the star's lines are filled with hatching too."""
    fh = y1 - y0
    lines = [_line((x0, y0), (x1, y0)), _line((x1, y0), (x1, y1)), _line((x1, y1), (x0, y1)),
             _line((x0, y1), (x0, y0))]
    stripes = ((0.10, 0.25), (0.75, 0.90))
    for top, bot in stripes:
        lines += [_line((x0, y0 + top * fh), (x1, y0 + top * fh)), _line((x0, y0 + bot * fh), (x1, y0 + bot * fh))]
        if detail:  # fill the blue stripes with diagonal hatching
            step = 0.012
            for k in np.arange(x0, x1 + fh * (bot - top), step):
                a = (k, y0 + top * fh)
                b = (k - fh * (bot - top), y0 + bot * fh)
                if b[0] < x0:  # clip to the flag's left edge
                    t = (k - x0) / (fh * (bot - top))
                    b = (x0, y0 + top * fh + t * fh * (bot - top))
                if a[0] > x1:
                    t = (a[0] - x1) / (fh * (bot - top))
                    a = (x1, y0 + top * fh + t * fh * (bot - top))
                lines.append(_line(a, b))
    cx, cy, r = (x0 + x1) / 2, y0 + fh / 2, 0.2 * fh  # the star between the stripes
    for rr in ((r, r * 0.88) if detail else (r,)):  # with detail, a second outline makes the star bold
        for rot in (-np.pi / 2, np.pi / 2):
            pts = [(cx + rr * np.cos(rot + k * 2 * np.pi / 3), cy + rr * np.sin(rot + k * 2 * np.pi / 3))
                   for k in range(4)]
            lines += [_line(pts[k], pts[k + 1]) for k in range(3)]
    out = []
    for ln in lines:
        out += _visible_runs(ln, person)
    return out


def fit_to_box(strokes: list[np.ndarray], aspect: float, box=BOX, win_aspect: float = 16 / 9) -> list[np.ndarray]:
    """Scale strokes (fractions of a picture with width/height = aspect) into the box, keeping proportions."""
    if not strokes:
        return []
    allp = np.concatenate(strokes)
    mnx, mny = allp.min(axis=0)
    mxx, mxy = allp.max(axis=0)
    aspect = aspect * (mxx - mnx) / max(1e-6, mxy - mny)
    strokes = [np.stack([(st[:, 0] - mnx) / (mxx - mnx), (st[:, 1] - mny) / (mxy - mny)], axis=1) for st in strokes]
    x0, y0, x1, y1 = box
    bw, bh = (x1 - x0) * win_aspect, (y1 - y0)
    s = min(bw / aspect, bh)
    pw, ph = s * aspect / win_aspect, s
    ox, oy = x0 + (x1 - x0 - pw) / 2, y0 + (y1 - y0 - ph) / 2
    return [np.stack([ox + st[:, 0] * pw, oy + st[:, 1] * ph], axis=1) for st in strokes]


def map_strokes(path: Path, detail: bool = True) -> list[np.ndarray]:
    h, w = cv2.imread(str(path)).shape[:2]
    return fit_to_box(strokes_from_picture(path, detail), w / h)


def draw_seconds(strokes: list[np.ndarray]) -> float:
    return sum(len(densify(st)) for st in strokes) * FRAME + len(strokes) * 0.05


def preview(path: Path, out: Path, detail: bool = True) -> int:
    strokes = map_strokes(path, detail)
    img = np.full((720, 1280, 3), 235, np.uint8)
    for st in strokes:
        cv2.polylines(img, [(st * [1280, 720]).astype(np.int32)], False, (40, 40, 200), 2)
    cv2.imwrite(str(out), img)
    return len(strokes)


STEP = 0.08  # longest straight jump between pointer positions; the game joins positions frame to frame
FRAME = 0.017  # one frame at 60 fps: each position is held for a frame so the game sees it


def densify(stroke: np.ndarray, step: float = STEP) -> np.ndarray:
    """Only the points where a stroke bends (straight runs become their two ends), with very long jumps
    split. Each point is then held for a frame: sent faster, the game missed whole hatch lines."""
    if len(stroke) > 2:
        stroke = cv2.approxPolyDP(stroke.reshape(-1, 1, 2).astype(np.float32), 0.0008, False).reshape(-1, 2)
    out = [stroke[0]]
    for a, b in zip(stroke[:-1], stroke[1:]):
        n = int(np.hypot(*(b - a)) / step)
        out += [a + (b - a) * (k / (n + 1)) for k in range(1, n + 1)] + [b]
    return np.array(out, np.float32)


def draw_on_map(win, inputs_mod, path: Path, guard=None, detail: bool = True) -> int:
    """Draw the picture with right-button drags. Returns the number of strokes drawn."""
    strokes = [densify(st) for st in map_strokes(path, detail)]
    for st in strokes:
        if guard:
            guard()
        inputs_mod.polyline(win, [tuple(p) for p in st], step_time=FRAME, right=True)  # the map draws on right-drag
    time.sleep(0.3)
    return len(strokes)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("file", nargs="?")
    a = ap.parse_args()
    p = Path(a.file) if a.file else pick_picture([])
    if p is None:
        raise SystemExit(f"No pictures: put some in {IMAGES}")
    DATA.mkdir(exist_ok=True)
    n = preview(p, DATA / "draw_preview.png")
    print(f"{p.name}: {n} strokes; preview written to {DATA / 'draw_preview.png'}")
