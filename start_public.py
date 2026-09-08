"""Bring up the ordering system with three public links, and print them.

    python start_public.py

Starts the server if it is not already running, opens one tunnel per console,
writes the three addresses into the database, then checks each link actually
answers before printing it.

Run it again any time the links stop working. Free Cloudflare "quick" tunnels
drop their connection on their own and cannot get the same address back, so
re-running gives three NEW links -- which is exactly why nothing should be
printed against them. A permanent address needs a domain and a server; see
deploy/README.md.

Standard library only, like the rest of the system.
"""
from __future__ import annotations

import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "zaria.db")
CF = os.path.join(BASE, "cloudflared.exe")
LOGS = os.path.join(BASE, "data", "tunnels")
PORT = 8080

CONSOLES = [
    ("guest",  "host_guest",  "Guests   (goes on the table QR codes)"),
    ("vendor", "host_vendor", "Vendors  (the four kitchens)"),
    ("admin",  "host_admin",  "Admin    (you)"),
]

URL_RE = re.compile(rb"https://[a-z0-9-]+\.trycloudflare\.com")

# Windows: start a process that keeps running after this script exits.
DETACHED = 0x00000008 | 0x00000200 if os.name == "nt" else 0


def listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", port)) == 0


def spawn(args, log_path):
    log = open(log_path, "wb")
    return subprocess.Popen(args, stdout=log, stderr=log, cwd=BASE,
                            creationflags=DETACHED, close_fds=True)


def kill_stale_tunnels():
    if os.name != "nt":
        return
    subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"],
                   capture_output=True)


def start_server():
    if listening(PORT):
        print(f"  server            already running on :{PORT}")
        return
    print(f"  server            starting on :{PORT} ...", end="", flush=True)
    spawn([sys.executable, "server.py", "--host", "0.0.0.0",
           "--port", str(PORT), "--public"],
          os.path.join(BASE, "data", "server.log"))
    for _ in range(40):
        if listening(PORT):
            print(" up")
            return
        time.sleep(0.5)
    print(" FAILED")
    sys.exit("The server did not start. Check data/server.log")


def start_tunnel(name: str) -> str | None:
    log_path = os.path.join(LOGS, f"{name}.log")
    open(log_path, "wb").close()
    spawn([CF, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{PORT}"],
          log_path)
    for _ in range(90):
        time.sleep(1)
        try:
            with open(log_path, "rb") as f:
                m = URL_RE.search(f.read())
            if m:
                return m.group(0).decode()
        except OSError:
            pass
    return None


def save(pairs: dict[str, str], guest_url: str):
    conn = sqlite3.connect(DB)
    with conn:
        for key, host in pairs.items():
            conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, host))
        # The address the table QR codes encode.
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('public_base_url',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (guest_url,))
    conn.close()


def answers(url: str, path: str = "/") -> bool:
    req = urllib.request.Request(url + path, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def main():
    if not os.path.exists(CF):
        sys.exit("cloudflared.exe is missing from this folder.")
    os.makedirs(LOGS, exist_ok=True)

    print("\n  Zaria Court -- public links")
    print("  " + "-" * 58)

    start_server()
    print("  old tunnels       clearing ...")
    kill_stale_tunnels()
    time.sleep(2)

    urls: dict[str, str] = {}
    for name, _key, _label in CONSOLES:
        print(f"  {name + ' tunnel':<18}opening ...", end="", flush=True)
        url = start_tunnel(name)
        if not url:
            print(" FAILED")
            sys.exit(f"Could not get an address for the {name} console. "
                     "Check your internet, then run this again.")
        urls[name] = url
        print(f" {url}")

    save({key: urls[name].replace("https://", "")
          for name, key, _ in CONSOLES}, urls["guest"])

    print("\n  checking each link from the outside ...")
    time.sleep(4)
    bad = []
    for name, _key, _label in CONSOLES:
        ok = any(answers(urls[name]) for _ in range(3))
        print(f"    {'OK  ' if ok else 'FAIL'} {name:<8} {urls[name]}")
        if not ok:
            bad.append(name)

    print("\n  " + "=" * 58)
    for name, _key, label in CONSOLES:
        print(f"  {label}\n    {urls[name]}\n")
    print("  " + "=" * 58)

    if bad:
        print(f"\n  {', '.join(bad)} did not answer yet. Tunnels sometimes need")
        print("  another few seconds -- try the link in a browser before re-running.")

    print("\n  Keep this computer awake and online. These links live on it.")
    print("  They change every time this script runs, so do not print them.")
    print("  For links that survive a shut laptop, see deploy/README.md.\n")


if __name__ == "__main__":
    main()
