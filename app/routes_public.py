"""Everything a guest's phone talks to. No login, no account."""
from __future__ import annotations

import secrets
import threading
import time
from datetime import timedelta

from . import catalog, config, db, guards, orders, security
from .web import HttpError, Request, Router, json_response, redirect

router = Router()


@router.route("GET", "/api/bootstrap")
def bootstrap(req: Request):
    """One call that fills the guest home screen."""
    token = req.query.get("t", "")
    table_code, table_id, table_error = "", None, ""

    if token:
        code = security.verify_table(token)
        if code is None:
            table_error = "That table code could not be verified. Please pick your table below."
        else:
            row = db.q1(
                "SELECT id,code,label,zone FROM venue_tables WHERE code=? AND is_active=1",
                (code,),
            )
            if row:
                table_code, table_id = row["code"], row["id"]
            else:
                table_error = "That table is not active tonight. Please pick your table below."

    data = {
        "venue": {
            "name": db.setting("venue_name", "Zaria Court Kigali"),
            "whatsapp_url": db.setting("whatsapp_url", config.WHATSAPP_URL),
            "currency": config.CURRENCY,
            "ordering_enabled": db.setting("ordering_enabled", "1") == "1",
            "notice": db.setting("venue_notice", ""),
            "service_mode": config.service_mode(),
        },
        "vendors": catalog.vendor_list(),
        "announcements": catalog.live_announcements(),
        "table": {"code": table_code, "id": table_id, "error": table_error},
        "tables": [dict(r) for r in db.q(
            "SELECT code,label,zone FROM venue_tables WHERE is_active=1 ORDER BY zone, code"
        )],
        "limits": {
            "max_qty": config.MAX_QTY_PER_LINE,
            "max_lines": config.MAX_ITEMS_PER_ORDER,
        },
    }

    resp = json_response(data)
    if not req.cookie(guards.GUEST_COOKIE):
        resp.cookie(
            guards.GUEST_COOKIE, secrets.token_urlsafe(18),
            max_age=int(config.GUEST_TTL.total_seconds()), same_site="Lax",
            secure=req.is_https,
        )
    return resp


_live_cache: dict = {"at": 0.0, "body": None}
_live_lock = threading.Lock()
LIVE_CACHE_SECONDS = 5


@router.route("GET", "/api/live")
def live(req: Request):
    """The parts of the home screen that change during an event.

    A guest can sit with the page open for an hour. Without this, a discount
    posted at 21:00 would only reach phones that loaded the page afterwards --
    which defeats the point of putting offers on the guest screen at all.
    Deliberately small: no tables, no menus, so it is cheap to poll.

    Every phone in the venue polls this, so the answer -- which is the same for
    all of them -- is built once every few seconds rather than once per request.
    At five hundred guests that is the difference between twenty database reads
    a second and one every five.
    """
    now = time.monotonic()
    with _live_lock:
        cached = _live_cache["body"]
        if cached is not None and now - _live_cache["at"] < LIVE_CACHE_SECONDS:
            return json_response(cached)

    body = {
        "venue": {
            "ordering_enabled": db.setting("ordering_enabled", "1") == "1",
            "notice": db.setting("venue_notice", ""),
            "service_mode": config.service_mode(),
        },
        "vendors": catalog.vendor_list(),
        "announcements": catalog.live_announcements(),
    }
    with _live_lock:
        _live_cache["body"] = body
        _live_cache["at"] = now
    return json_response(body)


@router.route("GET", "/api/menu/<slug>")
def menu(req: Request):
    row = db.q1(
        "SELECT id FROM vendors WHERE slug=? AND is_active=1", (req.params["slug"],)
    )
    if row is None:
        raise HttpError(404, "That kitchen is not on the menu.")
    return json_response(catalog.vendor_menu(row["id"]))


@router.route("POST", "/api/orders")
def create_order(req: Request):
    if db.setting("ordering_enabled", "1") != "1":
        raise HttpError(503, "Ordering is paused right now. Please order at the kiosk.")

    payload = req.json()
    mode = config.service_mode()
    token = security.clean_text(payload.get("table_token"), 80)
    manual = security.clean_text(payload.get("table_code"), 24).upper()

    table_code, table_id = "", None
    if mode != "PICKUP":
        verified = security.verify_table(token) if token else None
        if verified:
            table_code = verified
        elif manual:
            table_code = manual
        if table_code:
            row = db.q1(
                "SELECT id,code FROM venue_tables WHERE code=? AND is_active=1", (table_code,)
            )
            if row is None:
                raise HttpError(
                    400,
                    f"Table \"{table_code}\" is not in tonight's list. Please check the number on your table.",
                    "table_code",
                )
            table_code, table_id = row["code"], row["id"]

    # The phone number is optional. In hospitality, demanding a guest's number
    # to buy a plate reads as data collection; the table number (or the pickup
    # code) is what actually gets the food to the right person. We take a
    # number only from guests who volunteer one, and validate it if they do.
    raw_phone = security.clean_text(payload.get("phone"), 24)
    phone = security.normalise_phone(raw_phone)
    if raw_phone and not phone:
        raise HttpError(
            400,
            "That does not look like a Rwandan mobile number. Correct it, or leave it blank.",
            "phone",
        )
    if phone and security.is_blocked("phone", phone):
        raise HttpError(403, "Please place this order at the kiosk.")

    name = security.clean_text(payload.get("name"), 60)
    if len(name) < 2:
        raise HttpError(400, "Please give a name for the order.", "name")

    cart = payload.get("cart")
    if not isinstance(cart, list):
        raise HttpError(400, "Your basket could not be read. Please reload and try again.")

    result = orders.place_orders(
        cart=cart,
        table_code=table_code,
        table_id=table_id,
        name=name,
        phone=phone,
        note=payload.get("note", ""),
        device_hash=guards.guest_id(req),
        ip_hash=security.hash_ip(req.ip),
        # An address from the internet is a whole crowd behind NAT -- the venue's
        # Wi-Fi, or a mobile carrier's pool. A venue address is one phone.
        ip_is_shared=not req.on_venue_network,
    )
    _log_event(req, "order_placed", meta=str(len(result["orders"])), table_code=table_code)
    return json_response(result, 201)


@router.route("GET", "/api/orders/group/<group_key>")
def track_group(req: Request):
    rows = db.q(
        "SELECT id FROM orders WHERE group_key=? ORDER BY id", (req.params["group_key"],)
    )
    if not rows:
        raise HttpError(404, "We could not find that order.")
    return json_response({"orders": [orders.order_public(r["id"]) for r in rows]})


@router.route("GET", "/api/orders/<public_code>")
def track_one(req: Request):
    row = db.q1("SELECT id FROM orders WHERE public_code=?", (req.params["public_code"],))
    if row is None:
        raise HttpError(404, "We could not find that order.")
    return json_response(orders.order_public(row["id"]))


@router.route("POST", "/api/orders/<public_code>/cancel")
def cancel_own(req: Request):
    """A guest may withdraw an order only while it is still PENDING — once a
    kitchen has accepted it, food is already being made."""
    row = db.q1(
        "SELECT id,status,device_hash FROM orders WHERE public_code=?",
        (req.params["public_code"],),
    )
    if row is None:
        raise HttpError(404, "We could not find that order.")
    if row["device_hash"] != guards.guest_id(req):
        raise HttpError(403, "This order was placed on another phone.")
    if row["status"] != "PENDING":
        raise HttpError(409, "The kitchen has already started this order. Please speak to the runner.")
    orders.transition(row["id"], "CANCELLED", actor_type="guest", actor="",
                      note="Withdrawn by guest")
    return json_response({"ok": True})


# --- Analytics ---------------------------------------------------------------


def _log_event(req: Request, kind: str, vendor_id=None, meta="", table_code=""):
    visitor = guards.guest_id(req)
    # One row per visitor per kind per 10 minutes keeps the table honest and
    # stops a page refresh loop inflating the numbers the boss reads.
    bucket = f"ev:{kind}:{vendor_id or '-'}:{visitor}"
    if not security.rate_hit(bucket, 1, timedelta(minutes=10)):
        return
    db.ex(
        "INSERT INTO events(kind,vendor_id,table_code,visitor,meta,at) VALUES(?,?,?,?,?,?)",
        (kind, vendor_id, table_code, visitor, security.clean_text(meta, 120), config.now_iso()),
    )


@router.route("POST", "/api/track")
def track(req: Request):
    payload = req.json()
    kind = security.clean_text(payload.get("kind"), 30)
    if kind not in {"page_view", "vendor_view", "order_start"}:
        raise HttpError(400, "Unknown event.")
    vendor_id = security.clean_int(payload.get("vendor_id"), 1, 2**31, None)
    _log_event(req, kind, vendor_id=vendor_id,
               table_code=security.clean_text(payload.get("table_code"), 24))
    return json_response({"ok": True})


@router.route("GET", "/j/whatsapp")
def whatsapp(req: Request):
    """Counts the click, then forwards to WhatsApp.

    Worth being clear with the boss: WhatsApp gives us no way to confirm that a
    click became a join. This measures intent to join, which is the honest
    ceiling on what any link can tell you.
    """
    _log_event(req, "whatsapp_click")
    return redirect(db.setting("whatsapp_url", config.WHATSAPP_URL))
