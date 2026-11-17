"""RaidReady's local MCP server for Claude Desktop."""

import io
import json

from tarkov_display import mcp


class FakeSnap:
    progress = {"traders": {}, "tasks": [], "story": {"steps": []}}

    def export(self):
        return ("# RaidReady export\n\n## Me\n\n- Level 35\n\n## Open quests by map\n\n### Lighthouse (2)\n- **Easy Job** (Prapor)\n"
                "### Woods (1)\n- **Shootout** (Prapor)\n\n## Story chapters\n\n- **Tour**: done\n\n## Keys my open quests use\n\n- key\n")

    def data(self, name):
        return []

    def prices(self):
        return [{"id": "a", "name": "LEDX Skin Transilluminator", "short_name": "LEDX", "last_low": 900000, "avg24h": 950000,
                 "best_trader": "Therapist", "best_trader_price": 400000, "flea_banned": False}]


def talk(*messages):
    out = io.StringIO()
    mcp.serve(io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n\nnot json\n"), out, snapshot=FakeSnap)
    return [json.loads(l) for l in out.getvalue().splitlines()]


def test_handshake_and_tools():
    replies = talk({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                   {"jsonrpc": "2.0", "method": "notifications/initialized"},
                   {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                   {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "raidready_open_quests", "arguments": {"map": "light"}}},
                   {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "raidready_price", "arguments": {"item": "ledx"}}},
                   {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "nope"}},
                   {"jsonrpc": "2.0", "id": 6, "method": "bogus"})
    by_id = {r.get("id"): r for r in replies}
    assert by_id[1]["result"]["serverInfo"]["name"] == "raidready" and by_id[1]["result"]["protocolVersion"] == "2025-06-18"
    names = [t["name"] for t in by_id[2]["result"]["tools"]]
    assert "raidready_overview" in names and all(t["annotations"]["readOnlyHint"] for t in by_id[2]["result"]["tools"])
    text = by_id[3]["result"]["content"][0]["text"]
    assert "Easy Job" in text and "Shootout" not in text
    assert "flea lowest 900,000 ₽" in by_id[4]["result"]["content"][0]["text"]
    assert by_id[5]["error"]["code"] == -32602 and by_id[6]["error"]["code"] == -32601
    assert by_id[None]["error"]["code"] == -32700  # the line that wasn't JSON
    assert len(replies) == 7  # no reply to the notification


def test_install_into_claude_desktop(tmp_path):
    path = tmp_path / "Claude" / "claude_desktop_config.json"
    result = mcp.install_claude_desktop(path)
    config = json.loads(path.read_text())
    assert config["mcpServers"]["raidready"]["args"] == ["-m", "tarkov_display", "mcp"]
    assert mcp.claude_desktop_status(path)["installed"] is True
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
    mcp.install_claude_desktop(path)
    config = json.loads(path.read_text())
    assert set(config["mcpServers"]) == {"other", "raidready"} and config["theme"] == "dark"
    assert json.loads(path.with_suffix(".json.bak").read_text())["theme"] == "dark"
    path.write_text("{ broken")
    import pytest

    with pytest.raises(ValueError):
        mcp.install_claude_desktop(path)
    assert path.read_text() == "{ broken"  # left alone


def test_snapshot_reads_saved_state(webapp):
    webapp.store.refresh("tasks"), webapp.store.refresh("maps"), webapp.store.refresh("hideout")
    webapp.progress.apply({"op": "profile", "player_level": 21})
    snap = mcp.Snapshot(webapp.cfg_dir)
    text = snap.export()
    assert "Level 21" in text and "## Open quests by map" in text
    assert "LEDX" in mcp.tool_price(snap, {"item": "ledx"})
