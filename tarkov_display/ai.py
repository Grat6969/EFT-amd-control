"""Claude reads item names for the price check (off unless you turn it on
and add your own Anthropic API key).

When the built-in text reader isn't sure what an item is called (or on
every check, if you choose), the price check sends Claude the small image
it just read: the game's tooltip, or the area around the mouse with the
mouse marked. Claude replies with the item's name, which is then looked up
in the price list like any other reading. Uses the official Anthropic SDK;
the key is stored encrypted for your Windows account (see secretstore), and
each read is billed to your Anthropic account. Answers for the same image
are remembered, and there's a cap on reads per minute, so costs can't run
away.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import struct
import threading
import time
import zlib
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from .profiles import AiConfig

log = logging.getLogger(__name__)

# name, input and output price in dollars per million tokens (for the cost estimate shown in the app)
MODELS = {
    "claude-opus-5-5": ("Claude Opus 5.5", 4.00, 20.00),
    "claude-sonnet-5-5": ("Claude Sonnet 5.5", 2.00, 10.00),
    "claude-haiku-5-5": ("Claude Haiku 5.5", 0.10, 0.50),
}
DEFAULT_MODEL = "claude-opus-5-5"
# Models with a server-side fallback when they decline a request (Claude Haiku 5.5 has none).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MODES = ("off", "unsure", "always")
MAX_TOKENS = 2048        # room for a little thinking plus a one-line answer
TIMEOUT = 15.0           # seconds
PER_MINUTE = 30          # most reads in any minute
CACHE_SIZE = 300
MAX_SIDE = 1568          # longer images are shrunk first (the API would do it anyway, slower)

SYSTEM = ("You read item names from screenshots of the game Escape from Tarkov. Reply with only the item's full name, "
          "exactly as the game's tooltip writes it, on one line. If no item tooltip is visible, reply NONE.")
ASK = {
    "tooltip": "This is the tooltip the game showed when the mouse stopped on an item. What is the item's full name?",
    "area": ("The mouse is at the centre of the red cross. What is the full name in the game's item tooltip next to it? "
             "Ignore the short names printed on the items in the grid."),
}


def sdk_installed() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass
class AiRead:
    name: Optional[str] = None   # the item name Claude read; None: no item
    error: Optional[str] = None
    cached: bool = False


# -- images -----------------------------------------------------------------------


def to_png(bgra: bytes, w: int, h: int) -> bytes:
    """A top-down 32-bit BGRA capture as a PNG file (RGB)."""
    rgb = bytearray(w * h * 3)
    rgb[0::3] = bgra[2::4]
    rgb[1::3] = bgra[1::4]
    rgb[2::3] = bgra[0::4]
    row = w * 3
    raw = b"".join(b"\x00" + bytes(rgb[y * row:(y + 1) * row]) for y in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def mark_cursor(bgra: bytes, w: int, h: int, x: int, y: int, size: int = 14) -> bytes:
    """``bgra`` with a red cross centred on (x, y), leaving the very centre clear."""
    out = bytearray(bgra)
    red = bytes((0, 0, 255, 255))
    for d in range(4, size + 1):
        for px, py in ((x - d, y), (x + d, y), (x, y - d), (x, y + d)):
            for t in (-1, 0, 1):  # 3 px thick
                qx, qy = (px, py + t) if py == y else (px + t, py)
                if 0 <= qx < w and 0 <= qy < h:
                    i = (qy * w + qx) * 4
                    out[i:i + 4] = red
    return bytes(out)


def shrink(bgra: bytes, w: int, h: int) -> Tuple[bytes, int, int]:
    """Halve a capture until its longer side fits MAX_SIDE."""
    while max(w, h) > MAX_SIDE:
        nw, nh = w // 2, h // 2
        out = bytearray(nw * nh * 4)
        for y in range(nh):
            src = bgra[(y * 2) * w * 4:(y * 2 + 1) * w * 4]
            row = bytearray(nw * 4)
            for k in range(4):
                row[k::4] = src[k::8][:nw]
            out[y * nw * 4:(y + 1) * nw * 4] = row
        bgra, w, h = bytes(out), nw, nh
    return bgra, w, h


def parse_reply(text: str) -> Optional[str]:
    """The item name from Claude's reply, or None for "no item"."""
    for line in (text or "").splitlines():
        name = line.strip().strip("\"'“”*`.").strip()
        if name:
            return None if name.upper() == "NONE" or len(name) > 120 else name
    return None


# -- the reader -----------------------------------------------------------------------


class AiReader:
    """Asks Claude what an image of a tooltip says. One instance per app."""

    def __init__(self, cfg: Callable[[], AiConfig], key: Callable[[], str], client_factory: Optional[Callable] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.cfg = cfg
        self.key = key
        self._factory = client_factory  # tests pass a fake; otherwise the SDK client
        self._clock = clock
        self._client = None
        self._client_key: Optional[str] = None
        self._cache: "OrderedDict[str, Optional[str]]" = OrderedDict()
        self._recent: deque = deque()
        self._lock = threading.Lock()
        self.stats = {"reads": 0, "cached": 0, "skipped": 0, "errors": 0, "inputTokens": 0, "outputTokens": 0,
                      "cost": 0.0, "lastError": None, "last": None}

    # -- whether to use it ----------------------------------------------------------

    def unavailable(self) -> Optional[str]:
        """Why Claude can't read right now, or None if it can."""
        if self.cfg().mode == "off":
            return "off"
        if not sdk_installed():
            return "the Anthropic SDK isn't installed (the installer includes it; it needs Python 3.10 or newer)"
        if not self.key():
            return "no API key saved"
        return None

    def wanted(self, sure: bool) -> bool:
        """Should a check ask Claude? ``sure``: the built-in reader is certain."""
        mode = self.cfg().mode
        return (mode == "always" or (mode == "unsure" and not sure)) and self.unavailable() is None

    # -- reading ---------------------------------------------------------------------

    def read(self, bgra: bytes, w: int, h: int, kind: str = "tooltip", cursor: Optional[Tuple[int, int]] = None) -> AiRead:
        """What item name the image shows. ``kind``: "tooltip" (just the
        tooltip) or "area" (the area around the mouse at ``cursor``)."""
        if kind == "area" and cursor:
            bgra = mark_cursor(bgra, w, h, int(cursor[0]), int(cursor[1]))
        bgra, w, h = shrink(bgra, w, h)
        png = to_png(bgra, w, h)
        digest = hashlib.sha1(kind.encode() + png).hexdigest()
        with self._lock:
            if digest in self._cache:
                self._cache.move_to_end(digest)
                self.stats["cached"] += 1
                return AiRead(self._cache[digest], cached=True)
            now = self._clock()
            while self._recent and now - self._recent[0] > 60:
                self._recent.popleft()
            if len(self._recent) >= PER_MINUTE:
                self.stats["skipped"] += 1
                return AiRead(error=f"skipped: more than {PER_MINUTE} AI reads in a minute")
            self._recent.append(now)
        started = self._clock()
        try:
            response = self._ask(png, kind)
        except Exception as exc:
            message = self._explain(exc)
            with self._lock:
                self.stats["errors"] += 1
                self.stats["lastError"] = message
            log.warning("AI read failed: %s", message)
            return AiRead(error=message)
        seconds = self._clock() - started
        self._count(response)
        if getattr(response, "stop_reason", None) == "refusal":
            with self._lock:
                self.stats["lastError"] = "Claude declined to read that image"
            return AiRead(error="Claude declined to read that image")
        text = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text")
        name = parse_reply(text)
        with self._lock:
            self._cache[digest] = name
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
            self.stats["lastError"] = None
            self.stats["last"] = {"name": name, "seconds": round(seconds, 2), "time": time.time()}
        log.info("AI read (%s, %.1fs): %r", kind, seconds, name)
        return AiRead(name)

    def _ask(self, png: bytes, kind: str):
        cfg = self.cfg()
        model = cfg.model if cfg.model in MODELS else DEFAULT_MODEL
        params = dict(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            output_config={"effort": "low"},  # a quick read: keep the thinking short
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": base64.standard_b64encode(png).decode("ascii")}},
                {"type": "text", "text": ASK.get(kind, ASK["tooltip"])},
            ]}],
        )
        client = self._get_client()
        if model in FALLBACK_MODELS:  # if this model declines, the API retries on Anthropic's recommended fallback
            return client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
        return client.messages.create(**params)

    def _get_client(self):
        key = self.key()
        with self._lock:
            if self._client is None or self._client_key != key:
                if self._factory is not None:
                    self._client = self._factory(key)
                else:
                    import anthropic

                    self._client = anthropic.Anthropic(api_key=key, timeout=TIMEOUT, max_retries=1)
                self._client_key = key
            return self._client

    def _count(self, response) -> None:
        usage = getattr(response, "usage", None)
        tokens_in = int(getattr(usage, "input_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "output_tokens", 0) or 0)
        _, price_in, price_out = MODELS.get(self.cfg().model, MODELS[DEFAULT_MODEL])
        with self._lock:
            self.stats["reads"] += 1
            self.stats["inputTokens"] += tokens_in
            self.stats["outputTokens"] += tokens_out
            self.stats["cost"] += (tokens_in * price_in + tokens_out * price_out) / 1_000_000

    def check(self) -> str:
        """Check the saved key can use the chosen model (no tokens used). Raises with a clear message."""
        if not sdk_installed():
            raise RuntimeError(self.unavailable() or "the Anthropic SDK isn't installed")
        if not self.key():
            raise RuntimeError("no API key saved")
        model = self.cfg().model
        try:
            info = self._get_client().models.retrieve(model)
        except Exception as exc:
            raise RuntimeError(self._explain(exc)) from None
        return f"The key works: {getattr(info, 'display_name', None) or MODELS.get(model, (model,))[0]} is ready."

    def _explain(self, exc: Exception) -> str:
        """A short, plain explanation of an API error (most specific first)."""
        try:
            import anthropic
        except ImportError:
            return str(exc) or type(exc).__name__
        model = MODELS.get(self.cfg().model, (self.cfg().model,))[0]
        if isinstance(exc, anthropic.AuthenticationError):
            return "the API key was refused (check it under Display → AI reader)"
        if isinstance(exc, anthropic.PermissionDeniedError):
            return f"this API key isn't allowed to use {model}"
        if isinstance(exc, anthropic.NotFoundError):
            return f"{model} isn't available to this API key"
        if isinstance(exc, anthropic.RateLimitError):
            return "too many requests right now (rate limited by Anthropic)"
        if isinstance(exc, anthropic.BadRequestError):
            return f"Anthropic refused the request: {getattr(exc, 'message', exc)}"
        if isinstance(exc, anthropic.APIStatusError):
            if exc.status_code >= 500:
                return "Anthropic's servers are busy; try again in a moment"
            return f"Anthropic API error {exc.status_code}: {getattr(exc, 'message', exc)}"
        if isinstance(exc, anthropic.APITimeoutError):
            return "Claude took too long to answer"
        if isinstance(exc, anthropic.APIConnectionError):
            return "can't reach Anthropic (check your internet connection)"
        return str(exc) or type(exc).__name__

    def state(self) -> dict:
        cfg = self.cfg()
        reason = self.unavailable()
        with self._lock:
            stats = dict(self.stats)
        return {
            "mode": cfg.mode, "model": cfg.model,
            "models": [{"id": m, "name": n, "input": pin, "output": pout} for m, (n, pin, pout) in MODELS.items()],
            "sdk": sdk_installed(), "ready": reason is None, "reason": None if reason == "off" else reason,
            "stats": stats,
        }
