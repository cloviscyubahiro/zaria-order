"""Central configuration. No third-party packages anywhere in this project."""
from __future__ import annotations

import os
import pathlib
import secrets
from datetime import datetime, timedelta, timezone

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
WEB_DIR = BASE_DIR / "web"
DB_PATH = DATA_DIR / "zaria.db"
SECRET_PATH = DATA_DIR / "secret.key"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# Rwanda is Central Africa Time, permanently UTC+2. It has never observed DST,
# so a fixed offset is correct and avoids depending on a tz database that
# Windows Python does not ship.
KIGALI = timezone(timedelta(hours=2), "CAT")

CURRENCY = "RWF"

# How guests receive an order at this event.
#   TABLE  — every order needs a table number (seated event; the default)
#   PICKUP — no tables at all; the guest collects at the kitchen with a code
#   BOTH   — some guests are seated, some are standing
# Set from Admin -> Settings before each event; nothing else has to change.
SERVICE_MODES = ("TABLE", "PICKUP", "BOTH")
DEFAULT_SERVICE_MODE = "TABLE"


def service_mode() -> str:
    """Read the current mode. Imported lazily to avoid a config->db cycle."""
    from . import db

    mode = (db.setting("service_mode", DEFAULT_SERVICE_MODE) or "").upper()
    return mode if mode in SERVICE_MODES else DEFAULT_SERVICE_MODE


def _tunable(key: str, default: int, low: int, high: int) -> int:
    """A limit the venue can adjust mid-event without touching a file."""
    from . import db

    try:
        value = int(db.setting(key, "") or 0)
    except ValueError:
        return default
    return value if low <= value <= high else default


def orders_per_device_hour() -> int:
    return _tunable("orders_per_device_hour", MAX_ORDERS_PER_DEVICE_HOUR, 1, 500)


def orders_per_shared_ip_hour() -> int:
    """The crowd-sized cap, adjustable from Admin -> Settings during an event.

    Defined here rather than beside the constant because it needs the database.
    """
    from . import db

    return _tunable("orders_per_shared_ip_hour",
                    MAX_ORDERS_PER_SHARED_IP_HOUR, 10, 100_000)

# --- Secrets -----------------------------------------------------------------


def _load_secret() -> bytes:
    """Load the HMAC/session secret, creating it on first run.

    Kept out of source control on purpose: rotating this file invalidates every
    session and every printed table QR code.
    """
    env = os.environ.get("ZARIA_SECRET")
    if env:
        return env.encode("utf-8")
    if SECRET_PATH.exists():
        raw = SECRET_PATH.read_bytes().strip()
        if len(raw) >= 32:
            return raw
    raw = secrets.token_bytes(48)
    SECRET_PATH.write_bytes(raw)
    try:  # best-effort lockdown on POSIX; a no-op on Windows
        os.chmod(SECRET_PATH, 0o600)
    except OSError:
        pass
    return raw


SECRET = _load_secret()

# --- Tunables ----------------------------------------------------------------

SESSION_TTL = timedelta(hours=12)          # staff logins expire same-shift
GUEST_TTL = timedelta(hours=6)             # a guest's browser identity

# Anti-abuse. These are the numbers that stop a prank from flooding a kitchen
# during a concert. Tune them in the admin settings page, not here.
MAX_OPEN_ORDERS_PER_TABLE = 6

# One browser's budget. A group sharing one phone is normal -- somebody orders,
# then somebody else wants a drink, then another round -- so this has to be
# generous enough that a real table never meets it. It is the cap that actually
# stops a prankster, because it follows the browser onto any network.
MAX_ORDERS_PER_DEVICE_HOUR = 20

# Per-address caps have to be sized by how many people share the address.
#
# On the venue network every device -- phone, tablet or the kiosk PC -- has its
# own 192.168.x.x, so an address is one device and a tighter cap is right.
# Coming in from the internet it is the opposite: every guest on Zaria Wi-Fi
# leaves through the venue's single public address, and every guest on the same
# mobile carrier shares a small pool of addresses behind carrier-grade NAT. One
# cap for both would either be uselessly loose on the LAN or would stop the whole
# venue ordering after a few dozen plates -- which is what would have happened.
#
# A kiosk PC is the exception that proves the rule: it is one device placing
# orders for many guests, so it is exempted explicitly (Admin -> Settings).
MAX_ORDERS_PER_LAN_IP_HOUR = 60
MAX_ORDERS_PER_SHARED_IP_HOUR = 400
MAX_ITEMS_PER_ORDER = 40
MAX_QTY_PER_LINE = 20
MAX_ORDER_VALUE_RWF = 2_000_000

LOGIN_MAX_ATTEMPTS = 8
LOGIN_LOCKOUT = timedelta(minutes=15)

# How long we keep customer names/phones before scrubbing them. Rwanda's Law
# 058/2021 on personal data protection expects a stated retention period.
PII_RETENTION_DAYS = 90

WHATSAPP_URL = "https://chat.whatsapp.com/GCa3ijAoQjiJH2ECfGd9P0"


def now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def to_kigali(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KIGALI)
