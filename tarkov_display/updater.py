"""In-app updates from GitHub.

Checks the version number in the latest code on GitHub, downloads the code
as a ZIP, swaps it in (rolling back if anything fails) and restarts the app.
Settings and progress live in %APPDATA%\\TarkovDisplay and are never touched.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, List, Optional

from . import __version__

log = logging.getLogger(__name__)

REPO = "Grat6969/EFT-amd-control"
DEFAULT_BRANCH = "claude/tarkov-display-optimizer-30yah9"
PACKAGE = "tarkov_display"
# Files earlier versions shipped by mistake; removed when updating. (Other
# files in the app folder are never deleted: they could be yours.)
STALE_FILES = ("vermin-1.8.0-py3-none-any.whl",)


def parse_version(text: str) -> tuple:
    return tuple(int(p) for p in re.findall(r"\d+", text or "")[:4]) or (0,)


def app_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _download(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"RaidReady/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


class Updater:
    def __init__(self, branch: str = DEFAULT_BRANCH, root: Optional[Path] = None) -> None:
        self.branch = branch
        self.root = root or app_dir()
        self.last_check: dict = {}

    @property
    def zip_url(self) -> str:
        return f"https://github.com/{REPO}/archive/refs/heads/{self.branch}.zip"

    def can_update(self) -> tuple:
        if getattr(sys, "frozen", False):
            return False, "This is the standalone .exe; rebuild it from the updated code to update."
        if not (self.root / PACKAGE / "__init__.py").exists():
            return False, "Can't find the app's own files."
        if not os.access(self.root, os.W_OK):
            return False, f"No permission to write to {self.root}."
        return True, ""

    def check(self) -> dict:
        ok, reason = self.can_update()
        result = {
            "current": __version__, "latest": None, "available": False, "notes": [],
            "checked": time.time(), "error": None, "can_update": ok, "reason": reason,
        }
        try:
            result["latest"] = self._latest_version()
            result["available"] = parse_version(result["latest"]) > parse_version(__version__)
        except Exception as exc:
            result["error"] = f"Couldn't check for updates: {exc}"
        try:
            commits = json.loads(_download(f"https://api.github.com/repos/{REPO}/commits?sha={self.branch}&per_page=8", 20))
            result["notes"] = [
                {"title": c["commit"]["message"].split("\n")[0], "date": c["commit"]["author"]["date"]}
                for c in commits
            ]
        except Exception as exc:
            log.debug("Could not read change notes: %s", exc)
        self.last_check = result
        return result

    def _latest_version(self) -> str:
        """Version number in the newest code on GitHub. Asks the API first:
        raw.githubusercontent.com is cached for a few minutes after a push."""
        path = f"{PACKAGE}/__init__.py"
        sources = [
            f"https://api.github.com/repos/{REPO}/contents/{path}?ref={self.branch}",
            f"https://raw.githubusercontent.com/{REPO}/{self.branch}/{path}",
        ]
        last_error: Exception = ValueError("no source")
        for url in sources:
            try:
                raw = _download(url, 20)
                if "api.github.com" in url:
                    raw = base64.b64decode(json.loads(raw)["content"])
                match = re.search(r'__version__\s*=\s*"([^"]+)"', raw.decode("utf-8", "replace"))
                if match:
                    return match.group(1)
                last_error = ValueError("no version number in the latest code")
            except Exception as exc:
                last_error = exc
        raise last_error

    def apply(self, progress: Callable[[str], None] = lambda msg: None, data: Optional[bytes] = None) -> None:
        """Download and install the latest code. Raises on failure, leaving
        the current copy in place."""
        ok, reason = self.can_update()
        if not ok:
            raise RuntimeError(reason)
        progress("Downloading the latest version...")
        data = data if data is not None else _download(self.zip_url, 120)
        progress("Installing...")
        with tempfile.TemporaryDirectory(prefix="tarkov-update-") as tmp:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for name in zf.namelist():  # refuse paths that escape the folder
                    if name.startswith("/") or ".." in Path(name).parts:
                        raise RuntimeError(f"Unsafe path in download: {name}")
                zf.extractall(tmp)
            tops = [p for p in Path(tmp).iterdir() if p.is_dir()]
            if len(tops) != 1 or not (tops[0] / PACKAGE / "__init__.py").exists():
                raise RuntimeError("The download doesn't look like this app.")
            self._install(tops[0])
        progress("Installed.")

    def _install(self, src: Path) -> None:
        root = self.root
        package, backup = root / PACKAGE, root / f"{PACKAGE}.old"
        old_requirements = (root / "requirements.txt").read_bytes() if (root / "requirements.txt").exists() else b""
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        package.rename(backup)
        try:
            for item in src.iterdir():
                target = root / item.name
                if item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target)
        except Exception:
            shutil.rmtree(package, ignore_errors=True)
            backup.rename(package)
            raise
        shutil.rmtree(backup, ignore_errors=True)
        for name in STALE_FILES:
            try:
                (root / name).unlink()
            except OSError:
                pass
        for cache in package.rglob("__pycache__"):  # not the bundled Python's
            shutil.rmtree(cache, ignore_errors=True)
        new_requirements = (root / "requirements.txt").read_bytes() if (root / "requirements.txt").exists() else b""
        if new_requirements != old_requirements:
            self._install_requirements()

    def _install_requirements(self) -> None:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                 "-r", str(self.root / "requirements.txt")],
                cwd=self.root, timeout=600, capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            log.warning("Could not install Python packages: %s", exc)

    def restart(self, args: List[str]) -> None:
        """Start a fresh copy of the app; the caller then exits."""
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([sys.executable, "-m", PACKAGE] + args, cwd=self.root, creationflags=flags, close_fds=True)
