"""Keeps API tokens out of plain text.

On Windows, tokens are encrypted with DPAPI (the same protection Windows
uses for saved passwords), so they can only be read by your Windows account
on this PC. Elsewhere they are stored as-is.
"""

from __future__ import annotations

import base64
import ctypes
import sys

DPAPI = "dpapi:"
PLAIN = "plain:"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    src, _keep = _blob(data)
    out = _Blob()
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
        raise OSError("Windows couldn't " + ("protect" if protect else "read") + " the saved token")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def protect(secret: str) -> str:
    if not secret:
        return ""
    if sys.platform == "win32":
        return DPAPI + base64.b64encode(_dpapi(secret.encode(), True)).decode()
    return PLAIN + secret


def unprotect(stored: str) -> str:
    if not stored:
        return ""
    if stored.startswith(DPAPI):
        return _dpapi(base64.b64decode(stored[len(DPAPI):]), False).decode()
    if stored.startswith(PLAIN):
        return stored[len(PLAIN):]
    return stored


def mask(secret: str) -> str:
    """Enough of a token to recognise it, never the whole thing."""
    if not secret:
        return ""
    return (secret[:4] + "…" + secret[-4:]) if len(secret) > 10 else "…" + secret[-2:]
