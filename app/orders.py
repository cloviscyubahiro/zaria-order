"""Checkout and the order lifecycle.

Lifecycle
    PENDING ──accept──> ACCEPTED ──ready──> READY ──deliver──> DELIVERED ──pay──> PAID
       │                    │                 │                   │
       └── reject ──> REJECTED                └───── cancel ──> CANCELLED

Nothing is cooked until a human at the vendor taps Accept. That single step is
the real defence against fake orders in a pay-on-delivery model — far more so
than any rate limit, because it puts a person between a submitted order and a
committed one.
"""
from __future__ import annotations

from datetime import timedelta

from . import config, db, security
from .catalog import active_discounts, discount_percent_for, discounted_price
from .web import HttpError

OPEN_STATUSES = ("PENDING", "ACCEPTED", "READY")
FINAL_STATUSES = ("PAID", "REJECTED", "CANCELLED")

TRANSITIONS = {
    "PENDING":   {"ACCEPTED", "REJECTED", "CANCELLED"},
    "ACCEPTED":  {"READY", "DELIVERED", "CANCELLED"},
    "READY":     {"DELIVERED", "CANCELLED"},
    "DELIVERED": {"PAID"},
    "PAID":      set(),
    "REJECTED":  set(),
    "CANCELLED": set(),
}

STAMP = {
    "ACCEPTED": "accepted_at",
    "READY": "ready_at",
    "DELIVERED": "delivered_at",
    "PAID": "paid_at",
}

PAYMENT_METHODS = {"CASH", "MOMO", "CARD", "OTHER"}


def _guard_rate_limits(device_hash: str, ip_hash: str, table_code: str,
                       ip_is_shared: bool) -> None:
    if security.is_blocked("device", device_hash):
        raise HttpError(403, "Ordering from this device has been disabled. Please order at the kiosk.")
    if security.is_blocked("ip", ip_hash):
        raise HttpError(403, "Ordering from this connection has been disabled. Please order at the kiosk.")

    # A registered kiosk orders for many guests by design, so the per-guest
    # budgets do not apply to it. Blocks still do -- checked above.
    if security.is_exempt(device_hash, ip_hash):
        return

    # The per-device cap is the one that actually stops a prankster: it is a
    # count of one browser, whatever network it is on.
    if not security.rate_hit(f"dev:{device_hash}", config.orders_per_device_hour(), timedelta(hours=1)):
        raise HttpError(429, "That is a lot of orders in one hour. Please finish at the kiosk.")

    # The per-address cap is a flood backstop, and an address arriving from the
    # internet stands for a crowd, not a person -- see config for why.
    ip_cap = config.orders_per_shared_ip_hour() if ip_is_shared \
        else config.MAX_ORDERS_PER_LAN_IP_HOUR
    if not security.rate_hit(f"ip:{ip_hash}", ip_cap, timedelta(hours=1)):
        raise HttpError(429, "Too many orders from this network right now. Please try again shortly.")

    if table_code:
        open_now = db.scalar(
            "SELECT COUNT(*) FROM orders WHERE table_code=? AND status IN (?,?,?)",
            (table_code, *OPEN_STATUSES),
        )
        if open_now >= config.MAX_OPEN_ORDERS_PER_TABLE:
            raise HttpError(
                429,
                f"Table {table_code} already has {open_now} orders in progress. "
                "Please wait for one to arrive before ordering again.",
            )


def _price_lines(vendor_id: int, lines: list[dict]) -> tuple[list[dict], int, int]:
    """Re-price every line from the database. Returns (priced, subtotal, discount)."""
    discounts = active_discounts(vendor_id)
    priced, subtotal, discount_total = [], 0, 0

    for raw in lines:
        item_id = security.clean_int(raw.get("item_id"), 1, 2**31, None)
        qty = security.clean_int(raw.get("qty"), 1, config.MAX_QTY_PER_LINE, None)
        if item_id is None:
            raise HttpError(400, "An item in your basket is not valid.")
        if qty is None:
            raise HttpError(400, f"Quantity must be between 1 and {config.MAX_QTY_PER_LINE}.")

        row = db.q1(
            "SELECT * FROM items WHERE id=? AND vendor_id=? AND is_active=1",
            (item_id, vendor_id),
        )
        if row is None:
            raise HttpError(409, "An item in your basket is no longer on the menu. Please refresh.")
        if not row["is_available"]:
            raise HttpError(409, f"\"{row['name']}\" has just sold out. Please remove it and try again.")

        item = dict(row)
        pct, _ = discount_percent_for(item, discounts)
        unit_gross = item["price_rwf"]
        unit_net = discounted_price(unit_gross, pct)

        line_gross = unit_gross * qty
        line_net = unit_net * qty
        subtotal += line_gross
        discount_total += line_gross - line_net

        priced.append({
            "item_id": item["id"],
            "name": item["name"],
            "unit_price_rwf": unit_net,
            "qty": qty,
            "line_total_rwf": line_net,
            "discount_rwf": line_gross - line_net,
        })

    return priced, subtotal, discount_total


def place_orders(*, cart: list[dict], table_code: str, table_id: int | None,
                 name: str, phone: str, note: str,
                 device_hash: str, ip_hash: str, ip_is_shared: bool = False) -> dict:
    """Turn a basket into one order per vendor, sharing a group key.

    Each vendor cooks and is paid separately, so each gets its own ticket; the
    group key lets a runner see that four tickets belong to one guest.
    """
    if not cart:
        raise HttpError(400, "Your basket is empty.")

    total_lines = sum(len(v.get("lines") or []) for v in cart)
    if total_lines == 0:
        raise HttpError(400, "Your basket is empty.")
    if total_lines > config.MAX_ITEMS_PER_ORDER:
        raise HttpError(400, f"An order can hold at most {config.MAX_ITEMS_PER_ORDER} lines.")

    _guard_rate_limits(device_hash, ip_hash, table_code, ip_is_shared)

    name = security.clean_text(name, 60)
    note = security.clean_multiline(note, 400)
    if not table_code and config.service_mode() == "TABLE":
        raise HttpError(
            400,
            "We need your table number before we can send this to the kitchen.",
            "table_code",
        )

    group_key = security.public_code()
    created = []

    with db.tx():
        for entry in cart:
            vendor_id = security.clean_int(entry.get("vendor_id"), 1, 2**31, None)
            lines = entry.get("lines") or []
            if vendor_id is None or not lines:
                continue

            vendor = db.q1(
                "SELECT * FROM vendors WHERE id=? AND is_active=1", (vendor_id,)
            )
            if vendor is None:
                raise HttpError(409, "One of the kitchens is no longer available.")
            if not vendor["accepts_orders"]:
                raise HttpError(409, f"{vendor['name']} is not taking orders through the app right now.")
            if not vendor["is_open"]:
                raise HttpError(409, f"{vendor['name']} is closed at the moment.")

            priced, subtotal, discount = _price_lines(vendor_id, lines)
            total = subtotal - discount
            if total > config.MAX_ORDER_VALUE_RWF:
                raise HttpError(400, "That order is unusually large. Please place it at the kiosk.")

            code = security.public_code()
            cur = db.ex(
                "INSERT INTO orders(public_code,short_code,group_key,vendor_id,table_id,"
                "table_code,customer_name,customer_phone,note,status,subtotal_rwf,"
                "discount_rwf,total_rwf,device_hash,ip_hash,placed_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,'PENDING',?,?,?,?,?,?,?)",
                (code, security.short_code(), group_key, vendor_id, table_id, table_code,
                 name, phone, note, subtotal, discount, total,
                 device_hash, ip_hash, config.now_iso(), config.now_iso()),
            )
            order_id = cur.lastrowid

            for p in priced:
                db.ex(
                    "INSERT INTO order_items(order_id,item_id,name_snapshot,"
                    "unit_price_rwf,qty,line_total_rwf,discount_rwf)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (order_id, p["item_id"], p["name"], p["unit_price_rwf"],
                     p["qty"], p["line_total_rwf"], p["discount_rwf"]),
                )

            db.ex(
                "INSERT INTO order_events(order_id,from_status,to_status,actor_type,actor,at)"
                " VALUES(?,'','PENDING','guest','',?)",
                (order_id, config.now_iso()),
            )
            created.append(order_id)

    return {
        "group_key": group_key,
        "orders": [order_public(oid) for oid in created],
    }


def order_public(order_id: int) -> dict:
    row = db.q1(
        "SELECT o.*, v.name AS vendor_name, v.slug AS vendor_slug, v.accent AS vendor_accent,"
        " v.momo_code, v.phone AS vendor_phone"
        " FROM orders o JOIN vendors v ON v.id=o.vendor_id WHERE o.id=?",
        (order_id,),
    )
    if not row:
        raise HttpError(404, "Order not found.")
    d = dict(row)
    for k in ("device_hash", "ip_hash", "customer_phone", "pii_purged"):
        d.pop(k, None)
    d["items"] = [dict(r) for r in db.q(
        "SELECT name_snapshot,unit_price_rwf,qty,line_total_rwf,discount_rwf"
        " FROM order_items WHERE order_id=? ORDER BY id", (order_id,)
    )]
    return d


def order_for_staff(order_id: int) -> dict:
    row = db.q1(
        "SELECT o.*, v.name AS vendor_name, v.accent AS vendor_accent"
        " FROM orders o JOIN vendors v ON v.id=o.vendor_id WHERE o.id=?",
        (order_id,),
    )
    if not row:
        raise HttpError(404, "Order not found.")
    d = dict(row)
    d.pop("device_hash", None)
    d.pop("ip_hash", None)
    d["items"] = [dict(r) for r in db.q(
        "SELECT name_snapshot,unit_price_rwf,qty,line_total_rwf,discount_rwf"
        " FROM order_items WHERE order_id=? ORDER BY id", (order_id,)
    )]
    d["events"] = [dict(r) for r in db.q(
        "SELECT from_status,to_status,actor_type,actor,note,at"
        " FROM order_events WHERE order_id=? ORDER BY at, id", (order_id,)
    )]
    return d


def transition(order_id: int, to_status: str, *, actor_type: str, actor: str,
               vendor_id: int | None = None, payment_method: str = "",
               note: str = "") -> dict:
    """Move one order along the lifecycle.

    `vendor_id`, when given, is applied inside the UPDATE's WHERE clause rather
    than checked beforehand — so a vendor cannot touch another vendor's ticket
    even if two requests race.
    """
    to_status = (to_status or "").upper()
    if to_status not in TRANSITIONS:
        raise HttpError(400, "Unknown status.")

    with db.tx():
        sql = "SELECT * FROM orders WHERE id=?"
        args: list = [order_id]
        if vendor_id is not None:
            sql += " AND vendor_id=?"
            args.append(vendor_id)
        row = db.q1(sql, args)
        if row is None:
            raise HttpError(404, "Order not found.")

        current = row["status"]
        if to_status == current:
            return order_for_staff(order_id)
        if to_status not in TRANSITIONS[current]:
            raise HttpError(
                409,
                f"An order that is {current.lower()} cannot be marked {to_status.lower()}.",
            )

        sets = ["status=?", "updated_at=?"]
        vals: list = [to_status, config.now_iso()]

        stamp = STAMP.get(to_status)
        if stamp:
            sets.append(f"{stamp}=?")
            vals.append(config.now_iso())

        if to_status == "PAID":
            method = (payment_method or "CASH").upper()
            if method not in PAYMENT_METHODS:
                raise HttpError(400, "Unknown payment method.")
            sets.append("payment_method=?")
            vals.append(method)

        if to_status in FINAL_STATUSES:
            sets.append("closed_at=?")
            vals.append(config.now_iso())

        if to_status in ("REJECTED", "CANCELLED"):
            sets.append("cancel_reason=?")
            vals.append(security.clean_text(note, 200))

        vals.append(order_id)
        db.ex(f"UPDATE orders SET {', '.join(sets)} WHERE id=?", vals)
        db.ex(
            "INSERT INTO order_events(order_id,from_status,to_status,actor_type,actor,note,at)"
            " VALUES(?,?,?,?,?,?,?)",
            (order_id, current, to_status, actor_type, actor,
             security.clean_text(note, 200), config.now_iso()),
        )

    return order_for_staff(order_id)


def purge_old_pii() -> int:
    """Scrub names and phone numbers from orders older than the retention
    window, keeping the money and item rows for reporting."""
    cutoff = (config.now() - timedelta(days=config.PII_RETENTION_DAYS)).isoformat(timespec="seconds")
    cur = db.ex(
        "UPDATE orders SET customer_name='', customer_phone='', note='', pii_purged=1"
        " WHERE pii_purged=0 AND placed_at < ?",
        (cutoff,),
    )
    return cur.rowcount or 0
