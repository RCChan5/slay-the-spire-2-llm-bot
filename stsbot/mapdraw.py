"""Draw a picture on the map with the game's pen (user's request).

At the start of each act's map, one picture is picked at random from the images/ folder (no repeats in
a run until every picture has been used) and drawn with right-button drags (the map draws on right-drag,
so no room is chosen by accident). By default it is a plain outline at the original pace (the user's
choice); detail=True adds shading by hatching, which looked worse in the game and is off.

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
MAX_OUTLINE = 160
MAX_HATCH = 300
MIN_LENGTH = 30  # px in the working picture: shorter lines are noise
MAX_DRAW_STROKES = 100  # the outline and the flag always fit; inner lines fill the rest, longest first
STROKE_PAUSE = 0.12  # seconds between strokes, so a multiplayer game has time to take each one
INNER_MIN_LENGTH = 18  # inside the subject shorter lines are kept: eyes, mouth, fingers
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


MODELS = ROOT / "models"
U2NET = MODELS / "u2net.onnx"  # background removal (rembg's U-2-Net), downloaded once into models/
_u2net = None
MIN_SUBJECT = 0.08  # a cut-out smaller than this share of the picture is not the subject: trace it all


def _grabcut(color: np.ndarray) -> np.ndarray:
    """Fallback when the model is missing: GrabCut seeded with a box a little inside the frame."""
    H, W = color.shape[:2]
    mask = np.zeros((H, W), np.uint8)
    rect = (int(0.08 * W), int(0.02 * H), int(0.84 * W), int(0.97 * H))
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(color, mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
    person = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    return cv2.morphologyEx(person, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))


def _subject(color: np.ndarray) -> np.ndarray:
    """Mask of the subject (255) from the U-2-Net background-removal model; the whole picture when the
    model finds nothing big enough (it chose a bag over two legs once)."""
    global _u2net
    H, W = color.shape[:2]
    if not U2NET.exists():
        return _grabcut(color)
    if _u2net is None:
        _u2net = cv2.dnn.readNetFromONNX(str(U2NET))
    rgb = cv2.cvtColor(color, cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    x = (cv2.resize(rgb, (320, 320)) - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
    _u2net.setInput(x.transpose(2, 0, 1)[None].astype(np.float32))
    m = _u2net.forward()[0, 0]
    m = cv2.resize((m - m.min()) / (m.max() - m.min() + 1e-6), (W, H))
    mask = (m > 0.5).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    if mask.mean() / 255 < MIN_SUBJECT:
        return np.full((H, W), 255, np.uint8)
    return mask


def _calm_edges(gray: np.ndarray) -> np.ndarray:
    """Edges that matter: texture (skin, cloth, wall) smoothed away first, thresholds from the picture's
    own contrast so soft pictures still get lines."""
    g = gray
    for _ in range(3):
        g = cv2.bilateralFilter(g, 9, 45, 9)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    hi = float(np.percentile(np.hypot(gx, gy), 91))
    return cv2.Canny(g, 0.45 * hi / 4, hi / 4)


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


def strokes_from_picture(path: Path, detail: bool = False) -> list[np.ndarray]:
    """Strokes in fractions of the picture (the flag may reach past its left edge)."""
    color = cv2.imread(str(path))
    if color is None:
        return []
    h, w = color.shape[:2]
    scale = 600 / max(h, w)
    color = cv2.resize(color, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    H, W = color.shape[:2]
    person = _subject(color)
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)

    # The subject's own outline, smoothed, drawn first and whole.
    smooth = cv2.GaussianBlur(person, (9, 9), 0)
    outline_cs, _ = cv2.findContours((smooth > 127).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    outline = []
    for c in outline_cs:
        if cv2.arcLength(c, True) < 4 * MIN_LENGTH or person.mean() >= 250:
            continue
        pts = c.reshape(-1, 2)
        pts = np.vstack([pts, pts[:1]])
        # Where the subject runs off the photo, its outline follows the photo's border: leave that part out.
        on_edge = (pts[:, 0] <= 2) | (pts[:, 0] >= W - 3) | (pts[:, 1] <= 2) | (pts[:, 1] >= H - 3)
        run: list = []
        for q, edge in zip(pts, on_edge):
            if edge:
                if len(run) > 8:
                    outline.append(np.array(run, np.float32))
                run = []
            else:
                run.append(q)
        if len(run) > 8:
            outline.append(np.array(run, np.float32))
    outline = [cv2.approxPolyDP(o.reshape(-1, 1, 2), 1.5, False).reshape(-1, 2).astype(np.float32) for o in outline]

    # Inner details (face, tie, hands, folds): the calm edges, inside the subject only.
    edges = _calm_edges(gray)
    edges[cv2.erode(person, np.ones((9, 9), np.uint8)) == 0] = 0
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    contours = sorted((c for c in contours if cv2.arcLength(c, False) >= INNER_MIN_LENGTH),
                      key=lambda c: -cv2.arcLength(c, False))
    inner = [cv2.approxPolyDP(c, 1.5, False).reshape(-1, 2).astype(np.float32) for c in contours[:MAX_OUTLINE]]
    inner = [s for s in inner if len(s) >= 2]
    px_strokes = outline + inner

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

    def frac(strokes):
        return [np.stack([s[:, 0] / W, s[:, 1] / H], axis=1) for s in strokes]

    # Most important first, then capped: in multiplayer the game stopped taking strokes partway, and
    # whatever is lost should be the least important (short inner lines), never the outline or the flag.
    flag = flag_strokes(person, detail) if "flag" in path.stem.lower() else []
    first = frac(outline) + flag
    rest = frac([s for s in px_strokes if not any(s is o for o in outline)])
    return first + rest[:max(0, MAX_DRAW_STROKES - len(first))]


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


def flag_strokes(person: np.ndarray, detail: bool = False, x0=-0.55, x1=0.5, y0=0.02, y1=0.58) -> list[np.ndarray]:
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


def map_strokes(path: Path, detail: bool = False, box=BOX) -> list[np.ndarray]:
    h, w = cv2.imread(str(path)).shape[:2]
    return fit_to_box(strokes_from_picture(path, detail), w / h, box)


def preview(path: Path, out: Path, detail: bool = False) -> int:
    strokes = map_strokes(path, detail)
    img = np.full((720, 1280, 3), 235, np.uint8)
    for st in strokes:
        cv2.polylines(img, [(st * [1280, 720]).astype(np.int32)], False, (40, 40, 200), 2)
    cv2.imwrite(str(out), img)
    return len(strokes)


STEP_TIME = 0.02  # seconds per pointer step: about a minute per picture (the user's choice)


def draw_on_map(win, inputs_mod, path: Path, guard=None, detail: bool = False, box=BOX, after_stroke=None) -> int:
    """Draw the picture with right-button drags. Returns the number of strokes drawn.

    The default is the plain outline at the original pace (the user's choice: the shaded, faster version
    looked worse in the game)."""
    strokes = map_strokes(path, detail, box)
    for st in strokes:
        if guard:
            guard()
        inputs_mod.polyline(win, [tuple(p) for p in st], step_time=STEP_TIME, right=True)  # draws on right-drag
        if after_stroke:
            after_stroke()  # tell the caller where the pointer is now, so its own strokes are not taken for a hand
        time.sleep(STROKE_PAUSE)
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
