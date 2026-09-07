"""Serving the three consoles as three separate sites.

Guests, kitchens and the owner each get their own address. They are still one
program over one database -- an order placed on the guest site has to appear on
the kitchen screen a second later, and that only works if both are talking to
the same tables -- but nothing of one role is reachable at another's address.

The separation is by hostname. A request arriving at the guest address can
reach the guest pages and the guest API and nothing else; ask it for /admin and
it answers exactly as it would for any address that does not exist. So the
owner's console is not merely password-protected at the guest address, it is
absent from it, and there is no sign-in form there to find or to guess at.

This is deliberately a second lock rather than the first one. Every staff API
already refuses a request without the right session, and that check is what
actually protects the data. What this adds is that an address handed to five
hundred guests does not also advertise where the takings are.

Configured from Admin -> Settings, or by ZARIA_HOST_GUEST / _VENDOR / _ADMIN.
With nothing configured every address serves everything, which is the right
behaviour on the venue laptop where there is only one address to begin with.
"""
from __future__ import annotations

import os

GUEST, VENDOR, ADMIN = "guest", "vendor", "admin"
ROLES = (GUEST, VENDOR, ADMIN)

SETTING_KEYS = {GUEST: "host_guest", VENDOR: "host_vendor", ADMIN: "host_admin"}
ENV_KEYS = {GUEST: "ZARIA_HOST_GUEST", VENDOR: "ZARIA_HOST_VENDOR",
            ADMIN: "ZARIA_HOST_ADMIN"}

# Pages each role's address will serve.
PAGES = {
    GUEST:  {"/": "index.html", "/order": "index.html"},
    VENDOR: {"/": "vendor.html", "/vendor": "vendor.html", "/kitchen": "vendor.html"},
    ADMIN:  {"/": "admin.html", "/admin": "admin.html"},
}

# API prefixes each role's address will answer on. Taken from what each
# front-end actually calls, so tightening this cannot quietly break a screen.
API = {
    GUEST:  ("/api/bootstrap", "/api/live", "/api/menu", "/api/orders",
             "/api/track", "/j/"),
    VENDOR: ("/api/vendor/",),
    ADMIN:  ("/api/admin/",),
}


def normalise(host: str) -> str:
    """Bare lowercase hostname: no scheme, no port, no trailing slash."""
    host = (host or "").strip().lower()
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix):]
    host = host.split("/", 1)[0]
    # Strip the port, but leave a bracketed IPv6 literal intact.
    if host.startswith("["):
        end = host.find("]")
        if end != -1:
            host = host[:end + 1]
    elif ":" in host:
        host = host.rsplit(":", 1)[0]
    return host


def configured() -> dict[str, str]:
    """Hostname -> role, for every role that has an address set."""
    from . import db

    out: dict[str, str] = {}
    for role in ROLES:
        value = os.environ.get(ENV_KEYS[role]) or db.setting(SETTING_KEYS[role], "")
        host = normalise(value)
        if host:
            out[host] = role
    return out


def role_for(host_header: str) -> str | None:
    """Which role this address serves, or None when no addresses are set.

    None means single-site mode: one address serving all three consoles, which
    is what the venue laptop runs. An address that is not one of the configured
    ones also resolves to None rather than to a role, so adding a new address --
    a fresh tunnel, an IP typed by hand -- never silently exposes the owner's
    console. It is treated as the venue laptop's own address and serves
    everything only because it could not have been reached without being on
    that machine's network in the first place.
    """
    mapping = configured()
    if not mapping:
        return None
    return mapping.get(normalise(host_header))


def allows(role: str | None, path: str) -> bool:
    """Whether an address serving `role` may answer for `path`."""
    if role is None:
        return True                      # single-site mode: everything is served
    if path in PAGES[role]:
        return True
    if any(path == p.rstrip("/") or path.startswith(p) for p in API[role]):
        return True
    # Static assets are shared by all three consoles.
    return not (path.startswith("/api/") or path in _ALL_PAGES)


_ALL_PAGES = {p for pages in PAGES.values() for p in pages} | {"/vendor", "/admin", "/order"}


def page_for(role: str | None, path: str) -> str | None:
    """The HTML file to serve, or None if this address does not serve that page."""
    if role is None:
        return {"/": "index.html", "/order": "index.html", "/vendor": "vendor.html",
                "/kitchen": "vendor.html", "/admin": "admin.html"}.get(path)
    return PAGES[role].get(path)
