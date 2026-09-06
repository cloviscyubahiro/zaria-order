"""Passwords, sessions, CSRF, signed table codes, rate limiting, input hygiene.

Design notes that matter operationally:

* Guests are never asked to create an account. Their identity is a rotating
  random id in a cookie, hashed before storage. That is enough to rate-limit
  and to let them watch their own order, and it stores nothing re-identifiable.
* Table codes in a QR are signed. Without a signature anyone could point an
  order at any table by editing the URL.
* Raw IPs are never written to disk; only a keyed hash.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import unicodedata
from datetime import datetime, timedelta

from . import config, db

# --- Passwords ---------------------------------------------------------------

_SCRYPT = dict(n=2**15, r=8, p=1, dklen=32)

# scrypt needs roughly 128 * n * r bytes — 32 MB at these parameters, which is
# exactly OpenSSL's default ceiling. Ask for headroom or every hash raises
# "memory limit exceeded". Staff logins are rare, so the cost is irrelevant.
_MAXMEM = 132 * 1024 * 1024


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, maxmem=_MAXMEM, **_SCRYPT)
    return "scrypt$%d$%d$%d$%s$%s" % (
        _SCRYPT["n"], _SCRYPT["r"], _SCRYPT["p"],
        base64.b64encode(salt).decode(), base64.b64encode(dk).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n), r=int(r), p=int(p),
            dklen=len(base64.b64decode(dk_b64)),
            maxmem=_MAXMEM,
        )
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


def password_problem(pw: str) -> str | None:
    """Deliberately modest rules. Staff on a phone at a loud venue will write
    down anything longer, which is worse than a 10-character passphrase."""
    if len(pw) < 10:
        return "Password must be at least 10 characters."
    if pw.lower() in {"password12", "zariacourt", "1234567890", "qwertyuiop"}:
        return "That password is too common."
    return None


# --- Keyed hashes ------------------------------------------------------------


def keyed(value: str, domain: str) -> str:
    """Domain-separated HMAC. Used for IPs and device ids so a database leak
    does not hand over a list of visitor addresses."""
    mac = hmac.new(config.SECRET, f"{domain}:{value}".encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()[:32]


def hash_ip(ip: str) -> str:
    return keyed(ip or "-", "ip")


def hash_device(device_id: str) -> str:
    return keyed(device_id or "-", "device")


# --- Signed table codes ------------------------------------------------------


def sign_table(code: str) -> str:
    """Produce the `t=` value that goes in a printed QR code."""
    mac = hmac.new(config.SECRET, f"table:{code}".encode("utf-8"), hashlib.sha256)
    sig = base64.urlsafe_b64encode(mac.digest()[:9]).decode().rstrip("=")
    return f"{code}.{sig}"


def verify_table(token: str) -> str | None:
    if not token or "." not in token:
        return None
    code, _, sig = token.rpartition(".")
    if not code:
        return None
    expected = sign_table(code).rpartition(".")[2]
    return code if hmac.compare_digest(sig, expected) else None


# --- Sessions ----------------------------------------------------------------


def _token_hash(token: str) -> str:
    return hashlib.sha256(f"sess:{token}".encode("utf-8")).hexdigest()


def create_session(kind: str, user_id: int, ip: str) -> tuple[str, str]:
    """Returns (raw_token, csrf). Only the hash of the token is stored, so a
    read of the sessions table cannot be replayed as a login."""
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    expires = config.now() + config.SESSION_TTL
    db.ex(
        "INSERT INTO sessions(kind,user_id,token_hash,csrf,ip_hash,created_at,expires_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (kind, user_id, _token_hash(token), csrf, hash_ip(ip),
         config.now_iso(), expires.isoformat(timespec="seconds")),
    )
    return token, csrf


def load_session(token: str):
    if not token:
        return None
    row = db.q1(
        "SELECT * FROM sessions WHERE token_hash=?", (_token_hash(token),)
    )
    if not row:
        return None
    if datetime.fromisoformat(row["expires_at"]) <= config.now():
        db.ex("DELETE FROM sessions WHERE id=?", (row["id"],))
        return None
    return row


def destroy_session(token: str) -> None:
    if token:
        db.ex("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))


def purge_sessions() -> None:
    db.ex("DELETE FROM sessions WHERE expires_at <= ?", (config.now_iso(),))


# --- Login throttling --------------------------------------------------------


def login_blocked(scope: str) -> bool:
    since = (config.now() - config.LOGIN_LOCKOUT).isoformat(timespec="seconds")
    n = db.scalar(
        "SELECT COUNT(*) FROM login_attempts WHERE scope=? AND at > ?", (scope, since)
    )
    return n >= config.LOGIN_MAX_ATTEMPTS


def record_login_failure(scope: str) -> None:
    db.ex("INSERT INTO login_attempts(scope,at) VALUES(?,?)", (scope, config.now_iso()))


def clear_login_failures(scope: str) -> None:
    db.ex("DELETE FROM login_attempts WHERE scope=?", (scope,))


# --- Rate limiting -----------------------------------------------------------


def rate_hit(bucket: str, limit: int, window: timedelta) -> bool:
    """Fixed-window counter. Returns True when the caller is within budget.

    Fixed windows can allow a 2x burst across a boundary. For "stop a prankster
    flooding the kitchen" that is entirely adequate, and it is one row.
    """
    now = config.now()
    row = db.q1("SELECT count, window_end FROM rate_limits WHERE bucket=?", (bucket,))
    if row is None or datetime.fromisoformat(row["window_end"]) <= now:
        db.ex(
            "INSERT INTO rate_limits(bucket,count,window_end) VALUES(?,1,?)"
            " ON CONFLICT(bucket) DO UPDATE SET count=1, window_end=excluded.window_end",
            (bucket, (now + window).isoformat(timespec="seconds")),
        )
        return True
    if row["count"] >= limit:
        return False
    db.ex("UPDATE rate_limits SET count=count+1 WHERE bucket=?", (bucket,))
    return True


def purge_rate_limits() -> None:
    db.ex("DELETE FROM rate_limits WHERE window_end <= ?", (config.now_iso(),))


# --- Blocklist ---------------------------------------------------------------


def is_blocked(kind: str, value: str) -> bool:
    if not value:
        return False
    return db.q1("SELECT 1 FROM blocklist WHERE kind=? AND value=?", (kind, value)) is not None


def is_exempt(device_hash: str, ip_hash: str) -> bool:
    """A registered kiosk: one device that legitimately orders for many guests.

    Rate limits assume a device is a guest. The kiosk PC by the entrance breaks
    that assumption -- staff put in twenty orders an hour from it on purpose --
    so it is listed once and skipped. Being exempt from a *limit* is not being
    exempt from anything else; the kiosk is still an ordinary guest to the rest
    of the system.
    """
    return (is_blocked("kiosk_device", device_hash)
            or is_blocked("kiosk_ip", ip_hash))


# --- Input hygiene -----------------------------------------------------------

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_password_like(value, limit: int = 200) -> str:
    """Strip control characters and cap length, but leave spacing alone.

    For values a device compares byte for byte — a Wi-Fi key, say — where
    collapsing whitespace would quietly turn a working password into a wrong one.
    """
    if value is None:
        return ""
    return _CTRL.sub("", unicodedata.normalize("NFC", str(value)))[:limit]


def clean_text(value, limit: int = 200) -> str:
    """Normalise, strip control characters, collapse whitespace, cap length.

    This is *not* what protects against XSS — the frontends render with
    textContent and never inject HTML. This keeps junk out of the database and
    stops a vendor pasting 40KB into a ticker.
    """
    if value is None:
        return ""
    s = unicodedata.normalize("NFC", str(value))
    s = _CTRL.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def clean_multiline(value, limit: int = 1000) -> str:
    if value is None:
        return ""
    s = unicodedata.normalize("NFC", str(value))
    s = _CTRL.sub("", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = "\n".join(line.strip() for line in s.split("\n"))
    return s.strip()[:limit]


def clean_int(value, lo: int, hi: int, default: int | None = None) -> int | None:
    try:
        n = int(str(value).strip().replace(",", "").replace(" ", ""))
    except (TypeError, ValueError):
        return default
    if n < lo or n > hi:
        return default
    return n


_PHONE_OK = re.compile(r"^\+?[0-9]{7,15}$")


def normalise_phone(value) -> str:
    """Accepts the ways a Kigali guest actually types a number and returns
    +2507XXXXXXXX, or "" if it is not plausible."""
    raw = re.sub(r"[^\d+]", "", str(value or ""))
    if not raw:
        return ""
    if raw.startswith("+250"):
        digits = raw[4:]
    elif raw.startswith("250"):
        digits = raw[3:]
    elif raw.startswith("0"):
        digits = raw[1:]
    elif raw.startswith("+"):
        return raw if _PHONE_OK.match(raw) else ""
    else:
        digits = raw
    if len(digits) == 9 and digits[0] == "7":
        return "+250" + digits
    return ""


def short_code() -> str:
    """4 characters a runner can read out. No 0/O/1/I confusion."""
    alphabet = "ACDEFGHJKLMNPQRTUVWXY34679"
    return "".join(secrets.choice(alphabet) for _ in range(4))


def public_code() -> str:
    return secrets.token_urlsafe(12)
