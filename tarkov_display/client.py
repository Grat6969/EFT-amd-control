"""HTTP access to tarkov.dev and other JSON sources."""

from __future__ import annotations

import gzip
import json
import logging
import urllib.error
import urllib.request
from typing import Optional

log = logging.getLogger(__name__)

API_URL = "https://api.tarkov.dev/graphql"


class ApiError(RuntimeError):
    pass


def error_message(body: bytes, status: int, reason: str) -> str:
    """Best explanation available from an error response."""
    try:
        errors = json.loads(body).get("errors") or []
        messages = [e.get("message", str(e)) if isinstance(e, dict) else str(e) for e in errors]
        if messages:
            return f"HTTP {status}: " + "; ".join(messages[:3])
    except (ValueError, AttributeError):
        pass
    text = body.decode("utf-8", "replace").strip()
    return f"HTTP {status} {reason}" + (f": {text[:300]}" if text else "")


def drop_nulls(value):
    """The same data without null list entries. GraphQL puts a null in a list
    where one entry failed (e.g. a quest missing a translation) and still
    sends the rest; code reading the lists then needn't check every entry."""
    if isinstance(value, list):
        return [drop_nulls(v) for v in value if v is not None]
    if isinstance(value, dict):
        return {k: drop_nulls(v) for k, v in value.items()}
    return value


class TarkovClient:
    """Sends requests to tarkov.dev; ``game_mode`` is "regular" or "pve"."""

    def __init__(self, game_mode: str = "regular", timeout: float = 60) -> None:
        self.game_mode = game_mode
        self.timeout = timeout

    def send(self, req: urllib.request.Request) -> bytes:
        from . import __version__

        req.add_header("Accept", "application/json")
        req.add_header("Accept-Encoding", "gzip")
        req.add_header("User-Agent", f"RaidReady/{__version__}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                encoding = resp.headers.get("Content-Encoding")
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            if exc.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            raise ApiError(error_message(raw, exc.code, exc.reason)) from None
        return gzip.decompress(raw) if encoding == "gzip" else raw

    def get_json(self, url: str):
        return json.loads(self.send(urllib.request.Request(url)))

    def query(self, template: str, variables: Optional[dict] = None, **params) -> dict:
        """Run a GraphQL query. ``%(mode)s`` in the template becomes the
        game-mode argument; other ``%(name)s`` fields come from ``params``.
        Anything user-supplied goes in ``variables``, never the template."""
        mode = ", gameMode: pve" if self.game_mode == "pve" else ""
        payload = {"query": template % dict(mode=mode, **params)}
        if variables:
            payload["variables"] = variables
        req = urllib.request.Request(
            API_URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
        )
        raw = self.send(req)
        result = json.loads(raw)
        if result.get("errors"):
            log.debug("tarkov.dev reported: %s", result["errors"])
        if not result.get("data"):
            raise ApiError(error_message(raw, 200, "OK"))
        return drop_nulls(result["data"])
