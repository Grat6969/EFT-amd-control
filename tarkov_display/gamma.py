"""Windows gamma ramp control (works on any GPU).

AMD Adrenalin has no gamma slider any more, so gamma is applied through the
standard Windows GDI gamma ramp, the same thing tools like Gamma Panel use.
"""

from __future__ import annotations

import ctypes
import sys
from typing import List

Ramp = List[List[int]]  # [red[256], green[256], blue[256]], 0..65535


def build_ramp(gamma: float = 1.0, brightness: int = 0, contrast: int = 100) -> Ramp:
    """Build a gamma ramp.

    ``brightness`` (-100..100) and ``contrast`` (0..200) are only used when
    there is no AMD driver to apply them in hardware.
    """
    gamma = max(0.3, min(3.0, float(gamma)))
    values = []
    prev = 0
    for i in range(256):
        x = (i / 255.0) ** (1.0 / gamma)
        x = (x - 0.5) * (contrast / 100.0) + 0.5
        x += brightness / 400.0
        v = int(round(max(0.0, min(1.0, x)) * 65535))
        v = max(v, prev)  # Windows rejects non-monotonic ramps
        values.append(v)
        prev = v
    return [values, list(values), list(values)]


def identity_ramp() -> Ramp:
    return build_ramp(1.0)


class GammaRamp:
    """Reads and writes the gamma ramp of each attached Windows display."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Gamma ramps are only supported on Windows")
        from ctypes import wintypes

        self._wt = wintypes
        self._user32 = ctypes.windll.user32
        self._gdi32 = ctypes.windll.gdi32
        self._gdi32.CreateDCW.restype = wintypes.HDC
        self._gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR] * 3 + [ctypes.c_void_p]
        self._gdi32.DeleteDC.argtypes = [wintypes.HDC]
        self._gdi32.GetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]
        self._gdi32.SetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]

    def displays(self) -> List[str]:
        wt = self._wt

        class DISPLAY_DEVICEW(ctypes.Structure):
            _fields_ = [
                ("cb", wt.DWORD),
                ("DeviceName", wt.WCHAR * 32),
                ("DeviceString", wt.WCHAR * 128),
                ("StateFlags", wt.DWORD),
                ("DeviceID", wt.WCHAR * 128),
                ("DeviceKey", wt.WCHAR * 128),
            ]

        DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x1
        names = []
        i = 0
        while True:
            dev = DISPLAY_DEVICEW()
            dev.cb = ctypes.sizeof(dev)
            if not self._user32.EnumDisplayDevicesW(None, i, ctypes.byref(dev), 0):
                break
            if dev.StateFlags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP:
                names.append(dev.DeviceName)
            i += 1
        return names

    def _dc(self, device: str):
        hdc = self._gdi32.CreateDCW(None, device, None, None)
        if not hdc:
            raise OSError(f"CreateDC failed for {device}")
        return hdc

    def get(self, device: str) -> Ramp:
        buf = (ctypes.c_ushort * (3 * 256))()
        hdc = self._dc(device)
        try:
            if not self._gdi32.GetDeviceGammaRamp(hdc, buf):
                raise OSError(f"GetDeviceGammaRamp failed for {device}")
        finally:
            self._gdi32.DeleteDC(hdc)
        flat = list(buf)
        return [flat[0:256], flat[256:512], flat[512:768]]

    def set(self, device: str, ramp: Ramp) -> bool:
        buf = (ctypes.c_ushort * (3 * 256))(*(ramp[0] + ramp[1] + ramp[2]))
        hdc = self._dc(device)
        try:
            return bool(self._gdi32.SetDeviceGammaRamp(hdc, buf))
        finally:
            self._gdi32.DeleteDC(hdc)
