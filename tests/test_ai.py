"""The AI reader: Claude reads item names the text reader isn't sure of."""

import base64
import json
import struct
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from tarkov_display import ai
from tarkov_display.ai import (ASK, FALLBACK_BETA, MAX_SIDE, PER_MINUTE, SYSTEM, AiRead, AiReader, mark_cursor,
                               parse_reply, shrink, to_png)
from tarkov_display.ocr import OcrLine
from tarkov_display.profiles import AiConfig, ScanConfig
from tarkov_display.scanner import ItemScanner


def image(w, h, fill=(10, 20, 30)):
    """A BGRA image of one colour (given as RGB)."""
    r, g, b = fill
    return bytes((b, g, r, 0)) * (w * h)


def png_pixels(png):
    """Decode the RGB PNG to_png writes: (width, height, rows of RGB bytes)."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pos, chunks = 8, {}
    while pos < len(png):
        (length,) = struct.unpack(">I", png[pos:pos + 4])
        kind = png[pos + 4:pos + 8]
        data = png[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack(">I", png[pos + 8 + length:pos + 12 + length])
        assert crc == zlib.crc32(kind + data) & 0xFFFFFFFF
        chunks[kind] = chunks.get(kind, b"") + data
        pos += 12 + length
    w, h, depth, colour = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    assert (depth, colour) == (8, 2) and b"IEND" in chunks
    raw = zlib.decompress(chunks[b"IDAT"])
    rows = [raw[y * (w * 3 + 1):(y + 1) * (w * 3 + 1)] for y in range(h)]
    assert all(r[0] == 0 for r in rows)
    return w, h, [r[1:] for r in rows]


# -- images and replies -------------------------------------------------------------


def test_png_keeps_size_and_colours():
    w, h, rows = png_pixels(to_png(image(7, 3, (200, 100, 50)), 7, 3))
    assert (w, h) == (7, 3) and rows[2][:3] == bytes((200, 100, 50))


def test_cursor_mark():
    img = mark_cursor(image(60, 40), 60, 40, 30, 20)
    px = lambda x, y: img[(y * 60 + x) * 4:(y * 60 + x) * 4 + 3]
    assert px(30, 20) == bytes((30, 20, 10))   # the very centre stays clear
    assert px(37, 20) == bytes((0, 0, 255))    # the arms are red (BGR)
    assert px(30, 13) == bytes((0, 0, 255))
    assert mark_cursor(image(10, 10), 10, 10, 2, 2)  # near the edge: no crash


def test_big_images_are_shrunk():
    w0 = MAX_SIDE * 2 + 64
    img, w, h = shrink(image(w0, 40), w0, 40)
    assert max(w, h) <= MAX_SIDE and len(img) == w * h * 4
    small = image(100, 40)
    assert shrink(small, 100, 40) == (small, 100, 40)


@pytest.mark.parametrize("reply, name", [
    ("Graphics card", "Graphics card"),
    ('"LEDX Skin Transilluminator".', "LEDX Skin Transilluminator"),
    ("\n  Bolts\nanything else", "Bolts"),
    ("NONE", None), ("none", None), ("", None), (None, None), ("x" * 200, None),
])
def test_parse_reply(reply, name):
    assert parse_reply(reply) == name


# -- the reader, with a stand-in client ---------------------------------------------


class FakeClient:
    def __init__(self, text="Graphics card", stop="end_turn", fail=None):
        self.calls = []
        self.text, self.stop, self.fail = text, stop, fail
        self.messages = SimpleNamespace(create=lambda **kw: self._create(False, kw))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: self._create(True, kw)))
        self.models = SimpleNamespace(retrieve=lambda model: SimpleNamespace(display_name="Claude Opus 5.5"))

    def _create(self, beta, kw):
        self.calls.append((beta, kw))
        if self.fail:
            raise self.fail
        return SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(type="text", text=self.text)],
                               usage=SimpleNamespace(input_tokens=200, output_tokens=30))


@pytest.fixture()
def sdk(monkeypatch):
    monkeypatch.setattr(ai, "sdk_installed", lambda: True)


def reader(client, mode="unsure", model="claude-opus-5-5", key="sk-ant-test", clock=None):
    cfg = AiConfig(mode=mode, model=model)
    t = {"now": 0.0}
    r = AiReader(lambda: cfg, lambda: key, client_factory=lambda k: client, clock=clock or (lambda: t["now"]))
    r.t, r.c = t, cfg
    return r


def test_asks_opus_with_a_fallback_and_low_effort(sdk):
    client = FakeClient()
    r = reader(client)
    read = r.read(image(40, 12), 40, 12, "tooltip")
    assert read == AiRead("Graphics card")
    beta, kw = client.calls[0]
    assert beta and kw["betas"] == [FALLBACK_BETA] and kw["fallbacks"] == "default"
    assert kw["model"] == "claude-opus-5-5" and kw["output_config"] == {"effort": "low"} and kw["system"] == SYSTEM
    assert "thinking" not in kw and "temperature" not in kw
    img, text = kw["messages"][0]["content"]
    assert img["source"]["media_type"] == "image/png" and text["text"] == ASK["tooltip"]
    assert png_pixels(base64.b64decode(img["source"]["data"]))[:2] == (40, 12)
    assert r.stats["reads"] == 1 and abs(r.stats["cost"] - (200 * 4 + 30 * 20) / 1e6) < 1e-12


def test_haiku_has_no_server_side_fallback(sdk):
    client = FakeClient()
    reader(client, model="claude-haiku-5-5").read(image(40, 12), 40, 12)
    beta, kw = client.calls[0]
    assert not beta and "fallbacks" not in kw and "betas" not in kw and kw["model"] == "claude-haiku-5-5"


def test_area_reads_mark_the_mouse(sdk):
    client = FakeClient()
    reader(client).read(image(80, 40), 80, 40, "area", cursor=(40, 20))
    img, text = client.calls[0][1]["messages"][0]["content"]
    assert text["text"] == ASK["area"]
    _, _, rows = png_pixels(base64.b64decode(img["source"]["data"]))
    assert rows[20][(46) * 3:(46) * 3 + 3] == bytes((255, 0, 0))  # red, in RGB


def test_same_image_is_answered_from_memory(sdk):
    client = FakeClient()
    r = reader(client)
    r.read(image(40, 12), 40, 12)
    again = r.read(image(40, 12), 40, 12)
    assert again.name == "Graphics card" and again.cached and len(client.calls) == 1 and r.stats["cached"] == 1


def test_reads_per_minute_are_capped(sdk):
    client = FakeClient()
    r = reader(client)
    for i in range(PER_MINUTE):
        assert r.read(image(40, 12, (i, 0, 0)), 40, 12).error is None
    over = r.read(image(40, 12, (99, 1, 1)), 40, 12)
    assert over.error and "skipped" in over.error and len(client.calls) == PER_MINUTE
    r.t["now"] = 61.0
    assert r.read(image(40, 12, (99, 1, 1)), 40, 12).error is None


def test_refusals_and_failures_are_reported_not_raised(sdk):
    assert reader(FakeClient(stop="refusal")).read(image(4, 4), 4, 4).error == "Claude declined to read that image"
    r = reader(FakeClient(fail=RuntimeError("boom")))
    assert r.read(image(4, 4), 4, 4).error == "boom" and r.stats["errors"] == 1 and r.stats["lastError"] == "boom"
    assert reader(FakeClient(text="NONE")).read(image(4, 4), 4, 4) == AiRead(None)


def test_when_claude_is_asked(sdk):
    r = reader(FakeClient())
    assert r.wanted(sure=False) and not r.wanted(sure=True)
    r.c.mode = "always"
    assert r.wanted(sure=True)
    r.c.mode = "off"
    assert not r.wanted(sure=False) and r.unavailable() == "off"
    assert not reader(FakeClient(), key="").wanted(sure=False)


def test_without_the_sdk(monkeypatch):
    monkeypatch.setattr(ai, "sdk_installed", lambda: False)
    r = reader(FakeClient())
    assert not r.wanted(sure=False) and "SDK" in r.unavailable()
    with pytest.raises(RuntimeError):
        r.check()


def test_state_and_key_check(sdk):
    r = reader(FakeClient())
    assert r.check() == "The key works: Claude Opus 5.5 is ready."
    st = r.state()
    assert st["ready"] and st["mode"] == "unsure" and [m["id"] for m in st["models"]][0] == "claude-opus-5-5"


# -- the price check using Claude's answer ------------------------------------------


class FakeScreen:
    def cursor_pos(self):
        return 1000, 500

    def target_rect(self):
        return 0, 0, 1920, 1080

    def grab(self, x, y, w, h, scale=1):
        return b"\x80" * (w * scale * h * scale * 4), w * scale, h * scale


class FakeOcr:
    max_dimension = 2600

    def __init__(self, lines):
        self.lines = [OcrLine(t, 1000, 500) for t in lines]

    def read(self, bgra, w, h):
        return list(self.lines)


class FakeAi:
    def __init__(self, mode="unsure", answer=AiRead("Graphics card")):
        self.mode, self.answer, self.calls = mode, answer, []

    def wanted(self, sure):
        return self.mode == "always" or (self.mode == "unsure" and not sure)

    def read(self, bgra, w, h, kind="tooltip", cursor=None):
        self.calls.append((kind, cursor))
        return self.answer


ITEMS = [SimpleNamespace(id="gpu", name="Graphics card", short_name="GPU", is_preset=False),
         SimpleNamespace(id="toolset", name="Toolset", short_name="Toolset", is_preset=False)]


def scanner(lines, fake_ai):
    s = object.__new__(ItemScanner)
    s.prices, s.cfg, s.debug_dir = SimpleNamespace(items=ITEMS), ScanConfig(), None
    s.screen, s.ocr, s.ai = FakeScreen(), FakeOcr(lines), fake_ai
    s._matcher = s._matcher_for = None
    return s


BOX = (1015, 512, 1155, 536)


def test_claude_fixes_a_misread_tooltip():
    fake = FakeAi()
    result = scanner(["Grphcs crd"], fake).read_tooltip(BOX, (1000, 500))
    assert result.match.item.id == "gpu" and result.via == "claude" and fake.calls == [("tooltip", None)]
    assert "Claude: Graphics card" in result.lines


def test_an_exact_read_doesnt_ask_claude_unless_always():
    fake = FakeAi()
    assert scanner(["Graphics card"], fake).read_tooltip(BOX, (1000, 500)).via == "text" and fake.calls == []
    fake = FakeAi(mode="always", answer=AiRead("Toolset"))
    result = scanner(["Graphics card"], fake).read_tooltip(BOX, (1000, 500))
    assert result.match.item.id == "toolset" and result.via == "claude"  # with "always", Claude's answer wins


def test_when_claude_cant_help_the_text_reader_answer_stays():
    result = scanner(["Graphlcs card"], FakeAi(answer=AiRead(error="can't reach Anthropic"))).read_tooltip(BOX, (1000, 500))
    assert result.match.item.id == "gpu" and result.via == "text" and result.ai_error == "can't reach Anthropic"
    result = scanner(["Graphlcs card"], FakeAi(answer=AiRead("Moon rock"))).read_tooltip(BOX, (1000, 500))
    assert result.match.item.id == "gpu" and "isn't in the price list" in result.ai_error
    result = scanner(["Grphc"], FakeAi(answer=AiRead(None))).read_tooltip(BOX, (1000, 500))
    assert result.match is None and result.lines[-1] == "Claude: no item"


def test_a_box_with_no_text_isnt_sent():
    fake = FakeAi(mode="always")
    scanner([], fake).read_tooltip(BOX, (1000, 500))
    assert fake.calls == []


def test_full_reads_ask_claude_about_possible_grid_labels():
    fake = FakeAi()
    result = scanner(["Toolset", "GPU"], fake).scan(strict=True)  # only names that can be grid labels
    assert result.match.item.id == "gpu" and result.via == "claude"
    kind, cursor = fake.calls[0]
    assert kind == "area" and cursor == (160 * 2, 90 * 2)  # where the mouse is in the (2x) capture
    fake = FakeAi()
    scanner(["Stash", "Sort"], fake).scan(strict=True)  # nothing like an item name: not worth a read
    assert fake.calls == []
    scanner(["Toolset", "GPU"], fake).scan(strict=True, ask_ai=False)  # hover's early read
    assert fake.calls == []


# -- the settings, through the app's API --------------------------------------------


def test_ai_settings_api(webapp, monkeypatch):
    from tests.test_server import body, call

    monkeypatch.setattr(ai, "sdk_installed", lambda: False)
    s = webapp.server
    state = body(call(s, "/api/ai", "POST", {"mode": "unsure", "model": "claude-haiku-5-5", "key": " sk-ant-api03-abcdef123456 "}))
    a = state["ai"]
    assert (a["mode"], a["model"], a["key"]) == ("unsure", "claude-haiku-5-5", "sk-a…3456")
    assert webapp.app.config.ai.key.endswith("sk-ant-api03-abcdef123456") and webapp.app.ai_key() == "sk-ant-api03-abcdef123456"
    assert not a["ready"] and "SDK" in a["reason"]
    for bad in ({"mode": "sometimes"}, {"model": "gpt"}, {"key": "has spaces in it"}, {"key": 5}):
        assert call(s, "/api/ai", "POST", bad)[0] == 400
    status, resp, _ = call(s, "/api/ai/test", "POST", {})
    assert status == 400 and b"SDK" in resp
    assert body(call(s, "/api/ai", "POST", {"key": ""}))["ai"]["key"] is None
    assert body(call(s, "/api/state"))["ai"]["reads"] == 0
    saved = json.loads((webapp.cfg_dir / "config.json").read_text())
    assert saved["ai"]["mode"] == "unsure" and saved["ai"]["key"] == ""


def test_the_popup_says_when_claude_read_it(webapp, monkeypatch):
    from tarkov_display.matching import Match
    from tarkov_display.scanner import ScanResult

    shown = []
    webapp.popup = SimpleNamespace(show=lambda *a: shown.append(a), rect=None)
    monkeypatch.setattr(webapp, "item_needs", lambda item_id, limit=6: [])
    item = next(i for i in webapp.app.prices.items if i.name)
    result = ScanResult(Match(item, 1.0, item.name, full=True), [item.name], (500, 500), via="claude")
    webapp._popup(result)
    assert shown[-1][4] == "Read by Claude"
    assert webapp._scan_entry(result)["via"] == "claude"


# -- the real Anthropic SDK, against a local stand-in for the API --------------------


class FakeApi(BaseHTTPRequestHandler):
    requests = []
    status = 200

    def log_message(self, *a):
        pass

    def _reply(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("retry-after-ms", "1")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeApi.requests.append((self.path, dict(self.headers), body))
        if FakeApi.status != 200:
            kind = {401: "authentication_error", 429: "rate_limit_error"}.get(FakeApi.status, "api_error")
            return self._reply(FakeApi.status, {"type": "error", "error": {"type": kind, "message": "nope"}})
        self._reply(200, {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
                          "content": [{"type": "text", "text": "Graphics card"}], "stop_reason": "end_turn",
                          "stop_sequence": None, "usage": {"input_tokens": 120, "output_tokens": 12}})

    def do_GET(self):
        FakeApi.requests.append((self.path, dict(self.headers), None))
        if FakeApi.status != 200:
            return self._reply(FakeApi.status, {"type": "error", "error": {"type": "authentication_error", "message": "nope"}})
        self._reply(200, {"type": "model", "id": self.path.rsplit("/", 1)[-1], "display_name": "Claude Opus 5.5",
                          "created_at": "2026-01-01T00:00:00Z"})


@pytest.fixture()
def api(monkeypatch):
    pytest.importorskip("anthropic")
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}")
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    FakeApi.requests, FakeApi.status = [], 200
    yield FakeApi
    server.shutdown()


def real_reader(model="claude-opus-5-5"):
    cfg = AiConfig(mode="unsure", model=model)
    return AiReader(lambda: cfg, lambda: "sk-ant-test-key")


def test_real_sdk_request(api):
    read = real_reader().read(image(40, 12), 40, 12, "tooltip")
    assert read == AiRead("Graphics card")
    path, headers, body = api.requests[-1]
    headers = {k.lower(): v for k, v in headers.items()}
    assert path.startswith("/v1/messages")
    # The SDK picks how to send the key (x-api-key, or a bearer token in newer versions).
    assert headers.get("x-api-key") == "sk-ant-test-key" or headers.get("authorization") == "Bearer sk-ant-test-key"
    assert FALLBACK_BETA in headers.get("anthropic-beta", "") and headers.get("anthropic-version")
    assert body["model"] == "claude-opus-5-5" and body["fallbacks"] == "default" and body["max_tokens"] == 2048
    assert body["output_config"] == {"effort": "low"} and body["system"] == SYSTEM
    img = body["messages"][0]["content"][0]
    assert img["type"] == "image" and base64.b64decode(img["source"]["data"])[:4] == b"\x89PNG"


def test_real_sdk_haiku_request(api):
    real_reader("claude-haiku-5-5").read(image(40, 12), 40, 12)
    _, headers, body = api.requests[-1]
    headers = {k.lower(): v for k, v in headers.items()}
    assert "fallbacks" not in body and FALLBACK_BETA not in headers.get("anthropic-beta", "")


@pytest.mark.parametrize("status, words", [(401, "API key was refused"), (429, "rate limited"), (529, "busy")])
def test_real_sdk_errors(api, status, words):
    api.status = status
    read = real_reader().read(image(40, 12), 40, 12)
    assert read.name is None and words in read.error


def test_real_sdk_key_check(api):
    assert real_reader().check() == "The key works: Claude Opus 5.5 is ready."
    api.status = 401
    with pytest.raises(RuntimeError, match="API key was refused"):
        real_reader().check()
