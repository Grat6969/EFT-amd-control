"""Measures how bright the game scene is from a few small screen samples.

The capture reads the image the game drew, before the driver applies the
gamma ramp and colour adjustments, so the boost we add does not feed back
into the measurement.
"""

from __future__ import annotations

import ctypes
from typing import List, Optional, Sequence, Tuple

# Where to sample, as fractions of the game window: the centre plus four
# points around it. They sit inside the HUD-free part of Tarkov's screen.
SAMPLE_POINTS: Sequence[Tuple[float, float]] = (
    (0.50, 0.50),
    (0.30, 0.35),
    (0.70, 0.35),
    (0.30, 0.65),
    (0.70, 0.65),
)

Rect = Tuple[int, int, int, int]  # left, top, width, height


def box_luminance(bgra: bytes, pixels: int) -> float:
    """Average luma (0..1) of a 32-bit BGRA buffer."""
    if pixels <= 0:
        return 0.0
    b = sum(bgra[0::4])
    g = sum(bgra[1::4])
    r = sum(bgra[2::4])
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / (255.0 * pixels)


def average_samples(values: Sequence[float]) -> Optional[float]:
    """Average the per-location readings.

    Returns None when every sample is pure black: a loading screen, or
    exclusive fullscreen, which Windows captures as black. Either way the
    current boost should be held instead of maxed out.
    """
    if not values or max(values) <= 0.0:
        return None
    return sum(values) / len(values)


def sample_boxes(rect: Rect, points: Sequence[Tuple[float, float]] = SAMPLE_POINTS) -> List[Rect]:
    left, top, width, height = rect
    size = max(32, min(96, int(height * 0.06)))
    boxes = []
    for fx, fy in points:
        x = left + int(width * fx) - size // 2
        y = top + int(height * fy) - size // 2
        boxes.append((x, y, size, size))
    return boxes


class ScreenSampler:
    """Captures the sample boxes with GDI (Windows only)."""

    def __init__(self) -> None:
        from ctypes import wintypes

        self._wt = wintypes
        self._user32 = ctypes.windll.user32
        self._gdi32 = ctypes.windll.gdi32
        try:
            # Without this, Windows scales coordinates on high-DPI screens
            # and the boxes land in the wrong place.
            self._user32.SetProcessDPIAware()
        except Exception:
            pass
        self._user32.GetDC.restype = wintypes.HDC
        self._user32.GetDC.argtypes = [wintypes.HWND]
        self._user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self._user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self._gdi32.CreateCompatibleDC.restype = wintypes.HDC
        self._gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self._gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        self._gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        self._gdi32.SelectObject.restype = wintypes.HGDIOBJ
        self._gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        self._gdi32.BitBlt.argtypes = [wintypes.HDC] + [ctypes.c_int] * 4 + [wintypes.HDC] + [ctypes.c_int] * 2 + [wintypes.DWORD]
        self._gdi32.GetDIBits.argtypes = [
            wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
        ]
        self._gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self._gdi32.DeleteDC.argtypes = [wintypes.HDC]

    def target_rect(self) -> Rect:
        """The focused window's client area, or the primary screen."""
        wt = self._wt
        hwnd = self._user32.GetForegroundWindow()
        if hwnd:
            rc = wt.RECT()
            pt = wt.POINT(0, 0)
            if self._user32.GetClientRect(hwnd, ctypes.byref(rc)) and self._user32.ClientToScreen(hwnd, ctypes.byref(pt)):
                if rc.right > 100 and rc.bottom > 100:
                    return pt.x, pt.y, rc.right, rc.bottom
        return 0, 0, self._user32.GetSystemMetrics(0), self._user32.GetSystemMetrics(1)

    def sample(self) -> List[float]:
        boxes = sample_boxes(self.target_rect())
        size = boxes[0][2]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16),
                ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_int32), ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32),
            ]

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(bmi)
        bmi.biWidth = size
        bmi.biHeight = -size  # top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        buf = (ctypes.c_ubyte * (size * size * 4))()

        SRCCOPY = 0x00CC0020
        screen = self._user32.GetDC(None)
        mem = self._gdi32.CreateCompatibleDC(screen)
        bmp = self._gdi32.CreateCompatibleBitmap(screen, size, size)
        old = self._gdi32.SelectObject(mem, bmp)
        values = []
        try:
            for x, y, w, h in boxes:
                self._gdi32.SelectObject(mem, bmp)
                ok = self._gdi32.BitBlt(mem, 0, 0, w, h, screen, x, y, SRCCOPY)
                # GetDIBits needs the bitmap deselected from the DC.
                self._gdi32.SelectObject(mem, old)
                if not ok or self._gdi32.GetDIBits(screen, bmp, 0, h, buf, ctypes.byref(bmi), 0) != h:
                    continue
                values.append(box_luminance(bytes(buf), w * h))
        finally:
            self._gdi32.SelectObject(mem, old)
            self._gdi32.DeleteObject(bmp)
            self._gdi32.DeleteDC(mem)
            self._user32.ReleaseDC(None, screen)
        return values

    def scene_brightness(self) -> Optional[float]:
        return average_samples(self.sample())
