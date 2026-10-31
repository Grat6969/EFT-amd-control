"""Runs RaidReady on tarkov.dev data saved by ``tests/live_check.py --save DIR``.

    python -m tests.replay DIR [PORT]

Every download the app makes is answered from DIR (laid out by URL). Anything
that wasn't saved fails like a network error would, and GraphQL is down, as it
often is for real. The live-data workflow uses this to crawl the UI on real data.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path


def install(root: Path) -> None:
    from tarkov_display.client import ApiError, TarkovClient

    def get_json(self, url):
        path = root / (url.split("://", 1)[-1] + ".json")
        if not path.is_file():
            raise ApiError(f"not saved: {url}")
        return json.loads(path.read_text(encoding="utf-8"))

    def get_bytes(self, url):
        path = root / url.split("://", 1)[-1]
        if not path.is_file():
            raise ApiError(f"not saved: {url}")
        return path.read_bytes()

    def query(self, *args, **kwargs):
        raise ApiError("HTTP 422: GraphQL server unavailable. Try again later.")

    TarkovClient.get_json = get_json
    TarkovClient.get_bytes = get_bytes
    TarkovClient.query = query


def main(root: str, port: int = 47999) -> None:
    os.environ["APPDATA"] = tempfile.mkdtemp(prefix="raidready-replay-")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    install(Path(root).resolve())
    from tarkov_display.webapp import WebApp

    web = WebApp(open_on_start=False, port=port)
    web.app.config.keep_running = True  # a crawler reloads pages; don't quit when they disconnect
    web.run()


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 47999)
