"""Small local web server for the app window.

Listens on 127.0.0.1 only. Every API call needs the random token baked
into the page at launch, and the Host header must be our own address, so
web sites open in your browser can't drive the app.
"""

from __future__ import annotations

import hmac
import json
import logging
import mimetypes
import queue
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"
APP_ID = "tarkov-companion"
MAX_BODY = 2 * 1024 * 1024
# Fixed types: on Windows, mimetypes reads the registry, where .js or .css can
# be mapped to text/plain, and browsers then refuse to run or apply them.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8", ".woff2": "font/woff2",
}


class HttpError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class EventHub:
    """Fan-out of server-sent events to every open window."""

    def __init__(self, on_count: Callable[[int], None] = lambda n: None) -> None:
        self._subs: List[queue.Queue] = []
        self._lock = threading.Lock()
        self.on_count = on_count

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._lock:
            self._subs.append(q)
            n = len(self._subs)
        self.on_count(n)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)
            n = len(self._subs)
        self.on_count(n)

    def publish(self, event: str, data) -> None:
        payload = json.dumps(data, default=str)
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait((event, payload))
            except queue.Full:
                pass

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._subs)


Route = Tuple[str, "re.Pattern[str]", Callable]


class Server:
    def __init__(self, ctx, port: int = 0, host: str = "127.0.0.1") -> None:
        self.ctx = ctx
        self.token = secrets.token_urlsafe(24)
        self.events = EventHub(getattr(ctx, "on_clients", lambda n: None))
        self._stopping = threading.Event()
        self.routes: List[Route] = []
        self._add_routes()
        self.httpd = ThreadingHTTPServer((host, port), self._handler_class())
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="WebServer", daemon=True)
        self._thread.start()
        log.info("App window server on %s", self.url)

    def stop(self) -> None:
        self._stopping.set()
        self.httpd.shutdown()
        self.httpd.server_close()

    # -- routing ----------------------------------------------------------

    def route(self, method: str, pattern: str):
        def register(fn):
            self.routes.append((method, re.compile(f"^{pattern}$"), fn))
            return fn
        return register

    def _add_routes(self) -> None:
        ctx = self.ctx
        r = self.route

        @r("GET", "/api/bootstrap")
        def bootstrap(req, m, q, body):
            return ctx.bootstrap()

        @r("GET", "/api/state")
        def state(req, m, q, body):
            return ctx.state()

        @r("GET", "/api/items")
        def items(req, m, q, body):
            return ctx.items_payload()

        @r("GET", "/api/item/([A-Za-z0-9_-]{1,64})")
        def item(req, m, q, body):
            return ctx.item_detail(m.group(1))

        @r("GET", "/api/data/([a-z]+)")
        def data(req, m, q, body):
            wait = min(60.0, float((q.get("wait") or ["0"])[0] or 0))
            return ctx.dataset(m.group(1), wait)

        @r("POST", "/api/data/([a-z]+)/refresh")
        def refresh(req, m, q, body):
            return ctx.refresh_dataset(m.group(1))

        @r("GET", "/api/datastatus")
        def datastatus(req, m, q, body):
            return ctx.data_status()

        @r("GET", "/api/progress")
        def progress(req, m, q, body):
            return ctx.progress_snapshot()

        @r("POST", "/api/progress")
        def progress_change(req, m, q, body):
            return ctx.progress_change(body)

        @r("GET", "/api/display")
        def display(req, m, q, body):
            return ctx.display_state()

        @r("POST", "/api/display")
        def display_change(req, m, q, body):
            return ctx.display_change(body)

        @r("POST", "/api/settings")
        def settings(req, m, q, body):
            return ctx.settings_change(body)

        @r("GET", "/api/scans")
        def scans(req, m, q, body):
            return ctx.recent_scans()

        @r("GET", "/api/update")
        def update_check(req, m, q, body):
            return ctx.update_check(force=(q.get("force") or ["0"])[0] == "1")

        @r("POST", "/api/update")
        def update_apply(req, m, q, body):
            return ctx.update_apply()

        @r("POST", "/api/quit")
        def quit_app(req, m, q, body):
            ctx.quit()
            return {"ok": True}

    def _handler_class(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "TarkovCompanion"

            def log_message(self, fmt, *args):  # quiet; errors are logged elsewhere
                log.debug("http: " + fmt, *args)

            # -- helpers ---------------------------------------------------

            def _send(self, status: int, body: bytes, ctype: str, extra: Optional[dict] = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _json(self, status: int, obj) -> None:
                body = json.dumps(obj, default=str, separators=(",", ":")).encode()
                self._send(status, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})

            def _host_ok(self) -> bool:
                host = (self.headers.get("Host") or "").lower()
                return host in (f"127.0.0.1:{server.port}", f"localhost:{server.port}")

            def _token_ok(self, query: dict) -> bool:
                given = self.headers.get("X-Token") or (query.get("token") or [""])[0]
                return bool(given) and hmac.compare_digest(given, server.token)

            # -- methods ---------------------------------------------------

            def do_GET(self):
                self._dispatch("GET")

            def do_HEAD(self):
                self._dispatch("GET")

            def do_POST(self):
                self._dispatch("POST")

            def _dispatch(self, method: str) -> None:
                try:
                    if not self._host_ok():
                        raise HttpError(403, "bad host")
                    url = urlparse(self.path)
                    path, query = unquote(url.path), parse_qs(url.query)
                    if path == "/api/hello":
                        return self._json(200, {"app": APP_ID, "version": __version__})
                    if path.startswith("/api/"):
                        if not self._token_ok(query):
                            raise HttpError(403, "bad token")
                        if path == "/api/events" and method == "GET":
                            return self._events()
                        return self._api(method, path, query)
                    if method != "GET":
                        raise HttpError(405, "method not allowed")
                    return self._static(path)
                except HttpError as exc:
                    self._json(exc.status, {"error": exc.message})
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as exc:  # never kill the server thread
                    log.exception("Request failed: %s %s", method, self.path)
                    try:
                        self._json(500, {"error": str(exc)})
                    except Exception:
                        pass

            def _read_json(self):
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    raise HttpError(413, "request too large")
                if not length:
                    return None
                if "application/json" not in (self.headers.get("Content-Type") or ""):
                    raise HttpError(415, "send JSON")
                try:
                    return json.loads(self.rfile.read(length))
                except ValueError:
                    raise HttpError(400, "bad JSON") from None

            def _api(self, method: str, path: str, query: dict) -> None:
                body = self._read_json() if method == "POST" else None
                for route_method, pattern, fn in server.routes:
                    m = pattern.match(path)
                    if m and route_method == method:
                        try:
                            result = fn(self, m, query, body)
                        except (KeyError, ValueError) as exc:
                            raise HttpError(400, str(exc).strip("'\"")) from None
                        return self._json(200, result)
                raise HttpError(404, "no such API")

            def _static(self, path: str) -> None:
                if path in ("/", "/index.html"):
                    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
                    html = html.replace("{{TOKEN}}", server.token).replace("{{VERSION}}", __version__)
                    return self._send(200, html.encode(), "text/html; charset=utf-8", {
                        "Cache-Control": "no-store",
                        "Content-Security-Policy": (
                            "default-src 'self'; img-src 'self' https: data:; style-src 'self' 'unsafe-inline'; "
                            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
                        ),
                    })
                if not path.startswith("/static/"):
                    raise HttpError(404, "not found")
                target = (WEB_DIR / path[len("/static/"):]).resolve()
                if WEB_DIR not in target.parents or not target.is_file():
                    raise HttpError(404, "not found")
                ctype = CONTENT_TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                self._send(200, target.read_bytes(), ctype, {"Cache-Control": "no-cache"})

            def _events(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                self.close_connection = True
                q = server.events.subscribe()
                try:
                    hello = json.dumps(server.ctx.state(), default=str)
                    self.wfile.write(f"event: state\ndata: {hello}\n\n".encode())
                    self.wfile.flush()
                    while not server._stopping.is_set():
                        try:
                            event, payload = q.get(timeout=10)
                            self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    pass
                finally:
                    server.events.unsubscribe(q)

        return Handler


def find_running(port: int, timeout: float = 1.0) -> Optional[Dict]:
    """The app instance already listening on ``port``, if any."""
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/hello", timeout=timeout) as resp:
            info = json.loads(resp.read())
        return info if info.get("app") == APP_ID else None
    except Exception:
        return None
