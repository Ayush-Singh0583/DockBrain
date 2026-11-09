"""DockBrain's HTTP API for the web app (FRONTEND/API_CONTRACT.md), on the standard library.

    python -m server [--host 127.0.0.1] [--port 8000] [--offline]

All routes live under /api/v1. Route modules export ROUTES = [(method, pattern, handler)],
where a pattern uses {name} placeholders and a handler takes a `Request` and returns
(status, payload): a JSON-ready dict, or None for 204. Handlers raise `ApiError` for
anything the client should see.

Privacy: the server binds to 127.0.0.1 by default, provider keys stay in its environment,
and logs record only the method, the route pattern, the status and the duration, never
session ids, file names, document text, questions or answers.
"""
import json
import logging
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from rag.generator import ExtractiveGenerator

from . import cards, documents
from .errors import ApiError, invalid
from .sessions import DEFAULT_TTL_SECONDS, SessionStore

try:  # the quiz routes are another session's module; without it, the quiz isn't offered
    from . import quiz
except ImportError:
    quiz = None

log = logging.getLogger("dockbrain.server")

API_PREFIX = "/api/v1"
DOCUMENT_EXTENSIONS = (".pdf", ".docx", ".txt", ".md", ".markdown")
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024
DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173"
OFFLINE_ENGINE = "Offline extractive answers (nothing is sent anywhere)"


class Request:
    """What a route handler gets: path values, query, JSON body, and the session store."""

    def __init__(self, handler: "Handler", params: dict, query: dict):
        self.handler = handler
        self.server: "DockBrainServer" = handler.server
        self.store: SessionStore = handler.server.store
        self.method = handler.command
        self.headers = handler.headers
        self.params = params
        self.query = query

    def json(self):
        """The JSON body; 400 invalid_request if malformed, 413 too_large over 64 KB."""
        length = self.headers.get("Content-Length")
        if length is None or not length.isdigit():
            raise invalid("Send the request as JSON.")
        if int(length) > MAX_JSON_BYTES:
            self.handler.close_connection = True
            raise ApiError(413, "too_large", "That request is too large.")
        raw = self.handler.rfile.read(int(length))
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise invalid("The request isn't valid JSON.") from None


class Router:
    def __init__(self):
        self.routes: list[tuple[str, re.Pattern, str, Callable]] = []

    def add(self, method: str, pattern: str, handler: Callable) -> None:
        regex = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", re.escape(pattern).replace(r"\{", "{").replace(r"\}", "}"))
        self.routes.append((method.upper(), re.compile(f"^{regex}$"), pattern, handler))

    def match(self, method: str, path: str):
        """(handler, params, pattern), or raise 404/405."""
        allowed = []
        for route_method, regex, pattern, handler in self.routes:
            found = regex.match(path)
            if found:
                if route_method == method:
                    return handler, found.groupdict(), pattern
                allowed.append(route_method)
        if allowed:
            raise ApiError(405, "invalid_request", f"This endpoint doesn't accept {method} requests.")
        raise ApiError(404, "not_found", "There's no such endpoint on this DockBrain server.")

    def methods_for(self, path: str) -> list[str]:
        return [m for m, regex, _, _ in self.routes if regex.match(path)]


class Handler(BaseHTTPRequestHandler):
    server: "DockBrainServer"
    server_version = "DockBrain"
    sys_version = ""

    def log_message(self, format, *args):  # the default logs full paths, which hold session ids
        pass

    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_DELETE(self):
        self._dispatch()

    def do_PUT(self):
        self._dispatch()

    def do_PATCH(self):
        self._dispatch()

    def do_OPTIONS(self):
        started, pattern = time.monotonic(), "(preflight)"
        path = urlsplit(self.path).path
        methods = self.server.router.methods_for(path[len(API_PREFIX):]) if path.startswith(API_PREFIX) else []
        if not methods:
            self._send(404, ApiError(404, "not_found", "There's no such endpoint.").body())
        else:
            self._send(204, None, {
                "Access-Control-Allow-Methods": ", ".join(sorted({*methods, "OPTIONS"})),
                "Access-Control-Allow-Headers": "Content-Type, Accept",
                "Access-Control-Max-Age": "600",
            })
        self._log(pattern, 404 if not methods else 204, started)

    def _dispatch(self):
        started, pattern, status = time.monotonic(), "(unknown route)", 500
        try:
            url = urlsplit(self.path)
            if not url.path.startswith(API_PREFIX):
                raise ApiError(404, "not_found", "There's no such endpoint on this DockBrain server.")
            handler, params, pattern = self.server.router.match(self.command, url.path[len(API_PREFIX):])
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            status, payload = handler(Request(self, params, query))
        except ApiError as e:
            status, payload = e.status, e.body()
        except Exception as e:  # never send internals; log only the error's type
            log.error("%s %s failed: %s", self.command, pattern, type(e).__name__)
            status, payload = 500, ApiError(500, "unknown", "Something went wrong on the server. Try again.").body()
        self._send(status, payload)
        self._log(pattern, status, started)

    def _send(self, status: int, payload: dict | None, extra: dict | None = None):
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self.headers.get("Origin")
        if origin and origin in self.server.cors_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _log(self, pattern: str, status: int, started: float):
        log.info("%s %s %d %.0fms", self.command, pattern, status, (time.monotonic() - started) * 1000)


class DockBrainServer(ThreadingHTTPServer):
    daemon_threads = True
    store: SessionStore
    router: Router
    generator_factory: Callable
    answer_engine: str
    max_document_bytes: int
    document_extensions: tuple[str, ...]
    cors_origins: set[str]

    def capabilities(self) -> dict:
        return {
            "mode": "live",
            "notes": "available",
            "ask": "available",
            "quiz": "available" if quiz is not None else "unavailable",
            "cards": "available",
            "codebase": "unavailable",
            "maxDocumentBytes": self.max_document_bytes,
            "documentExtensions": list(self.document_extensions),
            "answerEngine": self.answer_engine,
        }


def get_capabilities(request):
    return 200, request.server.capabilities()


def choose_engine(offline: bool) -> tuple[Callable, str]:
    """A factory for answer engines (one per session: each keeps per-question state) and
    its description, chosen like the command line: Ollama, Gemini, Claude, else offline."""
    from main import pick_generator  # the CLI's choice, so both behave the same

    if offline:
        return ExtractiveGenerator, OFFLINE_ENGINE
    engine, name = pick_generator(False)
    if isinstance(engine, ExtractiveGenerator):
        return ExtractiveGenerator, OFFLINE_ENGINE
    if name == "Claude":
        name = "Claude (parts of the document are sent to Anthropic)"
    return (lambda: pick_generator(False)[0]), name


def create_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    offline: bool = False,
    generator_factory: Callable | None = None,
    answer_engine: str | None = None,
    max_document_bytes: int = MAX_DOCUMENT_BYTES,
    ttl_seconds: float | None = None,
    cors_origins: str | None = None,
) -> DockBrainServer:
    """The API server, not yet serving. Tests pass `generator_factory` (and port 0) so no
    provider is ever called; `server.store` is the session store."""
    if generator_factory is None:
        generator_factory, engine_name = choose_engine(offline)
    else:
        engine_name = OFFLINE_ENGINE if isinstance(generator_factory(), ExtractiveGenerator) else "Custom answer engine"
    server = DockBrainServer((host, port), Handler)
    server.generator_factory = generator_factory
    server.answer_engine = answer_engine or engine_name
    server.max_document_bytes = max_document_bytes
    server.document_extensions = DOCUMENT_EXTENSIONS
    server.store = SessionStore(DEFAULT_TTL_SECONDS if ttl_seconds is None else ttl_seconds)
    origins = cors_origins if cors_origins is not None else os.environ.get("DOCKBRAIN_CORS_ORIGINS", DEFAULT_ORIGINS)
    server.cors_origins = {o.strip().rstrip("/") for o in origins.split(",") if o.strip()}
    server.router = Router()
    server.router.add("GET", "/capabilities", get_capabilities)
    for module in (documents, quiz, cards):
        for method, pattern, handler in getattr(module, "ROUTES", []):
            server.router.add(method, pattern, handler)
    return server
