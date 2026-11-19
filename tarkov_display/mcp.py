"""RaidReady as a tool for Claude Desktop (a local MCP server).

Claude Desktop starts ``python -m tarkov_display mcp`` and talks to it over
stdin/stdout (JSON-RPC 2.0, one message per line: the MCP "stdio"
transport). Every tool is read-only and works from what RaidReady has saved
on this PC (progress, tarkov.dev data, your profile, the game's logs), so it
works even when the RaidReady window is closed. Nothing is sent anywhere.

``install_claude_desktop()`` adds RaidReady to Claude Desktop's config file
(backing it up first); Settings has a button for it.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import APP_NAME, __version__, advisor, gamelogs, playerprofile, story
from .datasets import DataStore
from .profiles import default_config_dir, load_config
from .progress import Progress

PROTOCOL = "2025-06-18"
SERVER_NAME = "raidready"


class Snapshot:
    """RaidReady's saved state for the game mode it was last showing."""

    def __init__(self, cfg_dir: Optional[Path] = None) -> None:
        self.cfg_dir = cfg_dir or default_config_dir()
        self.config = load_config(self.cfg_dir / "config.json")
        self.mode = self.config.game_mode
        self.store = DataStore(self.cfg_dir, self.mode)
        self.progress = Progress(self.cfg_dir / f"progress_{self.mode}.json").snapshot()

    def data(self, name: str):
        return self.store.snapshot(name)["data"]

    def logs_folder(self):
        return gamelogs.default_folder(self.config.logs.path)

    def prices(self) -> List[dict]:
        try:
            with open(self.cfg_dir / f"prices_{self.mode}.json", "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return []
        items = raw.get("items") if isinstance(raw, dict) else raw
        return [i for i in items or [] if isinstance(i, dict)]

    def item_names(self) -> Dict[str, str]:
        return {i.get("id"): i.get("name") for i in self.prices() if i.get("id") and i.get("name")}

    def profile(self) -> Optional[dict]:
        return playerprofile.ProfileStore(self.cfg_dir).cached(self.mode)

    def export(self) -> str:
        prices = {i.get("id"): {"flea": i.get("last_low") or i.get("lastLowPrice") or i.get("avg24h") or i.get("avg24hPrice"),
                                "banned": bool(i.get("flea_banned") or i.get("banned"))} for i in self.prices()}
        return advisor.build(progress=self.progress, tasks=self.data("tasks"), stations=self.data("hideout"),
                             maps=self.data("maps"), history=advisor.history_for(self.logs_folder()),
                             item_names=self.item_names(), game_mode=self.mode, app_version=__version__,
                             traders=self.data("traders"), prices=prices, profile=self.profile())


def _section(text: str, *titles: str) -> str:
    """The parts of the export under these ## headings."""
    out, keep = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            keep = any(line[3:].startswith(t) for t in titles)
        if keep:
            out.append(line)
    return "\n".join(out).strip() or "Nothing saved for that yet."


# -- tools ---------------------------------------------------------------------------------

def tool_overview(snap: Snapshot, args: dict) -> str:
    return snap.export()


def tool_open_quests(snap: Snapshot, args: dict) -> str:
    text = _section(snap.export(), "Open quests by map")
    wanted = str(args.get("map") or "").strip().lower()
    if not wanted:
        return text
    blocks, current = [], []
    for line in text.splitlines():
        if line.startswith("### "):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)
    hit = [b for b in blocks if wanted in b[0].lower()]
    return "\n".join(l for b in hit for l in b) if hit else f"No open quests on a map matching '{args.get('map')}'."


def tool_story(snap: Snapshot, args: dict) -> str:
    return _section(snap.export(), "Story chapters")


def tool_keys(snap: Snapshot, args: dict) -> str:
    return _section(snap.export(), "Keys my open quests use")


def tool_hideout(snap: Snapshot, args: dict) -> str:
    return _section(snap.export(), "Hideout", "Items I've set aside")


def tool_raids(snap: Snapshot, args: dict) -> str:
    return _section(snap.export(), "My recent raids", "Recent flea market sales", "My profile")


def tool_lightkeeper(snap: Snapshot, args: dict) -> str:
    rows = advisor.lightkeeper_checklist(snap.data("tasks"), snap.data("traders"), snap.progress)
    marks = {True: "✅", False: "❌", None: "❔"}
    return "\n".join(f"- {marks[r['ok']]} {r['label']}" + (f" ({r['detail']})" if r["detail"] else "") for r in rows)


def tool_price(snap: Snapshot, args: dict) -> str:
    query = str(args.get("item") or "").strip().lower()
    if not query:
        return "Give an item name, e.g. 'LEDX' or 'graphics card'."
    words = query.split()
    hits = [i for i in snap.prices()
            if all(w in f"{i.get('name', '')} {i.get('short_name') or i.get('shortName') or ''}".lower() for w in words)]
    if not hits:
        return f"No item matching '{args.get('item')}' in RaidReady's saved price list."
    out = []
    for i in hits[:8]:
        flea = i.get("last_low") or i.get("lastLowPrice")
        avg = i.get("avg24h") or i.get("avg24hPrice")
        trader = i.get("best_trader") or i.get("trader")
        tprice = i.get("best_trader_price") or i.get("traderPrice")
        bits = [f"flea lowest {flea:,} ₽" if isinstance(flea, int) else None,
                f"24h avg {avg:,} ₽" if isinstance(avg, int) else None,
                f"sells to {trader} for {tprice:,} ₽" if trader and isinstance(tprice, int) else None,
                "can't be sold on the flea" if i.get("flea_banned") or i.get("banned") else None]
        out.append(f"- **{i.get('name')}**: " + ", ".join(b for b in bits if b))
    return "\n".join(out)


TOOLS: Dict[str, dict] = {
    "raidready_overview": {
        "fn": tool_overview,
        "description": "Everything RaidReady knows about the player's Escape from Tarkov progress: level, trader standing, "
                       "open quests by map, story chapters, keys, hideout, recent raids, flea sales and their tarkov.dev "
                       "profile. Start here when helping plan raids.",
        "schema": {"type": "object", "properties": {}},
    },
    "raidready_open_quests": {
        "fn": tool_open_quests,
        "description": "The player's open quests grouped by map, with unfinished objectives. Optionally one map.",
        "schema": {"type": "object", "properties": {"map": {"type": "string", "description": "Map name, e.g. Lighthouse"}}},
    },
    "raidready_story": {"fn": tool_story, "description": "Where the player is in each story chapter, with next steps.",
                        "schema": {"type": "object", "properties": {}}},
    "raidready_keys": {"fn": tool_keys, "description": "Keys the player's open quests need, which they have, and flea prices.",
                       "schema": {"type": "object", "properties": {}}},
    "raidready_hideout": {"fn": tool_hideout, "description": "Next level of each hideout station and items set aside.",
                          "schema": {"type": "object", "properties": {}}},
    "raidready_raids": {"fn": tool_raids, "description": "Recent raids from the game logs (map, PMC/Scav, length, ping), "
                                                         "flea sales and public profile stats.",
                        "schema": {"type": "object", "properties": {}}},
    "raidready_lightkeeper": {"fn": tool_lightkeeper, "description": "Checklist of what's left before Lightkeeper access.",
                              "schema": {"type": "object", "properties": {}}},
    "raidready_price": {
        "fn": tool_price,
        "description": "Flea and trader prices for an item from RaidReady's last price download.",
        "schema": {"type": "object", "properties": {"item": {"type": "string"}}, "required": ["item"]},
    },
}


# -- JSON-RPC over stdio -----------------------------------------------------------------------

def handle(message: dict, snapshot: Callable[[], Snapshot]) -> Optional[dict]:
    """The reply to one message (None for notifications)."""
    method, mid = message.get("method"), message.get("id")
    if mid is None:  # notification (e.g. notifications/initialized)
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, text):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}

    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion")
        return ok({"protocolVersion": asked or PROTOCOL, "capabilities": {"tools": {}},
                   "serverInfo": {"name": SERVER_NAME, "title": APP_NAME, "version": __version__},
                   "instructions": "Read-only access to the player's Escape from Tarkov progress saved by RaidReady. "
                                   "Call raidready_overview first; it includes their goal and kit."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": name, "description": t["description"], "inputSchema": t["schema"],
                              "annotations": {"readOnlyHint": True}} for name, t in TOOLS.items()]})
    if method == "tools/call":
        params = message.get("params") or {}
        tool = TOOLS.get(params.get("name"))
        if not tool:
            return err(-32602, f"unknown tool {params.get('name')!r}")
        try:
            text = tool["fn"](snapshot(), params.get("arguments") or {})
            return ok({"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as exc:  # report it to Claude rather than crash
            return ok({"content": [{"type": "text", "text": f"RaidReady couldn't answer: {exc}"}], "isError": True})
    return err(-32601, f"method not found: {method}")


def serve(stdin=None, stdout=None, snapshot: Callable[[], Snapshot] = Snapshot) -> int:
    if stdin is None and stdout is None:
        # Windows pipes default to the ANSI code page and \r\n; MCP wants UTF-8 lines.
        for stream, kw in ((sys.stdin, {}), (sys.stdout, {"newline": "\n"})):
            try:
                stream.reconfigure(encoding="utf-8", **kw)
            except (AttributeError, ValueError):
                pass
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = handle(message, snapshot) if isinstance(message, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0


# -- adding RaidReady to Claude Desktop ------------------------------------------------------

def claude_config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "Claude" / "claude_desktop_config.json"


def claude_config_paths() -> List[Path]:
    """Where Claude Desktop may keep its settings. The normal installer uses
    %APPDATA%\\Claude; the Microsoft Store version keeps a private copy under
    %LOCALAPPDATA%\\Packages\\Claude_*\\LocalCache\\Roaming\\Claude and never reads
    the normal one. Folders that exist come first."""
    paths = [claude_config_path()]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        try:
            for pkg in sorted(Path(local, "Packages").glob("Claude_*")):
                paths.append(pkg / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json")
        except OSError:
            pass
    existing = [p for p in paths if p.parent.is_dir()]
    return existing or paths[:1]


def server_command() -> dict:
    """How Claude Desktop should start this server: this Python (console
    version, so stdin/stdout work), with the app's folder on PYTHONPATH.
    Only the keys Claude Desktop documents (command, args, env)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        exe = exe.parent / "python.exe"
    app_dir = Path(__file__).resolve().parent.parent
    return {"command": str(exe), "args": ["-m", "tarkov_display", "mcp"],
            "env": {"PYTHONPATH": str(app_dir), "PYTHONIOENCODING": "utf-8"}}


def _install_one(path: Path) -> dict:
    config: dict = {}
    if path.exists():
        try:
            config = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
        except ValueError:
            raise ValueError(f"Claude Desktop's config file isn't valid JSON, so I left it alone: {path}") from None
        if not isinstance(config, dict):
            raise ValueError(f"Unexpected content in {path}; left it alone.")
        shutil.copy2(path, path.with_suffix(".json.bak"))
    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("Claude Desktop's config has an unexpected mcpServers entry; left it alone.")
    servers[SERVER_NAME] = server_command()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return {"path": str(path), "server": servers[SERVER_NAME]}


def install_claude_desktop(path: Optional[Path] = None) -> dict:
    """Add (or update) RaidReady in Claude Desktop's config: every copy it
    may read (see claude_config_paths). Old files are kept as .bak. Claude
    Desktop must be quit fully (tray icon > Quit) and opened again."""
    paths = [path] if path else claude_config_paths()
    done = [_install_one(p) for p in paths]
    return {"path": done[0]["path"], "paths": [d["path"] for d in done], "server": done[0]["server"], "time": time.time()}


def _log_tail(folder: Path, lines: int = 25) -> List[str]:
    """The end of Claude Desktop's log about this server, if it has one."""
    out: List[str] = []
    for name in (f"mcp-server-{SERVER_NAME}.log", "mcp.log"):
        try:
            text = (folder / "logs" / name).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        if name == "mcp.log":
            text = [l for l in text if SERVER_NAME in l]
        out += [f"[{name}] {l}" for l in text[-lines:]]
    return out[-lines:]


def claude_desktop_status(path: Optional[Path] = None) -> dict:
    paths = [path] if path else claude_config_paths()
    configs = []
    for p in paths:
        installed = False
        try:
            installed = SERVER_NAME in (json.loads(p.read_text(encoding="utf-8-sig")).get("mcpServers") or {})
        except (OSError, ValueError, AttributeError):
            pass
        configs.append({"path": str(p), "installed": installed, "store": "Packages" in p.parts,
                        "folderExists": p.parent.is_dir()})
    first = configs[0]
    return {"path": first["path"], "installed": all(c["installed"] for c in configs), "claudeFound": any(c["folderExists"] for c in configs),
            "configs": configs, "log": _log_tail(Path(first["path"]).parent), "command": server_command()}


def self_test(timeout: float = 25) -> dict:
    """Start the server the way Claude Desktop would and ask it for its tools."""
    import subprocess

    cmd = server_command()
    env = dict(os.environ, **cmd["env"])
    messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": PROTOCOL}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run([cmd["command"], *cmd["args"]], input="\n".join(json.dumps(m) for m in messages) + "\n",
                              capture_output=True, text=True, encoding="utf-8", env=env, timeout=timeout,
                              cwd=cmd["env"]["PYTHONPATH"], creationflags=flags)
    except FileNotFoundError:
        return {"ok": False, "error": f"Python wasn't found at {cmd['command']}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "The server didn't answer within 25 seconds"}
    tools = 0
    for line in proc.stdout.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            return {"ok": False, "error": f"Unexpected output (it must be JSON only): {line[:200]}"}
        if msg.get("id") == 2:
            tools = len((msg.get("result") or {}).get("tools") or [])
    if tools:
        return {"ok": True, "tools": tools}
    err = (proc.stderr or "").strip().splitlines()[-8:]
    return {"ok": False, "error": "\n".join(err) or f"No answer (exit code {proc.returncode})"}
