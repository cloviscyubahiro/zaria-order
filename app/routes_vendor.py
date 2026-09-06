"""Vendor console API.

Every query is scoped by the signed-in vendor's id. Ownership is enforced
inside the WHERE clause of the statement that does the work, never by a
separate "is this mine?" check that a race could slip past.
"""
from __future__ import annotations

from . import catalog, config, db, guards, orders, security
from .web import HttpError, Request, Router, json_response

router = Router()

ANNOUNCEMENT_KINDS = {"INFO", "DISCOUNT", "SOLD_OUT", "EVENT"}


# --- Auth --------------------------------------------------------------------


@router.route("POST", "/api/vendor/login")
def login(req: Request):
    guards.require_staff_network(req)
    payload = req.json()
    username = security.clean_text(payload.get("username"), 40).lower()
    password = str(payload.get("password") or "")

    scope = f"v:{username}:{security.hash_ip(req.ip)[:12]}"
    if security.login_blocked(scope):
        raise HttpError(429, "Too many failed attempts. Try again in 15 minutes.")

    row = db.q1(
        "SELECT u.*, v.name AS vendor_name, v.slug AS vendor_slug"
        " FROM vendor_users u JOIN vendors v ON v.id=u.vendor_id"
        " WHERE u.username=? AND u.is_active=1 AND v.is_active=1",
        (username,),
    )
    # Verify against a dummy hash when the user is unknown so a wrong username
    # and a wrong password take the same amount of time.
    stored = row["pw_hash"] if row else security.hash_password("not-a-real-password")
    if not security.verify_password(password, stored) or row is None:
        security.record_login_failure(scope)
        raise HttpError(401, "Wrong username or password.")

    security.clear_login_failures(scope)
    token, csrf = security.create_session("vendor", row["id"], req.ip)
    db.ex("UPDATE vendor_users SET last_login=? WHERE id=?", (config.now_iso(), row["id"]))

    resp = json_response({
        "ok": True,
        "csrf": csrf,
        "vendor": {"id": row["vendor_id"], "name": row["vendor_name"], "slug": row["vendor_slug"]},
        "user": {"display": row["display"] or row["username"], "must_change": bool(row["must_change"])},
    })
    resp.cookie(guards.VENDOR_COOKIE, token,
                max_age=int(config.SESSION_TTL.total_seconds()),
                secure=req.is_https)
    return resp


@router.route("POST", "/api/vendor/logout")
def logout(req: Request):
    security.destroy_session(req.cookie(guards.VENDOR_COOKIE))
    resp = json_response({"ok": True})
    resp.cookie(guards.VENDOR_COOKIE, "", max_age=0, secure=req.is_https)
    return resp


@router.route("GET", "/api/vendor/me")
def me(req: Request):
    actor = guards.require_vendor(req)
    v = db.q1("SELECT * FROM vendors WHERE id=?", (actor.vendor_id,))
    return json_response({
        "csrf": actor.csrf,
        "user": {"display": actor.display, "must_change": actor.must_change},
        "vendor": {
            "id": v["id"], "name": v["name"], "slug": v["slug"], "accent": v["accent"],
            "is_open": bool(v["is_open"]), "accepts_orders": bool(v["accepts_orders"]),
            "momo_code": v["momo_code"], "phone": v["phone"],
        },
    })


@router.route("POST", "/api/vendor/password")
def change_password(req: Request):
    actor = guards.require_vendor(req)
    payload = req.json()
    current = str(payload.get("current") or "")
    new = str(payload.get("new") or "")

    row = db.q1("SELECT pw_hash FROM vendor_users WHERE id=?", (actor.user_id,))
    if not security.verify_password(current, row["pw_hash"]):
        raise HttpError(403, "Your current password is not correct.")
    problem = security.password_problem(new)
    if problem:
        raise HttpError(400, problem, "new")

    db.ex("UPDATE vendor_users SET pw_hash=?, must_change=0 WHERE id=?",
          (security.hash_password(new), actor.user_id))
    # Force every other device holding this account to sign in again.
    db.ex("DELETE FROM sessions WHERE kind='vendor' AND user_id=? AND token_hash<>?",
          (actor.user_id, ""))
    return json_response({"ok": True})


# --- Shop state --------------------------------------------------------------


@router.route("POST", "/api/vendor/state")
def set_state(req: Request):
    actor = guards.require_vendor(req)
    payload = req.json()
    sets, vals = [], []
    if "is_open" in payload:
        sets.append("is_open=?")
        vals.append(1 if payload.get("is_open") else 0)
    if "accepts_orders" in payload:
        sets.append("accepts_orders=?")
        vals.append(1 if payload.get("accepts_orders") else 0)
    if "momo_code" in payload:
        sets.append("momo_code=?")
        vals.append(security.clean_text(payload.get("momo_code"), 24))
    if not sets:
        raise HttpError(400, "Nothing to update.")
    vals.append(actor.vendor_id)
    db.ex(f"UPDATE vendors SET {', '.join(sets)} WHERE id=?", vals)
    return json_response({"ok": True})


# --- Menu --------------------------------------------------------------------


@router.route("GET", "/api/vendor/menu")
def get_menu(req: Request):
    actor = guards.require_vendor(req)
    return json_response(catalog.vendor_menu(actor.vendor_id, include_hidden=True))


@router.route("POST", "/api/vendor/categories")
def create_category(req: Request):
    actor = guards.require_vendor(req)
    payload = req.json()
    name = security.clean_text(payload.get("name"), 60)
    if len(name) < 2:
        raise HttpError(400, "Give the section a name.", "name")
    nxt = db.scalar(
        "SELECT COALESCE(MAX(sort),0)+10 FROM categories WHERE vendor_id=?", (actor.vendor_id,)
    )
    cur = db.ex(
        "INSERT INTO categories(vendor_id,name,note,sort,is_active) VALUES(?,?,?,?,1)",
        (actor.vendor_id, name, security.clean_text(payload.get("note"), 200), nxt),
    )
    return json_response({"id": cur.lastrowid}, 201)


@router.route("PATCH", "/api/vendor/categories/<cid>")
def update_category(req: Request):
    actor = guards.require_vendor(req)
    cid = security.clean_int(req.params["cid"], 1, 2**31)
    payload = req.json()
    sets, vals = [], []
    if "name" in payload:
        name = security.clean_text(payload.get("name"), 60)
        if len(name) < 2:
            raise HttpError(400, "Give the section a name.", "name")
        sets.append("name=?"); vals.append(name)
    if "note" in payload:
        sets.append("note=?"); vals.append(security.clean_text(payload.get("note"), 200))
    if "is_active" in payload:
        sets.append("is_active=?"); vals.append(1 if payload.get("is_active") else 0)
    if "sort" in payload:
        sets.append("sort=?"); vals.append(security.clean_int(payload.get("sort"), 0, 100000, 0))
    if not sets:
        raise HttpError(400, "Nothing to update.")
    vals += [cid, actor.vendor_id]
    cur = db.ex(f"UPDATE categories SET {', '.join(sets)} WHERE id=? AND vendor_id=?", vals)
    if not cur.rowcount:
        raise HttpError(404, "Section not found.")
    return json_response({"ok": True})


@router.route("DELETE", "/api/vendor/categories/<cid>")
def delete_category(req: Request):
    actor = guards.require_vendor(req)
    cid = security.clean_int(req.params["cid"], 1, 2**31)
    n = db.scalar("SELECT COUNT(*) FROM items WHERE category_id=? AND vendor_id=? AND is_active=1",
                  (cid, actor.vendor_id))
    if n:
        raise HttpError(409, f"Move or remove the {n} item(s) in this section first.")
    cur = db.ex("DELETE FROM categories WHERE id=? AND vendor_id=?", (cid, actor.vendor_id))
    if not cur.rowcount:
        raise HttpError(404, "Section not found.")
    return json_response({"ok": True})


def _item_fields(payload, *, partial: bool):
    sets, vals = [], []

    def want(key):
        return key in payload

    if want("name") or not partial:
        name = security.clean_text(payload.get("name"), 90)
        if len(name) < 2:
            raise HttpError(400, "Give the item a name.", "name")
        sets.append("name=?"); vals.append(name)
    if want("description") or not partial:
        sets.append("description=?")
        vals.append(security.clean_multiline(payload.get("description"), 300))
    if want("price_rwf") or not partial:
        price = security.clean_int(payload.get("price_rwf"), 0, 5_000_000, None)
        if price is None:
            raise HttpError(400, "Price must be a whole number of francs.", "price_rwf")
        sets.append("price_rwf=?"); vals.append(price)
    if want("category_id"):
        sets.append("category_id=?")
        vals.append(security.clean_int(payload.get("category_id"), 1, 2**31, None))
    if want("tags"):
        raw = payload.get("tags") or []
        if isinstance(raw, str):
            raw = [t for t in raw.split(",")]
        tags = ",".join(security.clean_text(t, 20) for t in raw if security.clean_text(t, 20))[:120]
        sets.append("tags=?"); vals.append(tags)
    if want("is_available"):
        sets.append("is_available=?"); vals.append(1 if payload.get("is_available") else 0)
    if want("is_active"):
        sets.append("is_active=?"); vals.append(1 if payload.get("is_active") else 0)
    if want("sort"):
        sets.append("sort=?"); vals.append(security.clean_int(payload.get("sort"), 0, 100000, 0))
    return sets, vals


@router.route("POST", "/api/vendor/items")
def create_item(req: Request):
    actor = guards.require_vendor(req)
    payload = req.json()
    cat_id = security.clean_int(payload.get("category_id"), 1, 2**31, None)
    if cat_id is not None:
        owned = db.q1("SELECT 1 FROM categories WHERE id=? AND vendor_id=?",
                      (cat_id, actor.vendor_id))
        if not owned:
            raise HttpError(400, "That section does not belong to your kitchen.", "category_id")

    name = security.clean_text(payload.get("name"), 90)
    if len(name) < 2:
        raise HttpError(400, "Give the item a name.", "name")
    price = security.clean_int(payload.get("price_rwf"), 0, 5_000_000, None)
    if price is None:
        raise HttpError(400, "Price must be a whole number of francs.", "price_rwf")

    nxt = db.scalar(
        "SELECT COALESCE(MAX(sort),0)+10 FROM items WHERE vendor_id=? AND category_id IS ?",
        (actor.vendor_id, cat_id),
    )
    cur = db.ex(
        "INSERT INTO items(vendor_id,category_id,name,description,price_rwf,tags,"
        "is_available,is_active,sort,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,1,1,?,?,?)",
        (actor.vendor_id, cat_id, name,
         security.clean_multiline(payload.get("description"), 300), price,
         "", nxt, config.now_iso(), config.now_iso()),
    )
    return json_response({"id": cur.lastrowid}, 201)


@router.route("PATCH", "/api/vendor/items/<iid>")
def update_item(req: Request):
    actor = guards.require_vendor(req)
    iid = security.clean_int(req.params["iid"], 1, 2**31)
    payload = req.json()

    if "category_id" in payload and payload.get("category_id") is not None:
        cat_id = security.clean_int(payload.get("category_id"), 1, 2**31, None)
        if cat_id is not None and not db.q1(
            "SELECT 1 FROM categories WHERE id=? AND vendor_id=?", (cat_id, actor.vendor_id)
        ):
            raise HttpError(400, "That section does not belong to your kitchen.", "category_id")

    sets, vals = _item_fields(payload, partial=True)
    if not sets:
        raise HttpError(400, "Nothing to update.")
    sets.append("updated_at=?"); vals.append(config.now_iso())
    vals += [iid, actor.vendor_id]
    cur = db.ex(f"UPDATE items SET {', '.join(sets)} WHERE id=? AND vendor_id=?", vals)
    if not cur.rowcount:
        raise HttpError(404, "Item not found.")
    return json_response({"ok": True})


@router.route("DELETE", "/api/vendor/items/<iid>")
def delete_item(req: Request):
    """Soft delete. Past orders reference the item, and the sales report would
    lose its link if the row disappeared."""
    actor = guards.require_vendor(req)
    iid = security.clean_int(req.params["iid"], 1, 2**31)
    cur = db.ex(
        "UPDATE items SET is_active=0, is_available=0, updated_at=? WHERE id=? AND vendor_id=?",
        (config.now_iso(), iid, actor.vendor_id),
    )
    if not cur.rowcount:
        raise HttpError(404, "Item not found.")
    return json_response({"ok": True})


@router.route("POST", "/api/vendor/items/bulk")
def bulk_items(req: Request):
    """Used by the 'sold out' sweep at the end of a night."""
    actor = guards.require_vendor(req)
    payload = req.json()
    ids = payload.get("ids") or []
    if not isinstance(ids, list) or not ids:
        raise HttpError(400, "Select at least one item.")
    ids = [security.clean_int(i, 1, 2**31, None) for i in ids][:300]
    ids = [i for i in ids if i is not None]
    if not ids:
        raise HttpError(400, "Select at least one item.")
    available = 1 if payload.get("is_available") else 0
    marks = ",".join("?" for _ in ids)
    db.ex(
        f"UPDATE items SET is_available=?, updated_at=? WHERE vendor_id=? AND id IN ({marks})",
        [available, config.now_iso(), actor.vendor_id, *ids],
    )
    return json_response({"ok": True, "updated": len(ids)})


# --- Discounts ---------------------------------------------------------------


@router.route("GET", "/api/vendor/discounts")
def list_discounts(req: Request):
    actor = guards.require_vendor(req)
    rows = db.q(
        "SELECT * FROM discounts WHERE vendor_id=? ORDER BY is_active DESC, id DESC",
        (actor.vendor_id,),
    )
    return json_response({"discounts": [dict(r) for r in rows]})


@router.route("POST", "/api/vendor/discounts")
def create_discount(req: Request):
    actor = guards.require_vendor(req)
    payload = req.json()
    scope = security.clean_text(payload.get("scope"), 12) or "vendor"
    if scope not in {"vendor", "category", "item"}:
        raise HttpError(400, "Unknown discount scope.")
    percent = security.clean_int(payload.get("percent"), 1, 90, None)
    if percent is None:
        raise HttpError(400, "Discount must be between 1% and 90%.", "percent")

    target_id = None
    if scope != "vendor":
        target_id = security.clean_int(payload.get("target_id"), 1, 2**31, None)
        table = "categories" if scope == "category" else "items"
        if target_id is None or not db.q1(
            f"SELECT 1 FROM {table} WHERE id=? AND vendor_id=?", (target_id, actor.vendor_id)
        ):
            raise HttpError(400, "Pick something from your own menu to discount.", "target_id")

    cur = db.ex(
        "INSERT INTO discounts(vendor_id,scope,target_id,percent,label,starts_at,ends_at,"
        "is_active,created_at) VALUES(?,?,?,?,?,?,?,1,?)",
        (actor.vendor_id, scope, target_id, percent,
         security.clean_text(payload.get("label"), 60),
         security.clean_text(payload.get("starts_at"), 40) or None,
         security.clean_text(payload.get("ends_at"), 40) or None,
         config.now_iso()),
    )
    return json_response({"id": cur.lastrowid}, 201)


@router.route("PATCH", "/api/vendor/discounts/<did>")
def update_discount(req: Request):
    actor = guards.require_vendor(req)
    did = security.clean_int(req.params["did"], 1, 2**31)
    payload = req.json()
    sets, vals = [], []
    if "is_active" in payload:
        sets.append("is_active=?"); vals.append(1 if payload.get("is_active") else 0)
    if "percent" in payload:
        pct = security.clean_int(payload.get("percent"), 1, 90, None)
        if pct is None:
            raise HttpError(400, "Discount must be between 1% and 90%.", "percent")
        sets.append("percent=?"); vals.append(pct)
    if "ends_at" in payload:
        sets.append("ends_at=?")
        vals.append(security.clean_text(payload.get("ends_at"), 40) or None)
    if not sets:
        raise HttpError(400, "Nothing to update.")
    vals += [did, actor.vendor_id]
    cur = db.ex(f"UPDATE discounts SET {', '.join(sets)} WHERE id=? AND vendor_id=?", vals)
    if not cur.rowcount:
        raise HttpError(404, "Discount not found.")
    return json_response({"ok": True})


# --- Announcements -----------------------------------------------------------


def _briefing() -> list[dict]:
    """What admin has asked the kitchens to do. Never leaves the staff screens."""
    now = config.now()
    rows = db.q(
        "SELECT id,kind,body,created_at,created_by,starts_at,ends_at FROM announcements"
        " WHERE is_active=1 AND audience='VENDORS'"
        " ORDER BY priority DESC, created_at DESC LIMIT 20"
    )
    return [dict(r) for r in rows if catalog.is_live(r["starts_at"], r["ends_at"], now)]


@router.route("GET", "/api/vendor/briefing")
def briefing(req: Request):
    guards.require_vendor(req)
    return json_response({"briefing": _briefing()})


@router.route("GET", "/api/vendor/announcements")
def list_announcements(req: Request):
    actor = guards.require_vendor(req)
    rows = db.q(
        "SELECT * FROM announcements WHERE vendor_id=? ORDER BY is_active DESC, id DESC LIMIT 100",
        (actor.vendor_id,),
    )
    return json_response({
        "announcements": [dict(r) for r in rows],
        "briefing": _briefing(),
    })


@router.route("POST", "/api/vendor/announcements")
def create_announcement(req: Request):
    actor = guards.require_vendor(req)
    payload = req.json()
    body = security.clean_text(payload.get("body"), 160)
    if len(body) < 3:
        raise HttpError(400, "Write the message guests should see.", "body")
    kind = security.clean_text(payload.get("kind"), 12).upper() or "INFO"
    if kind not in ANNOUNCEMENT_KINDS:
        kind = "INFO"
    cur = db.ex(
        "INSERT INTO announcements(vendor_id,kind,body,starts_at,ends_at,priority,"
        "is_active,created_at,created_by) VALUES(?,?,?,?,?,?,1,?,?)",
        (actor.vendor_id, kind, body,
         security.clean_text(payload.get("starts_at"), 40) or None,
         security.clean_text(payload.get("ends_at"), 40) or None,
         security.clean_int(payload.get("priority"), 0, 100, 0),
         config.now_iso(), actor.username),
    )
    return json_response({"id": cur.lastrowid}, 201)


@router.route("PATCH", "/api/vendor/announcements/<aid>")
def update_announcement(req: Request):
    actor = guards.require_vendor(req)
    aid = security.clean_int(req.params["aid"], 1, 2**31)
    payload = req.json()
    sets, vals = [], []
    if "is_active" in payload:
        sets.append("is_active=?"); vals.append(1 if payload.get("is_active") else 0)
    if "body" in payload:
        body = security.clean_text(payload.get("body"), 160)
        if len(body) < 3:
            raise HttpError(400, "Write the message guests should see.", "body")
        sets.append("body=?"); vals.append(body)
    if not sets:
        raise HttpError(400, "Nothing to update.")
    vals += [aid, actor.vendor_id]
    cur = db.ex(f"UPDATE announcements SET {', '.join(sets)} WHERE id=? AND vendor_id=?", vals)
    if not cur.rowcount:
        raise HttpError(404, "Announcement not found.")
    return json_response({"ok": True})


# --- Order queue -------------------------------------------------------------


@router.route("GET", "/api/vendor/orders")
def list_orders(req: Request):
    actor = guards.require_vendor(req)
    scope = req.query.get("scope", "open")
    if scope == "open":
        rows = db.q(
            "SELECT id FROM orders WHERE vendor_id=? AND status IN ('PENDING','ACCEPTED','READY','DELIVERED')"
            " ORDER BY placed_at", (actor.vendor_id,),
        )
    elif scope == "today":
        start = config.to_kigali(config.now()).replace(hour=0, minute=0, second=0, microsecond=0)
        rows = db.q(
            "SELECT id FROM orders WHERE vendor_id=? AND placed_at >= ? ORDER BY placed_at DESC",
            (actor.vendor_id, start.astimezone(config.KIGALI).isoformat(timespec="seconds")),
        )
    else:
        rows = db.q(
            "SELECT id FROM orders WHERE vendor_id=? ORDER BY placed_at DESC LIMIT 200",
            (actor.vendor_id,),
        )
    return json_response({
        "orders": [orders.order_for_staff(r["id"]) for r in rows],
        # Ride along with the queue the kitchen already watches. A briefing on a
        # tab nobody opens during service is a briefing nobody reads.
        "briefing": _briefing(),
        "server_time": config.now_iso(),
    })


@router.route("POST", "/api/vendor/orders/<oid>/status")
def set_status(req: Request):
    actor = guards.require_vendor(req)
    oid = security.clean_int(req.params["oid"], 1, 2**31)
    payload = req.json()
    order = orders.transition(
        oid,
        security.clean_text(payload.get("status"), 20),
        actor_type="vendor",
        actor=actor.username,
        vendor_id=actor.vendor_id,
        payment_method=security.clean_text(payload.get("payment_method"), 12),
        note=payload.get("note", ""),
    )
    return json_response(order)


@router.route("GET", "/api/vendor/summary")
def summary(req: Request):
    actor = guards.require_vendor(req)
    start = config.to_kigali(config.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    since = start.isoformat(timespec="seconds")
    row = db.q1(
        "SELECT COUNT(*) AS orders,"
        " COALESCE(SUM(CASE WHEN status='PAID' THEN total_rwf ELSE 0 END),0) AS collected,"
        " COALESCE(SUM(CASE WHEN status IN ('PENDING','ACCEPTED','READY','DELIVERED')"
        "   THEN total_rwf ELSE 0 END),0) AS outstanding,"
        " SUM(CASE WHEN status='PENDING' THEN 1 ELSE 0 END) AS pending"
        " FROM orders WHERE vendor_id=? AND placed_at >= ?",
        (actor.vendor_id, since),
    )
    return json_response(dict(row))
