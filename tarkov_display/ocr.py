"""Reads text from a screenshot.

Uses the OCR engine built into Windows 10/11 (via the ``winrt`` Python
packages). If those aren't installed, falls back to Tesseract when it is.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .screen import to_bmp

log = logging.getLogger(__name__)

INSTALL_HINT = (
    "No OCR engine found. Run install.bat (or: pip install -r requirements.txt) to use the OCR "
    "built into Windows, or install Tesseract from https://github.com/UB-Mannheim/tesseract/wiki"
)


class OcrUnavailable(RuntimeError):
    pass


WordBox = Tuple[str, Tuple[float, float, float, float]]  # text, (left, top, right, bottom)


@dataclass
class OcrLine:
    text: str
    x: float  # centre of the line in image pixels
    y: float
    words: Tuple[WordBox, ...] = ()  # each word and where it is (image pixels), left to right

    @staticmethod
    def of_words(words: List[WordBox]) -> "OcrLine":
        x0 = min(b[0] for _, b in words)
        y0 = min(b[1] for _, b in words)
        x1 = max(b[2] for _, b in words)
        y1 = max(b[3] for _, b in words)
        ordered = tuple(sorted(words, key=lambda w: w[1][0]))
        return OcrLine(" ".join(t for t, _ in ordered), (x0 + x1) / 2, (y0 + y1) / 2, ordered)


def order_by_distance(lines: List[OcrLine], cx: float, cy: float) -> List[OcrLine]:
    # Vertical distance counts double: the item name sits on its own row.
    return sorted(lines, key=lambda l: ((l.x - cx) ** 2 + (2 * (l.y - cy)) ** 2))


class WindowsOcr:
    def __init__(self) -> None:
        try:
            from winrt.windows.globalization import Language
            from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.storage.streams import DataWriter
        except ImportError as exc:
            raise OcrUnavailable(INSTALL_HINT) from exc
        self._SoftwareBitmap = SoftwareBitmap
        self._BGRA8 = BitmapPixelFormat.BGRA8
        self._IGNORE_ALPHA = BitmapAlphaMode.IGNORE
        self._DataWriter = DataWriter
        try:
            self.max_dimension = int(OcrEngine.max_image_dimension)
        except Exception:
            self.max_dimension = 2600
        engine = None
        try:
            engine = OcrEngine.try_create_from_language(Language("en-US"))
        except Exception:
            pass
        self.engine = engine or OcrEngine.try_create_from_user_profile_languages()
        if self.engine is None:
            raise OcrUnavailable("Windows OCR has no language installed (Settings > Language > add English).")

    def read(self, bgra: bytes, w: int, h: int) -> List[OcrLine]:
        import asyncio

        writer = self._DataWriter()
        writer.write_bytes(bgra)
        # Screen captures leave the alpha byte at 0. The default (premultiplied)
        # alpha mode would read that as fully transparent: a blank image.
        bitmap = self._SoftwareBitmap.create_copy_with_alpha_from_buffer(
            writer.detach_buffer(), self._BGRA8, w, h, self._IGNORE_ALPHA)

        async def run():
            return await self.engine.recognize_async(bitmap)

        result = asyncio.run(run())
        lines = []
        for line in result.lines:
            words = []
            for wd in line.words:
                r = wd.bounding_rect
                words.append((wd.text, (r.x, r.y, r.x + r.width, r.y + r.height)))
            if words:
                lines.append(OcrLine.of_words(words))
        return lines


INVERT = bytes(255 - i for i in range(256))


def find_tesseract() -> Optional[str]:
    path = shutil.which("tesseract")
    if path:
        return path
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("LOCALAPPDATA", "")):
        candidate = os.path.join(base, "Tesseract-OCR", "tesseract.exe")
        if base and os.path.exists(candidate):
            return candidate
    return None


def parse_tesseract_tsv(tsv: str) -> List[OcrLine]:
    groups = {}
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or not cols[11].strip():
            continue
        key = (cols[2], cols[3], cols[4])  # block, paragraph, line
        left, top, width, height = (int(c) for c in cols[6:10])
        groups.setdefault(key, []).append((left, top, width, height, cols[11].strip()))
    return [OcrLine.of_words([(w[4], (w[0], w[1], w[0] + w[2], w[1] + w[3])) for w in words]) for words in groups.values()]


class TesseractOcr:
    max_dimension = 10000

    def __init__(self) -> None:
        self.exe = find_tesseract()
        if not self.exe:
            raise OcrUnavailable(INSTALL_HINT)

    def read(self, bgra: bytes, w: int, h: int) -> List[OcrLine]:
        # Tesseract reads dark text on light backgrounds best; Tarkov is the opposite.
        bmp = to_bmp(bgra.translate(INVERT), w, h)
        fd, path = tempfile.mkstemp(suffix=".bmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(bmp)
            out = subprocess.run(
                [self.exe, path, "stdout", "--psm", "11", "tsv"],
                capture_output=True, text=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        finally:
            os.unlink(path)
        return parse_tesseract_tsv(out.stdout)


def available_engine() -> Optional[str]:
    """The OCR engine a price check would use, found without starting it."""
    import importlib.util

    try:
        if importlib.util.find_spec("winrt.windows.media.ocr"):
            return "Windows OCR"
    except (ImportError, ValueError):
        pass
    return "Tesseract" if find_tesseract() else None


def create_ocr():
    errors = []
    for cls in (WindowsOcr, TesseractOcr):
        try:
            engine = cls()
            log.info("OCR engine: %s", cls.__name__)
            return engine
        except OcrUnavailable as exc:
            errors.append(str(exc))
    raise OcrUnavailable(errors[0])
