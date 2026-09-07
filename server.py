"""Zaria Court ordering system — entry point.

    python server.py                 # http://localhost:8080
    python server.py --port 9000
    python server.py --host 0.0.0.0  # reachable from phones on the same Wi-Fi

Standard library only. No pip install, ever.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import config, db, orders, security                      # noqa: E402
from app import routes_admin, routes_public, routes_vendor        # noqa: E402
from app.web import (HttpError, Request, Response, Router,        # noqa: E402
                     SECURITY_HEADERS, json_response, serve_static)

PAGES = {
    "/": "index.html",
    "/order": "index.html",
    "/vendor": "vendor.html",
    "/admin": "admin.html",
    "/kitchen": "vendor.html",
}


def build_router() -> Router:
    r = Router()
    for sub in (routes_public.router, routes_vendor.router, routes_admin.router):
        r.routes.extend(sub.routes)
    return r


ROUTER = build_router()


class EventServer(ThreadingHTTPServer):
    """Sized for a crowd arriving at once.

    The stdlib default listen backlog is 5. When an MC says "order from your
    table now" and two hundred phones connect in the same few seconds, the
    operating system holds pending connections in that queue -- at 5, the rest
    are refused before any Python code runs, and the guest sees a dead page.
    """
    request_queue_size = 256
    daemon_threads = True
    # Do not wait for in-flight connections when shutting down; a keep-alive
    # connection can sit idle for its full timeout and stall a Ctrl+C.
    block_on_close = False
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    server_version = "ZariaOrder"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # HTTP/1.1 keeps a connection open after the response, and this server uses
    # one thread per connection. Without a timeout, every phone with the page
    # open holds a thread for as long as it lingers. The guest page polls every
    # 25s, so releasing after 15s of silence means an idle phone costs nothing
    # between polls and only pays one reconnect.
    timeout = 15

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (TimeoutError, socket.timeout):
            self.close_connection = True

    def _send(self, resp: Response):
        body = resp.body
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in SECURITY_HEADERS:
            self.send_header(k, v)
        for k, v in resp.headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _handle(self):
        try:
            req = Request(self)
        except Exception:
            self._send(Response(400, b"Bad request"))
            return

        try:
            # 1. API and other registered routes
            resp = ROUTER.dispatch(req)
            if resp is not None:
                self._send(resp)
                return

            # 2. App pages
            page = PAGES.get(req.path)
            if page:
                static = serve_static(page)
                if static:
                    self._send(static)
                    return

            # 3. Static assets
            static = serve_static(req.path)
            if static:
                self._send(static)
                return

            if req.path.startswith("/api/"):
                self._send(json_response({"error": "Not found."}, 404))
            else:
                self._send(Response(404, b"Not found."))

        except HttpError as e:
            payload = {"error": e.message}
            if e.field:
                payload["field"] = e.field
            self._send(json_response(payload, e.status))
        except BrokenPipeError:
            pass
        except Exception:
            # Log the detail server-side; never leak a traceback to a guest.
            traceback.print_exc()
            self._send(json_response(
                {"error": "Something went wrong on our side. Please try again."}, 500))

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _handle

    def log_message(self, fmt, *args):
        if os.environ.get("ZARIA_QUIET") == "1":
            return
        sys.stderr.write("%s  %s\n" % (time.strftime("%H:%M:%S"), fmt % args))


def housekeeping():
    """Hourly: expire sessions, trim rate-limit rows, scrub stale personal data."""
    while True:
        time.sleep(3600)
        try:
            security.purge_sessions()
            security.purge_rate_limits()
            purged = orders.purge_old_pii()
            if purged:
                print(f"[housekeeping] scrubbed personal data from {purged} old order(s)")
        except Exception:
            traceback.print_exc()


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser(description="Zaria Court ordering system")
    # A rented host tells the program where to listen through the environment
    # rather than the command line, and every one of them uses these names. The
    # flags still win, so nothing changes for the venue laptop.
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"),
                    help="use 0.0.0.0 to accept phones on the same network")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--public", action="store_true",
                    default=os.environ.get("ZARIA_PUBLIC") == "1",
                    help="running behind an HTTPS tunnel or reverse proxy")
    args = ap.parse_args()

    if args.public:
        # These three belong together and are easy to get half-right by hand.
        # Trusting X-Forwarded-For without a proxy in front lets anyone spoof
        # their address past every rate limit, so it is only ever set here,
        # where a proxy has been declared.
        os.environ["ZARIA_HTTPS"] = "1"
        os.environ["ZARIA_TRUST_PROXY"] = "1"

    db.init()
    from app import seed
    seed.ensure_seeded()

    threading.Thread(target=housekeeping, daemon=True).start()

    httpd = EventServer((args.host, args.port), Handler)

    shown = lan_ip() if args.host == "0.0.0.0" else args.host
    print("\n  Zaria Court ordering system")
    print("  " + "-" * 46)
    print(f"  Guests   http://{shown}:{args.port}/")
    print(f"  Vendors  http://{shown}:{args.port}/vendor")
    print(f"  Admin    http://{shown}:{args.port}/admin")
    if args.host != "0.0.0.0":
        print("\n  Only this computer can reach it. For phones on the venue")
        print("  Wi-Fi, restart with:  python server.py --host 0.0.0.0")

    if args.public:
        base = db.setting("public_base_url", "")
        print("\n  Public mode: cookies marked Secure, proxy address header trusted.")
        print(f"  Public address  {base or '(not set -- Admin > Settings)'}")
        if db.setting("staff_network", "ANY") == "LAN_ONLY":
            print("  Staff consoles  venue network only")
        else:
            print("  Staff consoles  reachable from the internet")
            print("                  Admin > Settings to limit them to the venue.")
        print("\n  Start the tunnel in a second window, then check that the public")
        print("  address opens on a phone with Wi-Fi turned off.")

    print("\n  Ctrl+C to stop.\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
