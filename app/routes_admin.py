"""Admin API: revenue, traffic, WhatsApp click-through, vendors, tables, QR codes."""
from __future__ import annotations

import csv
import io
import re
from datetime import timedelta

from . import config, db, guards, orders, qr, security
from .web import HttpError, Request, Response, Router, json_response

router = Router()


# --- Auth --------------------------------------------------------------------


@router.route("POST", "/api/admin/login")
def login(req: Request):
    guards.require_staff_network(req)
    payload = req.json()
    username = security.clean_text(payload.get("username"), 40).lower()
    password = str(payload.get("password") or "")

    scope = f"a:{username}:{security.hash_ip(req.ip)[:12]}"
    if security.login_blocked(scope):
        raise HttpError(429, "Too many failed attempts. Try again in 15 minutes.")

    row = db.q1("SELECT * FROM admin_users WHERE username=? AND is_active=1", (username,))
    stored = row["pw_hash"] if row else security.hash_password("not-a-real-password")
    if not security.verify_password(password, stored) or row is None:
        security.record_login_failure(scope)
        raise HttpError(401, "Wrong username or password.")

    security.clear_login_failures(scope)
    token, csrf = security.create_session("admin", row["id"], req.ip)
    db.ex("UPDATE admin_users SET last_login=? WHERE id=?", (config.now_iso(), row["id"]))

    resp = json_response({
        "ok": True, "csrf": csrf,
        "user": {"display": row["display"] or row["username"],
                 "must_change": bool(row["must_change"])},
    })
    resp.cookie(guards.ADMIN_COOKIE, token, max_age=int(config.SESSION_TTL.total_seconds()),
                secure=req.is_https)
    return resp


@router.route("POST", "/api/admin/logout")
def logout(req: Request):
    security.destroy_session(req.cookie(guards.ADMIN_COOKIE))
    resp = json_response({"ok": True})
    resp.cookie(guards.ADMIN_COOKIE, "", max_age=0, secure=req.is_https)
    return resp


@router.route("GET", "/api/admin/me")
def me(req: Request):
    actor = guards.require_admin(req)
    return json_response({
        "csrf": actor.csrf,
        "user": {"display": actor.display, "must_change": actor.must_change},
    })


@router.route("POST", "/api/admin/password")
def change_password(req: Request):
    actor = guards.require_admin(req)
    payload = req.json()
    row = db.q1("SELECT pw_hash FROM admin_users WHERE id=?", (actor.user_id,))
    if not security.verify_password(str(payload.get("current") or ""), row["pw_hash"]):
        raise HttpError(403, "Your current password is not correct.")
    new = str(payload.get("new") or "")
    problem = security.password_problem(new)
    if problem:
        raise HttpError(400, problem, "new")
    db.ex("UPDATE admin_users SET pw_hash=?, must_change=0 WHERE id=?",
          (security.hash_password(new), actor.user_id))
    return json_response({"ok": True})


# --- Dashboard ---------------------------------------------------------------


def _range(req: Request) -> tuple[str, str, int]:
    days = security.clean_int(req.query.get("days"), 1, 365, 7)
    end = config.now()
    start = (config.to_kigali(end) - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"), days


@router.route("GET", "/api/admin/dashboard")
def dashboard(req: Request):
    guards.require_admin(req)
    since, until, days = _range(req)

    money = db.q1(
        "SELECT COUNT(*) AS orders,"
        " COALESCE(SUM(CASE WHEN status='PAID' THEN total_rwf ELSE 0 END),0) AS revenue,"
        " COALESCE(SUM(CASE WHEN status='PAID' THEN discount_rwf ELSE 0 END),0) AS discounts_given,"
        " COALESCE(SUM(CASE WHEN status IN ('PENDING','ACCEPTED','READY','DELIVERED')"
        "   THEN total_rwf ELSE 0 END),0) AS outstanding,"
        " SUM(CASE WHEN status='PAID' THEN 1 ELSE 0 END) AS paid_orders,"
        " SUM(CASE WHEN status='REJECTED' THEN 1 ELSE 0 END) AS rejected,"
        " SUM(CASE WHEN status='CANCELLED' THEN 1 ELSE 0 END) AS cancelled"
        " FROM orders WHERE placed_at >= ?",
        (since,),
    )
    m = dict(money)
    m["avg_order_rwf"] = int(m["revenue"] / m["paid_orders"]) if m["paid_orders"] else 0

    by_vendor = [dict(r) for r in db.q(
        "SELECT v.id, v.name, v.accent,"
        " COUNT(o.id) AS orders,"
        " COALESCE(SUM(CASE WHEN o.status='PAID' THEN o.total_rwf ELSE 0 END),0) AS revenue,"
        " SUM(CASE WHEN o.status='PAID' THEN 1 ELSE 0 END) AS paid_orders"
        " FROM vendors v LEFT JOIN orders o ON o.vendor_id=v.id AND o.placed_at >= ?"
        " WHERE v.is_active=1 GROUP BY v.id ORDER BY revenue DESC",
        (since,),
    )]

    by_day = [dict(r) for r in db.q(
        "SELECT substr(placed_at,1,10) AS day, COUNT(*) AS orders,"
        " COALESCE(SUM(CASE WHEN status='PAID' THEN total_rwf ELSE 0 END),0) AS revenue"
        " FROM orders WHERE placed_at >= ? GROUP BY day ORDER BY day",
        (since,),
    )]

    by_hour = [dict(r) for r in db.q(
        "SELECT substr(placed_at,12,2) AS hour, COUNT(*) AS orders"
        " FROM orders WHERE placed_at >= ? GROUP BY hour ORDER BY hour",
        (since,),
    )]

    top_items = [dict(r) for r in db.q(
        "SELECT oi.name_snapshot AS name, v.name AS vendor,"
        " SUM(oi.qty) AS qty, SUM(oi.line_total_rwf) AS revenue"
        " FROM order_items oi JOIN orders o ON o.id=oi.order_id"
        " JOIN vendors v ON v.id=o.vendor_id"
        " WHERE o.placed_at >= ? AND o.status='PAID'"
        " GROUP BY oi.name_snapshot, v.name ORDER BY qty DESC LIMIT 12",
        (since,),
    )]

    by_table = [dict(r) for r in db.q(
        "SELECT table_code, COUNT(*) AS orders,"
        " COALESCE(SUM(CASE WHEN status='PAID' THEN total_rwf ELSE 0 END),0) AS revenue"
        " FROM orders WHERE placed_at >= ? AND table_code<>''"
        " GROUP BY table_code ORDER BY revenue DESC LIMIT 15",
        (since,),
    )]

    payment_mix = [dict(r) for r in db.q(
        "SELECT COALESCE(NULLIF(payment_method,''),'UNSPECIFIED') AS method,"
        " COUNT(*) AS orders, COALESCE(SUM(total_rwf),0) AS revenue"
        " FROM orders WHERE placed_at >= ? AND status='PAID' GROUP BY method",
        (since,),
    )]

    traffic = {
        "visitors": db.scalar(
            "SELECT COUNT(DISTINCT visitor) FROM events WHERE at >= ?", (since,)),
        "page_views": db.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='page_view' AND at >= ?", (since,)),
        "menu_opens": db.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='vendor_view' AND at >= ?", (since,)),
        "checkout_starts": db.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='order_start' AND at >= ?", (since,)),
        "whatsapp_clicks": db.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='whatsapp_click' AND at >= ?", (since,)),
        "whatsapp_unique": db.scalar(
            "SELECT COUNT(DISTINCT visitor) FROM events WHERE kind='whatsapp_click' AND at >= ?",
            (since,)),
    }
    traffic["whatsapp_all_time"] = db.scalar(
        "SELECT COUNT(DISTINCT visitor) FROM events WHERE kind='whatsapp_click'")
    visitors = traffic["visitors"] or 0
    traffic["order_conversion"] = round(100.0 * m["paid_orders"] / visitors, 1) if visitors else 0.0
    traffic["whatsapp_conversion"] = (
        round(100.0 * traffic["whatsapp_unique"] / visitors, 1) if visitors else 0.0
    )

    prep = db.q1(
        "SELECT AVG(julianday(accepted_at)-julianday(placed_at))*1440 AS accept_min,"
        " AVG(julianday(ready_at)-julianday(accepted_at))*1440 AS cook_min"
        " FROM orders WHERE placed_at >= ? AND ready_at IS NOT NULL",
        (since,),
    )

    return json_response({
        "range": {"days": days, "since": since, "until": until},
        "money": m,
        "by_vendor": by_vendor,
        "by_day": by_day,
        "by_hour": by_hour,
        "top_items": top_items,
        "by_table": by_table,
        "payment_mix": payment_mix,
        "traffic": traffic,
        "timing": {
            "accept_minutes": round(prep["accept_min"] or 0, 1),
            "cook_minutes": round(prep["cook_min"] or 0, 1),
        },
    })


@router.route("GET", "/api/admin/orders")
def admin_orders(req: Request):
    guards.require_admin(req)
    status = security.clean_text(req.query.get("status"), 20).upper()
    limit = security.clean_int(req.query.get("limit"), 1, 500, 100)
    sql = "SELECT id FROM orders"
    args: list = []
    if status and status in orders.TRANSITIONS:
        sql += " WHERE status=?"
        args.append(status)
    sql += " ORDER BY placed_at DESC LIMIT ?"
    args.append(limit)
    return json_response({"orders": [orders.order_for_staff(r["id"]) for r in db.q(sql, args)]})


@router.route("POST", "/api/admin/orders/<oid>/status")
def admin_set_status(req: Request):
    actor = guards.require_admin(req)
    oid = security.clean_int(req.params["oid"], 1, 2**31)
    payload = req.json()
    return json_response(orders.transition(
        oid, security.clean_text(payload.get("status"), 20),
        actor_type="admin", actor=actor.username,
        payment_method=security.clean_text(payload.get("payment_method"), 12),
        note=payload.get("note", ""),
    ))


@router.route("GET", "/api/admin/export.csv")
def export_csv(req: Request):
    guards.require_admin(req)
    since, _, _ = _range(req)
    rows = db.q(
        "SELECT o.placed_at, o.short_code, v.name AS vendor, o.table_code, o.status,"
        " o.subtotal_rwf, o.discount_rwf, o.total_rwf, o.payment_method, o.paid_at"
        " FROM orders o JOIN vendors v ON v.id=o.vendor_id"
        " WHERE o.placed_at >= ? ORDER BY o.placed_at",
        (since,),
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Placed (UTC)", "Code", "Vendor", "Table", "Status",
                "Subtotal RWF", "Discount RWF", "Total RWF", "Payment", "Paid at"])
    for r in rows:
        w.writerow([r[k] for k in r.keys()])
    return Response(
        200, buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8",
        headers=[("Content-Disposition", 'attachment; filename="zaria-orders.csv"')],
    )


# --- Vendors and staff -------------------------------------------------------


@router.route("GET", "/api/admin/vendors")
def list_vendors(req: Request):
    guards.require_admin(req)
    rows = db.q("SELECT * FROM vendors ORDER BY sort, id")
    out = []
    for r in rows:
        d = dict(r)
        d["users"] = [dict(u) for u in db.q(
            "SELECT id,username,display,is_active,last_login,must_change"
            " FROM vendor_users WHERE vendor_id=?", (r["id"],)
        )]
        out.append(d)
    return json_response({"vendors": out})


@router.route("PATCH", "/api/admin/vendors/<vid>")
def update_vendor(req: Request):
    guards.require_admin(req)
    vid = security.clean_int(req.params["vid"], 1, 2**31)
    payload = req.json()
    allowed = {
        "name": lambda v: security.clean_text(v, 60),
        "kind": lambda v: security.clean_text(v, 60),
        "tagline": lambda v: security.clean_text(v, 160),
        "accent": lambda v: security.clean_text(v, 12),
        "momo_code": lambda v: security.clean_text(v, 24),
        "phone": lambda v: security.clean_text(v, 24),
        "accepts_orders": lambda v: 1 if v else 0,
        "is_open": lambda v: 1 if v else 0,
        "is_active": lambda v: 1 if v else 0,
        "sort": lambda v: security.clean_int(v, 0, 10000, 0),
    }
    sets, vals = [], []
    for key, fn in allowed.items():
        if key in payload:
            sets.append(f"{key}=?")
            vals.append(fn(payload[key]))
    if not sets:
        raise HttpError(400, "Nothing to update.")
    vals.append(vid)
    cur = db.ex(f"UPDATE vendors SET {', '.join(sets)} WHERE id=?", vals)
    if not cur.rowcount:
        raise HttpError(404, "Vendor not found.")
    return json_response({"ok": True})


@router.route("POST", "/api/admin/vendor-users")
def create_vendor_user(req: Request):
    guards.require_admin(req)
    payload = req.json()
    vendor_id = security.clean_int(payload.get("vendor_id"), 1, 2**31, None)
    if vendor_id is None or not db.q1("SELECT 1 FROM vendors WHERE id=?", (vendor_id,)):
        raise HttpError(400, "Pick a vendor.", "vendor_id")
    username = security.clean_text(payload.get("username"), 40).lower()
    if len(username) < 3 or not username.replace("-", "").replace("_", "").isalnum():
        raise HttpError(400, "Username must be at least 3 letters or digits.", "username")
    if db.q1("SELECT 1 FROM vendor_users WHERE username=?", (username,)):
        raise HttpError(409, "That username is taken.", "username")

    # A one-time password is generated here and shown exactly once. The vendor
    # is forced to change it at first sign-in.
    temp = security.public_code()[:12]
    db.ex(
        "INSERT INTO vendor_users(vendor_id,username,pw_hash,display,is_active,"
        "must_change,created_at) VALUES(?,?,?,?,1,1,?)",
        (vendor_id, username, security.hash_password(temp),
         security.clean_text(payload.get("display"), 60), config.now_iso()),
    )
    return json_response({"username": username, "temp_password": temp}, 201)


@router.route("POST", "/api/admin/vendor-users/<uid>/reset")
def reset_vendor_user(req: Request):
    guards.require_admin(req)
    uid = security.clean_int(req.params["uid"], 1, 2**31)
    temp = security.public_code()[:12]
    cur = db.ex(
        "UPDATE vendor_users SET pw_hash=?, must_change=1 WHERE id=?",
        (security.hash_password(temp), uid),
    )
    if not cur.rowcount:
        raise HttpError(404, "User not found.")
    db.ex("DELETE FROM sessions WHERE kind='vendor' AND user_id=?", (uid,))
    return json_response({"temp_password": temp})


@router.route("PATCH", "/api/admin/vendor-users/<uid>")
def toggle_vendor_user(req: Request):
    guards.require_admin(req)
    uid = security.clean_int(req.params["uid"], 1, 2**31)
    active = 1 if req.json().get("is_active") else 0
    cur = db.ex("UPDATE vendor_users SET is_active=? WHERE id=?", (active, uid))
    if not cur.rowcount:
        raise HttpError(404, "User not found.")
    if not active:
        db.ex("DELETE FROM sessions WHERE kind='vendor' AND user_id=?", (uid,))
    return json_response({"ok": True})


# --- Tables and QR codes -----------------------------------------------------


@router.route("GET", "/api/admin/tables")
def list_tables(req: Request):
    guards.require_admin(req)
    rows = db.q("SELECT * FROM venue_tables ORDER BY zone, code")
    return json_response({"tables": [
        {**dict(r), "token": security.sign_table(r["code"])} for r in rows
    ]})


def _parse_codes(raw: str) -> list[str]:
    """'A1-A20, VIP1, VIP2' -> ['A1', ..., 'A20', 'VIP1', 'VIP2'].

    Table layouts change from one event to the next, so this has to survive
    being typed quickly on the day. Ranges only expand when both ends share a
    prefix; anything else is taken literally.
    """
    codes: list[str] = []
    for chunk in raw.replace(";", ",").replace("\n", ",").split(","):
        chunk = chunk.strip().upper()
        if not chunk:
            continue
        if "-" in chunk:
            lo, _, hi = chunk.partition("-")
            m1 = re.match(r"^([A-Z]*)(\d+)$", lo.strip())
            m2 = re.match(r"^([A-Z]*)(\d+)$", hi.strip())
            if m1 and m2 and m1.group(1) == m2.group(1):
                a, b = int(m1.group(2)), int(m2.group(2))
                if 0 <= a <= b and b - a < 500:
                    codes.extend(f"{m1.group(1)}{i}" for i in range(a, b + 1))
                    continue
        codes.append(chunk)
    return [c for c in dict.fromkeys(codes) if 1 <= len(c) <= 12][:500]


@router.route("POST", "/api/admin/tables")
def create_tables(req: Request):
    """Accepts a single code or a range spec like 'A1-A20' for fast setup."""
    guards.require_admin(req)
    payload = req.json()
    zone = security.clean_text(payload.get("zone"), 40)
    raw = security.clean_text(payload.get("codes"), 4000)
    if not raw:
        raise HttpError(400, "Enter one or more table codes.", "codes")

    codes = _parse_codes(raw)
    if not codes:
        raise HttpError(400, "Could not read those table codes.", "codes")

    added = 0
    with db.tx():
        for c in codes:
            try:
                db.ex(
                    "INSERT INTO venue_tables(code,label,zone,is_active,created_at)"
                    " VALUES(?,?,?,1,?)",
                    (c, c, zone, config.now_iso()),
                )
                added += 1
            except Exception:
                pass  # already exists
    return json_response({"added": added, "total": len(codes)}, 201)


@router.route("PUT", "/api/admin/tables")
def replace_tables(req: Request):
    """Wipe the table list and set it to exactly what was typed.

    This is the between-events reset: the floor plan for a concert has nothing
    to do with last week's. Past orders keep their table_code as plain text, so
    clearing the list never rewrites history — `orders.table_id` is declared
    ON DELETE SET NULL and the printed code stays on the ticket.
    """
    guards.require_admin(req)
    payload = req.json()
    zone = security.clean_text(payload.get("zone"), 40)
    raw = security.clean_text(payload.get("codes"), 4000)
    codes = _parse_codes(raw) if raw else []

    if not payload.get("confirm"):
        raise HttpError(400, "Confirm before replacing the table list.", "confirm")

    with db.tx():
        db.ex("DELETE FROM venue_tables")
        for c in codes:
            db.ex(
                "INSERT INTO venue_tables(code,label,zone,is_active,created_at)"
                " VALUES(?,?,?,1,?)",
                (c, c, zone, config.now_iso()),
            )
    return json_response({"total": len(codes)})


@router.route("DELETE", "/api/admin/tables/<tid>")
def delete_table(req: Request):
    guards.require_admin(req)
    tid = security.clean_int(req.params["tid"], 1, 2**31)
    cur = db.ex("DELETE FROM venue_tables WHERE id=?", (tid,))
    if not cur.rowcount:
        raise HttpError(404, "Table not found.")
    return json_response({"ok": True})


@router.route("PATCH", "/api/admin/tables/<tid>")
def update_table(req: Request):
    guards.require_admin(req)
    tid = security.clean_int(req.params["tid"], 1, 2**31)
    payload = req.json()
    sets, vals = [], []
    if "is_active" in payload:
        sets.append("is_active=?"); vals.append(1 if payload.get("is_active") else 0)
    if "zone" in payload:
        sets.append("zone=?"); vals.append(security.clean_text(payload.get("zone"), 40))
    if not sets:
        raise HttpError(400, "Nothing to update.")
    vals.append(tid)
    cur = db.ex(f"UPDATE venue_tables SET {', '.join(sets)} WHERE id=?", vals)
    if not cur.rowcount:
        raise HttpError(404, "Table not found.")
    return json_response({"ok": True})


def _wifi_payload(ssid: str, password: str, security_type: str) -> str:
    """The WIFI: URI both iOS and Android understand from the camera app.

    Guests are split between the venue Wi-Fi and their own data bundles, and a
    LAN-only server is unreachable from a data bundle. Putting a join-the-Wi-Fi
    code next to the menu code turns that from an explanation the door staff
    have to give into one scan.
    """
    def esc(value: str) -> str:
        for ch in ("\\", ";", ",", ":", '"'):
            value = value.replace(ch, "\\" + ch)
        return value

    if security_type == "nopass":
        return f"WIFI:T:nopass;S:{esc(ssid)};;"
    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(password)};;"


@router.route("GET", "/api/admin/qr/wifi")
def wifi_qr(req: Request):
    """SVG QR that joins the venue Wi-Fi when scanned."""
    guards.require_admin(req)
    ssid = db.setting("wifi_ssid", "")
    if not ssid:
        raise HttpError(404, "Set the Wi-Fi network name in Settings first.")
    password = db.setting("wifi_password", "")
    kind = "nopass" if (db.setting("wifi_security", "WPA") == "nopass" or not password) else "WPA"
    payload = _wifi_payload(ssid, password, kind)
    return Response(200, qr.svg(payload, scale=8).encode("utf-8"), "image/svg+xml")


@router.route("GET", "/api/admin/qr")
def table_qr(req: Request):
    """SVG QR for one table, sized for a printed tent card."""
    guards.require_admin(req)
    code = security.clean_text(req.query.get("code"), 12).upper()
    row = db.q1("SELECT code FROM venue_tables WHERE code=?", (code,))
    if row is None:
        raise HttpError(404, "Table not found.")
    base = db.setting("public_base_url", "").rstrip("/")
    if not base:
        base = f"http://{req.headers.get('Host', 'localhost:8080')}"
    url = f"{base}/?t={security.sign_table(row['code'])}"
    return Response(200, qr.svg(url, scale=8).encode("utf-8"), "image/svg+xml")


# --- Announcements (venue-wide) ---------------------------------------------


AUDIENCES = ("GUESTS", "VENDORS")


@router.route("POST", "/api/admin/announcements")
def create_global_announcement(req: Request):
    """A message to every guest's screen, or a briefing to the kitchens.

    The kitchens' one is how you ask for something to happen -- "concert
    tonight, run your offers" -- rather than announcing it yourself. Each
    kitchen then posts its own offer, which is the part guests see.
    """
    actor = guards.require_admin(req)
    payload = req.json()
    audience = security.clean_text(payload.get("audience"), 10).upper() or "GUESTS"
    if audience not in AUDIENCES:
        raise HttpError(400, "Choose who should see this.", "audience")

    body = security.clean_text(payload.get("body"), 300 if audience == "VENDORS" else 160)
    if len(body) < 3:
        raise HttpError(
            400,
            "Write the message the kitchens should see." if audience == "VENDORS"
            else "Write the message guests should see.",
            "body",
        )
    kind = security.clean_text(payload.get("kind"), 12).upper() or "EVENT"
    cur = db.ex(
        "INSERT INTO announcements(vendor_id,audience,kind,body,starts_at,ends_at,"
        "priority,is_active,created_at,created_by) VALUES(NULL,?,?,?,?,?,?,1,?,?)",
        (audience, kind, body,
         security.clean_text(payload.get("starts_at"), 40) or None,
         security.clean_text(payload.get("ends_at"), 40) or None,
         security.clean_int(payload.get("priority"), 0, 100, 50),
         config.now_iso(), actor.username),
    )
    return json_response({"id": cur.lastrowid, "audience": audience}, 201)


@router.route("GET", "/api/admin/announcements")
def list_all_announcements(req: Request):
    guards.require_admin(req)
    rows = db.q(
        "SELECT a.*, v.name AS vendor_name FROM announcements a"
        " LEFT JOIN vendors v ON v.id=a.vendor_id"
        " ORDER BY a.is_active DESC, a.id DESC LIMIT 200"
    )
    return json_response({"announcements": [dict(r) for r in rows]})


@router.route("PATCH", "/api/admin/announcements/<aid>")
def admin_toggle_announcement(req: Request):
    guards.require_admin(req)
    aid = security.clean_int(req.params["aid"], 1, 2**31)
    cur = db.ex(
        "UPDATE announcements SET is_active=? WHERE id=?",
        (1 if req.json().get("is_active") else 0, aid),
    )
    if not cur.rowcount:
        raise HttpError(404, "Announcement not found.")
    return json_response({"ok": True})


# --- Settings and moderation -------------------------------------------------


EDITABLE_SETTINGS = {
    "venue_name", "whatsapp_url", "venue_notice", "ordering_enabled", "public_base_url",
    "service_mode", "wifi_ssid", "wifi_password", "wifi_security", "staff_network",
    "orders_per_shared_ip_hour", "orders_per_device_hour",
}

# Settings that hold a number, with the range that is sane for each.
NUMERIC_SETTINGS = {
    "orders_per_shared_ip_hour": (10, 100_000),
    "orders_per_device_hour": (1, 500),
}

# Settings that may only hold one of a fixed set of values. Free text here would
# silently disable the table requirement, so the whitelist is enforced on write.
SETTING_CHOICES = {
    "service_mode": config.SERVICE_MODES,
    "wifi_security": ("WPA", "nopass"),
    "staff_network": ("ANY", "LAN_ONLY"),
}


@router.route("GET", "/api/admin/settings")
def get_settings(req: Request):
    guards.require_admin(req)
    return json_response({
        "settings": {k: db.setting(k, "") for k in sorted(EDITABLE_SETTINGS)},
        "service_mode": config.service_mode(),
        "service_modes": list(config.SERVICE_MODES),
        "staff_network": db.setting("staff_network", "ANY"),
        "on_venue_network": req.on_venue_network,
        "retention_days": config.PII_RETENTION_DAYS,
        "limits": {
            "open_orders_per_table": config.MAX_OPEN_ORDERS_PER_TABLE,
            "orders_per_device_hour": config.orders_per_device_hour(),
            "orders_per_lan_ip_hour": config.MAX_ORDERS_PER_LAN_IP_HOUR,
            "orders_per_shared_ip_hour": config.orders_per_shared_ip_hour(),
        },
    })


@router.route("POST", "/api/admin/settings")
def put_settings(req: Request):
    guards.require_admin(req)
    payload = req.json()
    changed = []
    for key, value in payload.items():
        if key not in EDITABLE_SETTINGS:
            continue

        if key in NUMERIC_SETTINGS:
            low, high = NUMERIC_SETTINGS[key]
            try:
                n = int(str(value).strip())
            except (TypeError, ValueError):
                raise HttpError(400, "Enter a whole number.", key)
            if not low <= n <= high:
                raise HttpError(400, f"Choose a number between {low} and {high}.", key)
            db.set_setting(key, str(n))
            changed.append(key)
            continue

        if key == "wifi_password":
            # A Wi-Fi key is matched byte for byte by the phone, so the usual
            # whitespace collapsing would silently break a password that
            # legitimately contains spaces. Strip control characters only.
            clean = security.clean_password_like(value, 63)
        else:
            clean = security.clean_text(value, 300)

        choices = SETTING_CHOICES.get(key)
        if choices is not None:
            match = next((c for c in choices if c.lower() == clean.lower()), None)
            if match is None:
                raise HttpError(400, f"\"{clean}\" is not a valid {key.replace('_', ' ')}.", key)
            clean = match

        # Turning this on from the public address would lock the admin out with
        # the very next request. Requiring it to be switched on from inside the
        # venue proves the way back in still works.
        if key == "staff_network" and clean == "LAN_ONLY" and not req.on_venue_network:
            raise HttpError(
                400,
                "Switch this on while you are on Zaria Wi-Fi, using the venue address. "
                "Doing it from the public address would lock you out immediately.",
                key,
            )

        db.set_setting(key, clean)
        changed.append(key)
    if not changed:
        raise HttpError(400, "Nothing to update.")
    return json_response({"ok": True, "changed": changed})


@router.route("GET", "/api/admin/blocklist")
def get_blocklist(req: Request):
    guards.require_admin(req)
    return json_response({"entries": [dict(r) for r in db.q(
        "SELECT id,kind,value,reason,created_at FROM blocklist ORDER BY id DESC LIMIT 200"
    )]})


@router.route("POST", "/api/admin/blocklist")
def add_block(req: Request):
    """Block the device behind a specific order — the practical response when
    one phone is spamming the kitchen mid-event."""
    guards.require_admin(req)
    payload = req.json()
    order_code = security.clean_text(payload.get("order_code"), 40)
    kind = security.clean_text(payload.get("kind"), 10) or "device"
    value = ""

    if order_code:
        row = db.q1(
            "SELECT device_hash, ip_hash, customer_phone FROM orders WHERE short_code=?"
            " OR public_code=? ORDER BY id DESC LIMIT 1", (order_code.upper(), order_code)
        )
        if row is None:
            raise HttpError(404, "No order with that code.")
        value = {"device": row["device_hash"], "ip": row["ip_hash"],
                 "phone": row["customer_phone"]}.get(kind, "")
    else:
        value = security.clean_text(payload.get("value"), 80)
        if kind == "phone":
            value = security.normalise_phone(value)

    if not value:
        raise HttpError(400, "Nothing to block.")
    try:
        db.ex(
            "INSERT INTO blocklist(kind,value,reason,created_at) VALUES(?,?,?,?)",
            (kind, value, security.clean_text(payload.get("reason"), 120), config.now_iso()),
        )
    except Exception:
        raise HttpError(409, "Already blocked.")
    return json_response({"ok": True}, 201)


@router.route("POST", "/api/admin/kiosks")
def register_kiosk(req: Request):
    """Register the machine this request came from as a kiosk.

    Done from the kiosk itself, which is the only way to identify it without
    asking anyone to read a hash off a screen: whoever is setting it up opens
    admin on that machine and presses the button.
    """
    guards.require_admin(req)
    label = security.clean_text(req.json().get("label"), 60) or "Kiosk"
    ip_hash = security.hash_ip(req.ip)
    if not req.on_venue_network:
        raise HttpError(
            400,
            "Register the kiosk from the kiosk itself, on the venue network. "
            "From the public address every guest would share its exemption.",
        )
    try:
        db.ex(
            "INSERT INTO blocklist(kind,value,reason,created_at) VALUES('kiosk_ip',?,?,?)",
            (ip_hash, label, config.now_iso()),
        )
    except Exception:
        raise HttpError(409, "This machine is already registered as a kiosk.")
    return json_response({"ok": True, "label": label}, 201)


@router.route("GET", "/api/admin/kiosks")
def list_kiosks(req: Request):
    guards.require_admin(req)
    rows = db.q(
        "SELECT id,value,reason AS label,created_at FROM blocklist"
        " WHERE kind IN ('kiosk_ip','kiosk_device') ORDER BY id DESC"
    )
    return json_response({
        "kiosks": [{"id": r["id"], "label": r["label"], "created_at": r["created_at"]}
                   for r in rows],
        "this_machine_registered": security.is_blocked("kiosk_ip", security.hash_ip(req.ip)),
        "on_venue_network": req.on_venue_network,
    })


@router.route("DELETE", "/api/admin/blocklist/<bid>")
def remove_block(req: Request):
    guards.require_admin(req)
    bid = security.clean_int(req.params["bid"], 1, 2**31)
    cur = db.ex("DELETE FROM blocklist WHERE id=?", (bid,))
    if not cur.rowcount:
        raise HttpError(404, "Entry not found.")
    return json_response({"ok": True})


@router.route("POST", "/api/admin/purge-pii")
def purge_pii(req: Request):
    guards.require_admin(req)
    return json_response({"purged": orders.purge_old_pii()})
