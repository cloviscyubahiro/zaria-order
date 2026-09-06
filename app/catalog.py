"""Menu reads and discount arithmetic.

The single rule this module exists to enforce: a price is whatever the database
says it is, right now. The browser sends item ids and quantities and nothing
else. Any "price" field arriving from a client is ignored, not validated.
"""
from __future__ import annotations

from datetime import datetime

from . import config, db


def _live(row_starts: str | None, row_ends: str | None, now: datetime) -> bool:
    if row_starts:
        try:
            if datetime.fromisoformat(row_starts) > now:
                return False
        except ValueError:
            pass
    if row_ends:
        try:
            if datetime.fromisoformat(row_ends) <= now:
                return False
        except ValueError:
            pass
    return True


def active_discounts(vendor_id: int) -> list[dict]:
    now = config.now()
    rows = db.q(
        "SELECT * FROM discounts WHERE vendor_id=? AND is_active=1", (vendor_id,)
    )
    return [dict(r) for r in rows if _live(r["starts_at"], r["ends_at"], now)]


def discount_percent_for(item: dict, discounts: list[dict]) -> tuple[int, str]:
    """Best (highest) applicable percentage for one item.

    Discounts do not stack — stacking is how a venue accidentally gives away a
    plate for 0 RWF. The most specific/largest single discount wins.
    """
    best, label = 0, ""
    for d in discounts:
        scope = d["scope"]
        if scope == "vendor":
            ok = True
        elif scope == "category":
            ok = item.get("category_id") == d["target_id"]
        elif scope == "item":
            ok = item["id"] == d["target_id"]
        else:
            ok = False
        if ok and d["percent"] > best:
            best, label = d["percent"], d["label"] or f"-{d['percent']}%"
    return best, label


def discounted_price(price_rwf: int, percent: int) -> int:
    """Round to the nearest 100 RWF. Nobody at a container-park kiosk is making
    change for 7 francs, and a clean number speeds up the cash handover."""
    if percent <= 0:
        return price_rwf
    net = price_rwf * (100 - percent) / 100.0
    return max(0, int(round(net / 100.0)) * 100)


def vendor_menu(vendor_id: int, *, include_hidden: bool = False) -> dict:
    vendor = db.q1("SELECT * FROM vendors WHERE id=?", (vendor_id,))
    if not vendor:
        return {}
    discounts = active_discounts(vendor_id)

    cat_sql = "SELECT * FROM categories WHERE vendor_id=?"
    if not include_hidden:
        cat_sql += " AND is_active=1"
    cat_sql += " ORDER BY sort, id"
    cats = [dict(r) for r in db.q(cat_sql, (vendor_id,))]

    item_sql = "SELECT * FROM items WHERE vendor_id=?"
    if not include_hidden:
        item_sql += " AND is_active=1"
    item_sql += " ORDER BY sort, id"
    items = [dict(r) for r in db.q(item_sql, (vendor_id,))]

    by_cat: dict[int | None, list[dict]] = {}
    for it in items:
        pct, label = discount_percent_for(it, discounts)
        it["discount_percent"] = pct
        it["discount_label"] = label
        it["base_price_rwf"] = it["price_rwf"]
        it["price_rwf"] = discounted_price(it["price_rwf"], pct)
        it["tags"] = [t for t in (it.get("tags") or "").split(",") if t]
        by_cat.setdefault(it["category_id"], []).append(it)

    for c in cats:
        c["items"] = by_cat.get(c["id"], [])

    return {
        "vendor": dict(vendor),
        "categories": [c for c in cats if c["items"] or include_hidden],
        "uncategorised": by_cat.get(None, []),
        "discounts": discounts,
    }


# Public name for other modules. A staff briefing is scheduled by the same
# start/end rules as anything a guest sees.
is_live = _live


def live_announcements() -> list[dict]:
    """What scrolls across the guest screen.

    The audience filter is in the SQL rather than applied afterwards: a message
    admin wrote for the kitchens ("push the fish, we over-ordered") must never
    be one refactor away from a guest's phone.
    """
    now = config.now()
    rows = db.q(
        "SELECT a.*, v.name AS vendor_name, v.accent AS vendor_accent "
        "FROM announcements a LEFT JOIN vendors v ON v.id=a.vendor_id "
        "WHERE a.is_active=1 AND a.audience='GUESTS' "
        "ORDER BY a.priority DESC, a.created_at DESC"
    )
    out = []
    for r in rows:
        if _live(r["starts_at"], r["ends_at"], now):
            d = dict(r)
            d.pop("created_by", None)
            out.append(d)
    return out


def vendor_list() -> list[dict]:
    rows = db.q(
        "SELECT id,slug,name,kind,tagline,accent,logo,external_url,"
        "accepts_orders,is_open,momo_code,phone "
        "FROM vendors WHERE is_active=1 ORDER BY sort, id"
    )
    now = config.now()
    out = []
    for r in rows:
        d = dict(r)
        d["item_count"] = db.scalar(
            "SELECT COUNT(*) FROM items WHERE vendor_id=? AND is_active=1 AND is_available=1",
            (r["id"],),
        )
        best = 0
        for disc in db.q(
            "SELECT percent,starts_at,ends_at FROM discounts WHERE vendor_id=? AND is_active=1",
            (r["id"],),
        ):
            if _live(disc["starts_at"], disc["ends_at"], now):
                best = max(best, disc["percent"])
        d["top_discount"] = best
        out.append(d)
    return out
