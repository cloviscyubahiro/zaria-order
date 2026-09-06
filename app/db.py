"""SQLite access layer.

One connection per thread (the HTTP server is threaded), WAL journaling so
readers never block the kitchen writing an order status.

Money is stored as whole Rwandan francs in INTEGER columns. RWF has no
circulating subunit, so there is no cents/x100 conversion anywhere.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable

from . import config

_local = threading.local()
_write_lock = threading.Lock()

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS vendors (
  id          INTEGER PRIMARY KEY,
  slug        TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  kind        TEXT NOT NULL DEFAULT '',
  tagline     TEXT NOT NULL DEFAULT '',
  accent      TEXT NOT NULL DEFAULT '#C9A063',
  logo        TEXT NOT NULL DEFAULT '',
  momo_code   TEXT NOT NULL DEFAULT '',
  phone       TEXT NOT NULL DEFAULT '',
  external_url TEXT NOT NULL DEFAULT '',
  accepts_orders INTEGER NOT NULL DEFAULT 1,
  is_open     INTEGER NOT NULL DEFAULT 1,
  is_active   INTEGER NOT NULL DEFAULT 1,
  sort        INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vendor_users (
  id         INTEGER PRIMARY KEY,
  vendor_id  INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
  username   TEXT NOT NULL UNIQUE,
  pw_hash    TEXT NOT NULL,
  display    TEXT NOT NULL DEFAULT '',
  is_active  INTEGER NOT NULL DEFAULT 1,
  must_change INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_login TEXT
);

CREATE TABLE IF NOT EXISTS admin_users (
  id         INTEGER PRIMARY KEY,
  username   TEXT NOT NULL UNIQUE,
  pw_hash    TEXT NOT NULL,
  display    TEXT NOT NULL DEFAULT '',
  is_active  INTEGER NOT NULL DEFAULT 1,
  must_change INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_login TEXT
);

CREATE TABLE IF NOT EXISTS categories (
  id        INTEGER PRIMARY KEY,
  vendor_id INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
  name      TEXT NOT NULL,
  note      TEXT NOT NULL DEFAULT '',
  sort      INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_cat_vendor ON categories(vendor_id, sort);

CREATE TABLE IF NOT EXISTS items (
  id          INTEGER PRIMARY KEY,
  vendor_id   INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
  category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  name        TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  price_rwf   INTEGER NOT NULL CHECK (price_rwf >= 0),
  tags        TEXT NOT NULL DEFAULT '',
  is_available INTEGER NOT NULL DEFAULT 1,
  is_active   INTEGER NOT NULL DEFAULT 1,
  sort        INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_item_vendor ON items(vendor_id, category_id, sort);

-- Percentage discounts a vendor runs during an event. Applied server-side at
-- checkout; the browser never decides a price.
CREATE TABLE IF NOT EXISTS discounts (
  id          INTEGER PRIMARY KEY,
  vendor_id   INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
  scope       TEXT NOT NULL DEFAULT 'vendor',   -- vendor | category | item
  target_id   INTEGER,
  percent     INTEGER NOT NULL CHECK (percent BETWEEN 1 AND 90),
  label       TEXT NOT NULL DEFAULT '',
  starts_at   TEXT,
  ends_at     TEXT,
  is_active   INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_disc_vendor ON discounts(vendor_id, is_active);

-- The scrolling "subtitles" on the guest screen, and the noticeboard admin uses
-- to brief the kitchens. `audience` is what separates the two: a VENDORS notice
-- is staff-only and must never reach a guest.
CREATE TABLE IF NOT EXISTS announcements (
  id         INTEGER PRIMARY KEY,
  vendor_id  INTEGER REFERENCES vendors(id) ON DELETE CASCADE,  -- NULL = venue-wide
  audience   TEXT NOT NULL DEFAULT 'GUESTS', -- GUESTS | VENDORS
  kind       TEXT NOT NULL DEFAULT 'INFO',   -- INFO | DISCOUNT | SOLD_OUT | EVENT
  body       TEXT NOT NULL,
  starts_at  TEXT,
  ends_at    TEXT,
  priority   INTEGER NOT NULL DEFAULT 0,
  is_active  INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ann_live ON announcements(is_active, priority);

CREATE TABLE IF NOT EXISTS venue_tables (
  id         INTEGER PRIMARY KEY,
  code       TEXT NOT NULL UNIQUE,     -- what the guest sees, e.g. "A12"
  label      TEXT NOT NULL DEFAULT '',
  zone       TEXT NOT NULL DEFAULT '',
  is_active  INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
  id            INTEGER PRIMARY KEY,
  public_code   TEXT NOT NULL UNIQUE,   -- unguessable; used for guest tracking
  short_code    TEXT NOT NULL,          -- 4 chars, shouted across a kitchen
  group_key     TEXT NOT NULL DEFAULT '',
  vendor_id     INTEGER NOT NULL REFERENCES vendors(id) ON DELETE RESTRICT,
  table_id      INTEGER REFERENCES venue_tables(id) ON DELETE SET NULL,
  table_code    TEXT NOT NULL DEFAULT '',
  customer_name TEXT NOT NULL DEFAULT '',
  customer_phone TEXT NOT NULL DEFAULT '',
  note          TEXT NOT NULL DEFAULT '',
  status        TEXT NOT NULL DEFAULT 'PENDING',
  subtotal_rwf  INTEGER NOT NULL DEFAULT 0,
  discount_rwf  INTEGER NOT NULL DEFAULT 0,
  total_rwf     INTEGER NOT NULL DEFAULT 0,
  payment_method TEXT NOT NULL DEFAULT '',
  device_hash   TEXT NOT NULL DEFAULT '',
  ip_hash       TEXT NOT NULL DEFAULT '',
  placed_at     TEXT NOT NULL,
  accepted_at   TEXT,
  ready_at      TEXT,
  delivered_at  TEXT,
  paid_at       TEXT,
  closed_at     TEXT,
  cancel_reason TEXT NOT NULL DEFAULT '',
  pii_purged    INTEGER NOT NULL DEFAULT 0,
  updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ord_vendor ON orders(vendor_id, status, placed_at);
CREATE INDEX IF NOT EXISTS idx_ord_placed ON orders(placed_at);
CREATE INDEX IF NOT EXISTS idx_ord_group ON orders(group_key);
CREATE INDEX IF NOT EXISTS idx_ord_device ON orders(device_hash, placed_at);

CREATE TABLE IF NOT EXISTS order_items (
  id            INTEGER PRIMARY KEY,
  order_id      INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  item_id       INTEGER REFERENCES items(id) ON DELETE SET NULL,
  name_snapshot TEXT NOT NULL,
  unit_price_rwf INTEGER NOT NULL,
  qty           INTEGER NOT NULL CHECK (qty > 0),
  line_total_rwf INTEGER NOT NULL,
  discount_rwf  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_oi_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_oi_item ON order_items(item_id);

CREATE TABLE IF NOT EXISTS order_events (
  id          INTEGER PRIMARY KEY,
  order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  from_status TEXT NOT NULL DEFAULT '',
  to_status   TEXT NOT NULL,
  actor_type  TEXT NOT NULL DEFAULT 'system',
  actor       TEXT NOT NULL DEFAULT '',
  note        TEXT NOT NULL DEFAULT '',
  at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_oe_order ON order_events(order_id, at);

CREATE TABLE IF NOT EXISTS sessions (
  id         INTEGER PRIMARY KEY,
  kind       TEXT NOT NULL,            -- vendor | admin
  user_id    INTEGER NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  csrf       TEXT NOT NULL,
  ip_hash    TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sess_exp ON sessions(expires_at);

-- Analytics. Deliberately coarse: no raw IPs, no cross-site identifiers.
CREATE TABLE IF NOT EXISTS events (
  id         INTEGER PRIMARY KEY,
  kind       TEXT NOT NULL,     -- page_view | vendor_view | whatsapp_click | order_start
  vendor_id  INTEGER,
  table_code TEXT NOT NULL DEFAULT '',
  visitor    TEXT NOT NULL DEFAULT '',   -- rotating hashed device id
  meta       TEXT NOT NULL DEFAULT '',
  at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ev_kind ON events(kind, at);
CREATE INDEX IF NOT EXISTS idx_ev_visitor ON events(visitor, at);

CREATE TABLE IF NOT EXISTS rate_limits (
  bucket     TEXT PRIMARY KEY,
  count      INTEGER NOT NULL DEFAULT 0,
  window_end TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blocklist (
  id         INTEGER PRIMARY KEY,
  kind       TEXT NOT NULL,     -- device | phone | ip
  value      TEXT NOT NULL,
  reason     TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(kind, value)
);

CREATE TABLE IF NOT EXISTS login_attempts (
  id       INTEGER PRIMARY KEY,
  scope    TEXT NOT NULL,
  at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_la ON login_attempts(scope, at);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(config.DB_PATH, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=8000")
        _local.conn = conn
    return conn


# Columns added after the first release. CREATE TABLE IF NOT EXISTS leaves an
# existing table alone, so new columns have to be added explicitly or a venue
# that has already run an event would start with a broken database.
MIGRATIONS = [
    ("announcements", "audience", "TEXT NOT NULL DEFAULT 'GUESTS'"),
]


def _migrate(conn) -> None:
    for table, column, decl in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if cols and column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init() -> None:
    conn = connect()
    conn.executescript(SCHEMA)
    _migrate(conn)


@contextmanager
def tx():
    """Serialise writers. SQLite allows one writer; making that explicit keeps
    error handling predictable under a burst of concurrent checkouts."""
    conn = connect()
    with _write_lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def q(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return connect().execute(sql, tuple(params)).fetchall()


def q1(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return connect().execute(sql, tuple(params)).fetchone()


def scalar(sql: str, params: Iterable[Any] = (), default: Any = 0) -> Any:
    row = q1(sql, params)
    if row is None:
        return default
    val = row[0]
    return default if val is None else val


def ex(sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    return connect().execute(sql, tuple(params))


def setting(key: str, default: str = "") -> str:
    row = q1("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    ex(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
