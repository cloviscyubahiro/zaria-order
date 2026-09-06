"""Minimal HTTP plumbing on top of http.server: routing, JSON, cookies,
static files, security headers.
"""
from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import re
import traceback
from http.cookies import SimpleCookie
from typing import Callable
from urllib.parse import parse_qs, urlparse

from . import config

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("font/otf", ".otf")

MAX_BODY = 256 * 1024


class HttpError(Exception):
    def __init__(self, status: int, message: str, field: str = ""):
        super().__init__(message)
        self.status = status
        self.message = message
        self.field = field


class Request:
    def __init__(self, handler):
        self._h = handler
        parsed = urlparse(handler.path)
        self.path = posixpath.normpath(parsed.path or "/")
        if not self.path.startswith("/"):
            self.path = "/" + self.path
        self.method = handler.command.upper()
        self.query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        self.params: dict[str, str] = {}
        self._body = None
        self._json = None
        self.cookies = SimpleCookie()
        raw_cookie = handler.headers.get("Cookie")
        if raw_cookie:
            try:
                self.cookies.load(raw_cookie)
            except Exception:
                pass

    @property
    def headers(self):
        return self._h.headers

    def cookie(self, name: str, default: str = "") -> str:
        m = self.cookies.get(name)
        return m.value if m else default

    @property
    def via_proxy(self) -> bool:
        """Whether this request reached us through the tunnel rather than direct.

        Only meaningful when a proxy has actually been declared; without one the
        header is attacker-controlled and means nothing.
        """
        return (os.environ.get("ZARIA_TRUST_PROXY") == "1"
                and bool(self._h.headers.get("X-Forwarded-For")))

    @property
    def ip(self) -> str:
        """Trust a proxy header only when the server was told to.

        Behind a reverse proxy (nginx, Cloudflare tunnel) set ZARIA_TRUST_PROXY=1.
        Trusting it unconditionally would let anyone spoof their way around
        every IP-based rate limit by sending their own X-Forwarded-For.

        Even then, take the *last* entry, not the first. A proxy appends the
        address it received the connection from, so anything a client sent of
        its own survives to the left of that. Reading the first entry would hand
        every guest a free choice of address, and with it a way around the rate
        limits and the venue-network check.
        """
        if os.environ.get("ZARIA_TRUST_PROXY") == "1":
            fwd = self._h.headers.get("X-Forwarded-For")
            if fwd:
                parts = [p.strip() for p in fwd.split(",") if p.strip()]
                if parts:
                    return parts[-1]
        return self._h.client_address[0]

    @property
    def is_https(self) -> bool:
        """Whether the browser's own connection to us was encrypted.

        This decides the Secure flag on session cookies, and it has to be per
        request rather than one switch for the whole server. In public mode the
        same process answers on two addresses at once: the HTTPS tunnel, and the
        plain http:// venue address that staff use inside the building. A cookie
        marked Secure is simply discarded by the browser on an http:// page, so
        a single global flag meant staff signing in on the venue address were
        authenticated and then instantly forgotten -- the password was accepted
        and the very next request came back "Please sign in."

        This server never terminates TLS itself, so a direct connection is
        always plain. Only the tunnel can be https, and only when it says so.
        """
        if self.via_proxy:
            proto = (self._h.headers.get("X-Forwarded-Proto") or "https").strip().lower()
            return proto == "https"
        return False

    @property
    def on_venue_network(self) -> bool:
        """True when this request came from inside the venue, not the internet.

        Once the system is reachable publicly, the staff consoles are reachable
        publicly too. This is what lets them be shut back down to the building.

        The test is how the request arrived, not what its address looks like.
        Address ranges are the obvious idea and the wrong one: Zaria's Wi-Fi
        hands out addresses in a public range, so a check for 192.168.x would
        decide that staff standing in the building are on the internet and lock
        them out. Arriving through the tunnel is what actually means "outside".
        """
        return not self.via_proxy

    def body(self) -> bytes:
        if self._body is None:
            try:
                length = int(self._h.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length > MAX_BODY:
                raise HttpError(413, "Request too large.")
            self._body = self._h.rfile.read(length) if length > 0 else b""
        return self._body

    def json(self) -> dict:
        if self._json is None:
            raw = self.body()
            if not raw:
                self._json = {}
            else:
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    raise HttpError(400, "Malformed JSON body.")
                if not isinstance(parsed, dict):
                    raise HttpError(400, "Request body must be a JSON object.")
                self._json = parsed
        return self._json


class Response:
    def __init__(self, status=200, body=b"", content_type="text/plain; charset=utf-8",
                 headers=None):
        self.status = status
        self.body = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.content_type = content_type
        self.headers: list[tuple[str, str]] = list(headers or [])

    def cookie(self, name, value, *, max_age=None, http_only=True,
               same_site="Lax", path="/", secure=None):
        parts = [f"{name}={value}", f"Path={path}", f"SameSite={same_site}"]
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        if http_only:
            parts.append("HttpOnly")
        import os
        if secure if secure is not None else (os.environ.get("ZARIA_HTTPS") == "1"):
            parts.append("Secure")
        self.headers.append(("Set-Cookie", "; ".join(parts)))
        return self


def json_response(data, status=200) -> Response:
    return Response(
        status,
        json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"),
        "application/json; charset=utf-8",
    )


def redirect(location: str, status=302) -> Response:
    return Response(status, b"", headers=[("Location", location)])


# --- Router ------------------------------------------------------------------


class Router:
    def __init__(self):
        self.routes: list[tuple[str, re.Pattern, Callable]] = []

    def add(self, method: str, pattern: str, fn: Callable):
        regex = re.compile(
            "^" + re.sub(r"<(\w+)>", r"(?P<\1>[^/]+)", pattern) + "$"
        )
        self.routes.append((method.upper(), regex, fn))

    def route(self, method, pattern):
        def deco(fn):
            self.add(method, pattern, fn)
            return fn
        return deco

    def dispatch(self, req: Request):
        allowed = set()
        for method, regex, fn in self.routes:
            m = regex.match(req.path)
            if not m:
                continue
            if method != req.method:
                allowed.add(method)
                continue
            req.params = {k: v for k, v in m.groupdict().items()}
            return fn(req)
        if allowed:
            raise HttpError(405, "Method not allowed.")
        return None


# --- Static files ------------------------------------------------------------

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._/-]+$")

# Everything is same-origin and self-hosted, so the policy can be strict.
# 'unsafe-inline' is present for style only because a few elements set inline
# widths/colors; no inline <script> is used anywhere in the frontends.
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "object-src 'none'"
)

SECURITY_HEADERS = [
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "same-origin"),
    ("X-Frame-Options", "DENY"),
    ("Permissions-Policy", "geolocation=(), microphone=(), camera=(), interest-cohort=()"),
    ("Content-Security-Policy", CSP),
]


def serve_static(rel: str) -> Response | None:
    rel = rel.lstrip("/")
    if not rel or not _SAFE_NAME.match(rel) or ".." in rel:
        return None
    target = (config.WEB_DIR / rel).resolve()
    try:
        target.relative_to(config.WEB_DIR.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    ctype, _ = mimetypes.guess_type(str(target))
    data = target.read_bytes()
    cache = "public, max-age=31536000, immutable" if rel.startswith("assets/") \
        else "no-cache"
    return Response(
        200, data, ctype or "application/octet-stream",
        headers=[("Cache-Control", cache)],
    )
