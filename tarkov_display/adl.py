"""Thin ctypes wrapper around AMD Display Library (ADL).

ADL ships with every AMD Radeon driver as ``atiadlxx.dll`` (64-bit) /
``atiadlxy.dll`` (32-bit). The Display Color functions used here drive the
same brightness / contrast / saturation / hue / temperature controls that
AMD Software: Adrenalin Edition shows under Display > Display Color.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from typing import Dict, List

ADL_OK = 0
ADL_MAX_PATH = 256

ADL_DISPLAY_COLOR_BRIGHTNESS = 1 << 0
ADL_DISPLAY_COLOR_CONTRAST = 1 << 1
ADL_DISPLAY_COLOR_SATURATION = 1 << 2
ADL_DISPLAY_COLOR_HUE = 1 << 3
ADL_DISPLAY_COLOR_TEMPERATURE = 1 << 4

ADL_DISPLAY_DISPLAYINFO_DISPLAYCONNECTED = 0x1
ADL_DISPLAY_DISPLAYINFO_DISPLAYMAPPED = 0x2

COLOR_TYPES: Dict[str, int] = {
    "brightness": ADL_DISPLAY_COLOR_BRIGHTNESS,
    "contrast": ADL_DISPLAY_COLOR_CONTRAST,
    "saturation": ADL_DISPLAY_COLOR_SATURATION,
    "hue": ADL_DISPLAY_COLOR_HUE,
    "temperature": ADL_DISPLAY_COLOR_TEMPERATURE,
}


class ADLError(RuntimeError):
    pass


class AdapterInfo(ctypes.Structure):
    # Windows layout of ADL's AdapterInfo.
    _fields_ = [
        ("iSize", ctypes.c_int),
        ("iAdapterIndex", ctypes.c_int),
        ("strUDID", ctypes.c_char * ADL_MAX_PATH),
        ("iBusNumber", ctypes.c_int),
        ("iDeviceNumber", ctypes.c_int),
        ("iFunctionNumber", ctypes.c_int),
        ("iVendorID", ctypes.c_int),
        ("strAdapterName", ctypes.c_char * ADL_MAX_PATH),
        ("strDisplayName", ctypes.c_char * ADL_MAX_PATH),
        ("iPresent", ctypes.c_int),
        ("iExist", ctypes.c_int),
        ("strDriverPath", ctypes.c_char * ADL_MAX_PATH),
        ("strDriverPathExt", ctypes.c_char * ADL_MAX_PATH),
        ("strPNPString", ctypes.c_char * ADL_MAX_PATH),
        ("iOSDisplayIndex", ctypes.c_int),
    ]


class ADLDisplayID(ctypes.Structure):
    _fields_ = [
        ("iDisplayLogicalIndex", ctypes.c_int),
        ("iDisplayPhysicalIndex", ctypes.c_int),
        ("iDisplayLogicalAdapterIndex", ctypes.c_int),
        ("iDisplayPhysicalAdapterIndex", ctypes.c_int),
    ]


class ADLDisplayInfo(ctypes.Structure):
    _fields_ = [
        ("displayID", ADLDisplayID),
        ("iDisplayControllerIndex", ctypes.c_int),
        ("strDisplayName", ctypes.c_char * ADL_MAX_PATH),
        ("strDisplayManufacturerName", ctypes.c_char * ADL_MAX_PATH),
        ("iDisplayType", ctypes.c_int),
        ("iDisplayOutputType", ctypes.c_int),
        ("iDisplayConnector", ctypes.c_int),
        ("iDisplayInfoMask", ctypes.c_int),
        ("iDisplayInfoValue", ctypes.c_int),
    ]


@dataclass(frozen=True)
class Display:
    adapter_index: int
    display_index: int
    name: str
    os_name: str  # e.g. \\.\DISPLAY1

    @property
    def key(self) -> str:
        return f"{self.adapter_index}:{self.display_index}"


@dataclass
class ColorRange:
    current: int
    default: int
    minimum: int
    maximum: int
    step: int

    def clamp(self, value: int) -> int:
        value = max(self.minimum, min(self.maximum, int(round(value))))
        if self.step > 1:
            value = self.minimum + round((value - self.minimum) / self.step) * self.step
            value = min(value, self.maximum)
        return value


class ADL:
    """AMD Display Library session. Use as a context manager or call close()."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise ADLError("AMD ADL is only available on Windows")
        self._dll = self._load()
        self._libc = ctypes.cdll.msvcrt
        self._libc.malloc.restype = ctypes.c_void_p
        self._libc.malloc.argtypes = [ctypes.c_size_t]
        self._libc.free.argtypes = [ctypes.c_void_p]

        # ADL allocates its output buffers through this callback. Keep a
        # reference on self or the callback gets garbage collected.
        alloc_type = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_int)
        self._alloc = alloc_type(lambda size: self._libc.malloc(size))

        self._ctx = ctypes.c_void_p()
        self._check(
            self._dll.ADL2_Main_Control_Create(self._alloc, 1, ctypes.byref(self._ctx)),
            "ADL2_Main_Control_Create",
        )

    @staticmethod
    def _load():
        last_err = None
        for name in ("atiadlxx.dll", "atiadlxy.dll"):
            try:
                return ctypes.CDLL(name)
            except OSError as exc:
                last_err = exc
        raise ADLError(
            "Could not load the AMD Display Library (atiadlxx.dll). "
            "Is an AMD Radeon driver installed?"
        ) from last_err

    @staticmethod
    def _check(rc: int, what: str) -> None:
        # ADL returns 0 for OK and small positive values for "OK, but...".
        if rc < ADL_OK:
            raise ADLError(f"{what} failed with ADL error {rc}")

    def close(self) -> None:
        if self._ctx:
            self._dll.ADL2_Main_Control_Destroy(self._ctx)
            self._ctx = ctypes.c_void_p()

    def __enter__(self) -> "ADL":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def displays(self) -> List[Display]:
        """Every connected, active display driven by an AMD GPU."""
        count = ctypes.c_int()
        self._check(
            self._dll.ADL2_Adapter_NumberOfAdapters_Get(self._ctx, ctypes.byref(count)),
            "ADL2_Adapter_NumberOfAdapters_Get",
        )
        if count.value <= 0:
            return []

        infos = (AdapterInfo * count.value)()
        self._check(
            self._dll.ADL2_Adapter_AdapterInfo_Get(self._ctx, infos, ctypes.sizeof(infos)),
            "ADL2_Adapter_AdapterInfo_Get",
        )

        found: Dict[str, Display] = {}
        for info in infos:
            if not info.iPresent:
                continue
            adapter = info.iAdapterIndex
            num = ctypes.c_int()
            ptr = ctypes.POINTER(ADLDisplayInfo)()
            rc = self._dll.ADL2_Display_DisplayInfo_Get(
                self._ctx, adapter, ctypes.byref(num), ctypes.byref(ptr), 0
            )
            if rc < ADL_OK or not ptr:
                continue
            try:
                for i in range(num.value):
                    d = ptr[i]
                    want = ADL_DISPLAY_DISPLAYINFO_DISPLAYCONNECTED | ADL_DISPLAY_DISPLAYINFO_DISPLAYMAPPED
                    if d.iDisplayInfoValue & want != want:
                        continue
                    # The same display is reported under every logical
                    # adapter; only keep it under the one that owns it.
                    if d.displayID.iDisplayLogicalAdapterIndex != adapter:
                        continue
                    disp = Display(
                        adapter_index=adapter,
                        display_index=d.displayID.iDisplayLogicalIndex,
                        name=d.strDisplayName.decode(errors="replace").strip() or "Display",
                        os_name=info.strDisplayName.decode(errors="replace"),
                    )
                    found.setdefault(disp.key, disp)
            finally:
                self._libc.free(ctypes.cast(ptr, ctypes.c_void_p))
        return list(found.values())

    def get_color(self, display: Display, color: str) -> ColorRange:
        vals = [ctypes.c_int() for _ in range(5)]
        self._check(
            self._dll.ADL2_Display_Color_Get(
                self._ctx,
                display.adapter_index,
                display.display_index,
                COLOR_TYPES[color],
                *[ctypes.byref(v) for v in vals],
            ),
            f"ADL2_Display_Color_Get({color})",
        )
        return ColorRange(*(v.value for v in vals))

    def set_color(self, display: Display, color: str, value: int) -> None:
        self._check(
            self._dll.ADL2_Display_Color_Set(
                self._ctx,
                display.adapter_index,
                display.display_index,
                COLOR_TYPES[color],
                int(value),
            ),
            f"ADL2_Display_Color_Set({color}={value})",
        )
