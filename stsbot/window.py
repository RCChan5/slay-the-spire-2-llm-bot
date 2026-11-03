"""Find the Slay the Spire 2 window and grab its picture.

Uses only the window list (by program name) and a screen grab of the window's
client area. Nothing is read from or injected into the game's process.

    win = find_game()
    frame = grab(win)          # BGR numpy array, client area only
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
from dataclasses import dataclass

import mss
import numpy as np

GAME_EXE = "SlayTheSpire2.exe"

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Report real pixels, not scaled ones, so grabs and clicks line up on high-DPI monitors.
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
except Exception:
    pass

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


@dataclass
class GameWindow:
    hwnd: int
    title: str
    left: int  # client area on screen, real pixels
    top: int
    width: int
    height: int

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        """A point in the window's client area (pixels) to screen pixels."""
        return int(self.left + x), int(self.top + y)


def _exe_name(pid: int) -> str:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(h)


def _client_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, r.right - r.left, r.bottom - r.top


def find_game(exe: str = GAME_EXE) -> GameWindow | None:
    """The game's largest visible top-level window, or None if it is not running."""
    found: list[GameWindow] = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if _exe_name(pid.value).lower() != exe.lower():
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        x, y, w, h = _client_rect(hwnd)
        if w > 100 and h > 100:
            found.append(GameWindow(hwnd, buf.value, x, y, w, h))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    if not found:
        return None
    return max(found, key=lambda g: g.width * g.height)


def is_foreground(win: GameWindow) -> bool:
    return user32.GetForegroundWindow() == win.hwnd


_sct = None


def grab(win: GameWindow) -> np.ndarray:
    """The window's client area as a BGR image. The window must be visible on screen."""
    global _sct
    if _sct is None:
        _sct = mss.mss()
    shot = _sct.grab({"left": win.left, "top": win.top, "width": win.width, "height": win.height})
    return np.ascontiguousarray(np.asarray(shot)[:, :, :3])
