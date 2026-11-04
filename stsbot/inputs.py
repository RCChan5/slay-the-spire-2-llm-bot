"""Mouse and keyboard through Windows SendInput (what a real mouse and keyboard send).

Points are given as fractions of the game window (0..1), so the same plan works at any resolution.
Every action first checks the game is the window in front; it never clicks into another program.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import random
import time

from .window import GameWindow, is_foreground, user32

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0001, 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x8000, 0x4000
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x0002, 0x0008
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]


class NotInFront(RuntimeError):
    pass


def _send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _mouse(flags: int, dx: int = 0, dy: int = 0) -> INPUT:
    return INPUT(INPUT_MOUSE, _U(mi=MOUSEINPUT(dx, dy, 0, flags, 0, None)))


def _check(win: GameWindow) -> None:
    if not is_foreground(win):
        raise NotInFront("Slay the Spire 2 is not the window in front; no input sent.")


def move_px(sx: int, sy: int) -> None:
    """Move the pointer to a screen pixel."""
    vx, vy = user32.GetSystemMetrics(SM_XVIRTUALSCREEN), user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw, vh = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN), user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    nx = round((sx - vx) * 65535 / max(1, vw - 1))
    ny = round((sy - vy) * 65535 / max(1, vh - 1))
    _send(_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny))


def move(win: GameWindow, fx: float, fy: float, steps: int = 8, duration: float = 0.12) -> None:
    """Glide to a point given as fractions of the window (the game reacts to hover, so no jumps)."""
    _check(win)
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    tx, ty = win.to_screen(fx * win.width, fy * win.height)
    for i in range(1, steps + 1):
        t = i / steps
        move_px(round(pt.x + (tx - pt.x) * t), round(pt.y + (ty - pt.y) * t))
        time.sleep(duration / steps)


def click(win: GameWindow, fx: float, fy: float, right: bool = False) -> None:
    move(win, fx, fy)
    time.sleep(0.05 + random.random() * 0.03)
    down, up = (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP) if right else (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
    _check(win)
    _send(_mouse(down))
    time.sleep(0.04)
    _send(_mouse(up))


def drag(win: GameWindow, f0: tuple[float, float], f1: tuple[float, float]) -> None:
    move(win, *f0)
    _check(win)
    _send(_mouse(MOUSEEVENTF_LEFTDOWN))
    time.sleep(0.08)
    move(win, *f1, steps=16, duration=0.25)
    time.sleep(0.08)
    _send(_mouse(MOUSEEVENTF_LEFTUP))


def polyline(win: GameWindow, points: list[tuple[float, float]], step_time: float = 0.012, right: bool = False) -> None:
    """Press, move through the points (fractions of the window), release: one pen stroke."""
    down, up = (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP) if right else (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
    if len(points) < 2:
        return
    _check(win)
    move_px(*win.to_screen(points[0][0] * win.width, points[0][1] * win.height))
    time.sleep(step_time)
    _send(_mouse(down))
    for fx, fy in points[1:]:
        move_px(*win.to_screen(fx * win.width, fy * win.height))
        time.sleep(step_time)
    _send(_mouse(up))
    time.sleep(step_time)


def wheel(win: GameWindow, notches: int) -> None:
    """Scroll: negative notches scroll down."""
    _check(win)
    for _ in range(abs(notches)):
        _send(INPUT(INPUT_MOUSE, _U(mi=MOUSEINPUT(0, 0, 120 if notches > 0 else (-120 & 0xFFFFFFFF), MOUSEEVENTF_WHEEL,
                                                  0, None))))
        time.sleep(0.05)


VK = {"enter": 0x0D, "esc": 0x1B, "space": 0x20, "e": 0x45, **{str(i): 0x30 + i for i in range(10)}}


def key(win: GameWindow, name: str) -> None:
    _check(win)
    vk = VK[name]
    scan = user32.MapVirtualKeyW(vk, 0)
    _send(INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(0, scan, KEYEVENTF_SCANCODE, 0, None))))
    time.sleep(0.04)
    _send(INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(0, scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0, None))))
