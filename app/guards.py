"""Session guards shared by the vendor and admin APIs."""
from __future__ import annotations

from . import db, security
from .web import HttpError, Request

VENDOR_COOKIE = "zc_vendor"
ADMIN_COOKIE = "zc_admin"
GUEST_COOKIE = "zc_guest"

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class Actor:
    def __init__(self, kind, user_id, username, display, vendor_id=None,
                 csrf="", must_change=False):
        self.kind = kind
        self.user_id = user_id
        self.username = username
        self.display = display
        self.vendor_id = vendor_id
        self.csrf = csrf
        self.must_change = must_change


def staff_network_ok(req: Request) -> bool:
    """Whether staff screens may be used from where this request came from.

    Guests reach the system over the internet so that people on their own data
    bundles can order. Kitchens and admin do not need that — they are in the
    building — so the venue can require them to be on the venue network, which
    keeps the login pages off the public internet entirely.
    """
    if db.setting("staff_network", "ANY") != "LAN_ONLY":
        return True
    return req.on_venue_network


def require_staff_network(req: Request) -> None:
    if not staff_network_ok(req):
        raise HttpError(
            403,
            "Staff sign-in is limited to the venue network. Connect to Zaria Wi-Fi "
            "and use the venue address, not the public one.",
        )


def _authenticate(req: Request, kind: str, cookie_name: str) -> Actor:
    require_staff_network(req)
    sess = security.load_session(req.cookie(cookie_name))
    if sess is None or sess["kind"] != kind:
        raise HttpError(401, "Please sign in.")

    if kind == "vendor":
        row = db.q1(
            "SELECT u.*, v.name AS vendor_name FROM vendor_users u"
            " JOIN vendors v ON v.id=u.vendor_id"
            " WHERE u.id=? AND u.is_active=1 AND v.is_active=1",
            (sess["user_id"],),
        )
    else:
        row = db.q1(
            "SELECT * FROM admin_users WHERE id=? AND is_active=1", (sess["user_id"],)
        )
    if row is None:
        security.destroy_session(req.cookie(cookie_name))
        raise HttpError(401, "This account is no longer active.")

    # CSRF: state-changing calls must echo the session's token in a header.
    # SameSite=Lax already blocks most cross-site POSTs; this covers the rest.
    if req.method not in SAFE_METHODS:
        sent = req.headers.get("X-CSRF-Token", "")
        import hmac as _hmac
        if not sent or not _hmac.compare_digest(sent, sess["csrf"]):
            raise HttpError(403, "Your session expired. Please reload the page.")

    return Actor(
        kind=kind,
        user_id=row["id"],
        username=row["username"],
        display=row["display"] or row["username"],
        vendor_id=row["vendor_id"] if kind == "vendor" else None,
        csrf=sess["csrf"],
        must_change=bool(row["must_change"]),
    )


def require_vendor(req: Request) -> Actor:
    return _authenticate(req, "vendor", VENDOR_COOKIE)


def require_admin(req: Request) -> Actor:
    return _authenticate(req, "admin", ADMIN_COOKIE)


def guest_id(req: Request) -> str:
    """The guest's rotating browser id, hashed. Set by the client on first load."""
    return security.hash_device(req.cookie(GUEST_COOKIE))
