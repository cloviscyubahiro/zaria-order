# Zaria Court ordering system

Guests scan the QR code on their table, browse the kitchens, and send an order.
Nothing is charged in the app — they pay the runner when the food arrives.
Vendors keep their own menus current. Admin sees the money and the traffic.

Built on the Python standard library only. There is nothing to install and no
account to open anywhere.

---

## Running it

Double-click **`Start Zaria Ordering.bat`**, or from a terminal:

```
cd C:\Users\HP\zaria-order
python server.py --host 0.0.0.0 --port 8080
```

`--host 0.0.0.0` is what lets phones on the venue Wi-Fi reach it. The startup
banner prints the address to use. Without it the server is only reachable from
this computer, which is what you want while testing.

| Who | Address |
|---|---|
| Guests | `http://<address>:8080/` |
| Vendors | `http://<address>:8080/vendor` |
| Admin | `http://<address>:8080/admin` |

To also reach guests who are on their own mobile data rather than Zaria Wi-Fi,
use **`Start Zaria Ordering (public).bat`** instead — see *Reaching guests on
Wi-Fi and on their own data* below.

### First run

The first start creates the database, loads the current menus for all five
kitchens, creates 36 tables, and generates one-time passwords for every
account. They are printed to the console and saved to
`data/FIRST-RUN-PASSWORDS.txt`.

Hand those out in person, make each person change theirs at first sign-in, then
**delete that file**.

---

## Before a real event

1. **Admin → Settings → How guests get their order.** Set this for tonight:

   | Setting | Use it when | What the guest sees |
   |---|---|---|
   | **Seated** | Normal service, every guest at a table | Must give a table number |
   | **Mixed** | Some tables, some standing | Table is optional; blank means "I'll collect" |
   | **Standing** | Concert, no tables at all | No table question; a four-letter collection code instead |

   In Mixed and Standing, an order with no table shows on the kitchen screen as
   **Collect at counter** with the guest's code, so nobody goes looking for a
   table that does not exist.

2. **Admin → Tables & QR.** Type the codes for tonight (`A1-A20, VIP1-VIP6` —
   commas for a list, a dash for a range) and press **Replace all**. That
   clears last event's layout and sets exactly what you typed; **Add** keeps
   what is there. Past orders keep the table number they were placed with
   either way. In Standing mode you can leave the list empty.
3. **Admin → Settings → Public address used in QR codes.** Set this to the
   address guests will actually use *before* printing anything. QR codes encode
   this address; changing it later means reprinting.
4. **Each vendor signs in** and checks their prices, marks anything unavailable,
   and sets their MoMo code.
5. **Test one order end to end** — place it on a phone, accept it on the vendor
   tablet, mark it paid. Ten minutes now saves an hour on the night.

---

## Reaching guests on Wi-Fi *and* on their own data

Both work. They need different things from you.

A phone on Zaria Wi-Fi is on the same network as this computer, so it can open
the venue address directly. A phone on its own mobile data is not — for that one
to work, the system needs an address on the internet.

### Running it publicly

Double-click **`Start Zaria Ordering (public).bat`**. It starts the server in
public mode and opens a tunnel that gives it an `https://…` address. No router
changes, no port forwarding, no fixed IP, no cost.

One thing to install, once:

1. Download `cloudflared-windows-amd64.exe` from
   <https://github.com/cloudflare/cloudflared/releases/latest>
2. Rename it to `cloudflared.exe`
3. Put it in this folder, beside `server.py`

Then every time you run it:

1. Watch the tunnel window for an address ending in `trycloudflare.com`.
2. Paste it into **Admin → Settings → Public address**. QR codes are generated
   from this, so it must be set before printing.
3. Test it on a phone **with Wi-Fi switched off**. That is the only real proof.

The temporary address **changes every time the tunnel restarts**, which is fine
while nothing is printed. For a permanent address that survives restarts you
need a domain on a Cloudflare account and a named tunnel — worth doing before
you print QR codes, not before the trial.

To run it manually instead:

```
python server.py --host 0.0.0.0 --port 8080 --public
```

`--public` marks session cookies `Secure` and trusts the proxy's address header.
Only use it when a tunnel or reverse proxy is genuinely in front — without one,
anyone could spoof `X-Forwarded-For` and walk around the IP rate limits.

### What going public changes

| | Venue Wi-Fi only | With a public address |
|---|---|---|
| Guests on Zaria Wi-Fi | Work | Work |
| Guests on mobile data | **Cannot reach it** | Work |
| Traffic encrypted | No | Yes, by the tunnel |
| If venue internet drops | Keeps working | Ordering stops |
| Who can find the login pages | People in the building | Anyone — unless you limit it, below |

That fourth row is the real trade-off. The tunnel makes the venue's internet a
dependency it did not used to be. Keep the kiosks as the fallback.

### Lock the staff screens back to the building

Once there is a public address, the vendor and admin sign-in pages are on the
internet too. They do not need to be — kitchens and admin are in the building.

**Admin → Settings → Staff sign-in → Venue network only.** With it on, sign-in
works only from Zaria Wi-Fi using the venue address; from the public address
staff get a plain refusal, and any session opened from outside stops working.
Guests are never affected.

Turn it on **while you are on Zaria Wi-Fi** — the system will refuse to enable
it from the public address, because that would lock you out with the next click.
If you are ever locked out anyway, stop the tunnel and use the venue address.

### Does a guest's own network put the system at risk?

No, and a guest on cellular data is in the *safer* position of the two.

Their phone talks to the tunnel over `https://`, so their order is encrypted the
whole way. A guest on Zaria Wi-Fi opening the plain venue address is not
encrypted, and another guest on the same Wi-Fi could in principle watch it. Once
the public address is in use, everyone should be sent to it — including people
on Zaria Wi-Fi. Wi-Fi then just saves them data, and their traffic is encrypted
too.

A guest's network never gets them anything extra either way. It carries no
privileges: the order is priced by the server, the table code is signed, and the
staff API refuses a guest session whatever address it arrives from.

### Why the server is not exposed directly to the internet

When the tunnel is running, `cloudflared` holds the connection out to the
internet and passes requests to the Python server over `localhost`. The Python
server never accepts a connection from the internet itself. That matters,
because `http.server` is a standard-library server, not a hardened one — it is
fine behind something, and would not be a good idea in front.

Things the tunnel absorbs: raw internet noise, malformed connections, TLS, and
casual scanning. Things it does not: someone who has the address and behaves
like a real guest. Those are what the rate limits and the vendor Accept step
are for.

### Netlify and similar hosts will not work

Netlify, Vercel and GitHub Pages serve files. They cannot run a program or keep
a database, and this system is both — every order is priced, stored and moved
through its stages by code that has to be running somewhere.

Only two shapes work:

1. **This computer, with a tunnel** — what `Start Zaria Ordering (public).bat`
   does. Free, no account, the database stays in the building. The venue's
   internet has to be up.
2. **A small rented server** — a few dollars a month, always on, does not care
   whether the venue's internet is up. Worth it once the system is proven and
   you want the address never to change.

The old menus page could live on Netlify because it was only pictures and text.
This one cannot.

### One address can be a whole crowd

Worth knowing, because it caused a real bug worth explaining.

Every guest on Zaria Wi-Fi leaves through the venue's **one** public address.
Every guest on the same mobile network shares a small pool of addresses too
(carriers put many subscribers behind one). So once guests arrive from the
internet, an address stands for a crowd, not a person.

So the limits are sized by what an address actually represents:

| What | Limit | Why |
|---|---|---|
| One browser | 20 orders/hour | The limit that stops a prankster. It follows the phone onto any network. A table sharing one phone orders several rounds a night, so it has room. |
| One venue-network address | 60/hour | On the venue Wi-Fi an address really is one device. |
| One internet address | 400/hour, adjustable | Stands for the whole venue, or a whole mobile network. |

Both the phone limit and the crowd limit are in Admin → Settings and take effect
immediately, so raise them mid-event if real guests are ever told *"too many
orders"*.

**A kiosk PC is the exception.** It is one device placing orders for many
guests, so the per-guest limit would stop it. Open Admin *on that machine*,
Settings → Kiosks → **Register**. It then skips the limits. Blocks still apply,
and it must be registered from the machine itself — from the public address
every guest would inherit the exemption.

### Make joining the Wi-Fi one scan

Worth doing either way, because Wi-Fi is faster and free for the guest.

**Admin → Tables & QR → Venue Wi-Fi**: enter the network name and password, save,
and a QR appears. Scanning it joins the network on both iPhone and Android
without anyone typing a password. Print it beside the menu code:

```
   1. Scan to join Wi-Fi        2. Scan to see the menu
        [ Wi-Fi QR ]                 [ table QR ]
```

---

## How an order flows

```
Guest sends  ─►  PENDING  ─► vendor taps Accept ─►  ACCEPTED
                    │                                   │
                    └─ Reject ─► REJECTED               Ready
                                                          │
                                                        READY
                                                          │
                                                      Delivered
                                                          │
                                                      DELIVERED ─► Paid cash/MoMo ─► PAID
```

Two things worth knowing:

- **Nothing is cooked until a person taps Accept.** That step is the real
  protection in a pay-later model — it puts a human between a submitted order
  and a committed one.
- **A guest can withdraw only while the order is still PENDING.** Once a kitchen
  accepts, the withdraw button disappears.

---

## Daily use

**Vendors** — the *Orders* tab is the kitchen screen; it refreshes itself every
ten seconds. *Menu* is where prices and sold-out flags live. *Offers* runs a
percentage discount. *Notices* posts the one-line messages that scroll across
every guest's screen. *Shop* opens and closes the kitchen.

### Telling the kitchens something

Admin → Notices has **Who sees this**:

| Choice | Where it goes |
|---|---|
| **Guests** | Scrolls across every guest's screen, as before |
| **The kitchens** | A gold box above each kitchen's order queue. Guests never see it. |

Use the kitchens option to ask for something rather than announce it — *"concert
tonight, please post your offers"* — and each kitchen then posts its own offer,
which is the part guests see. It appears on their order screen within ten
seconds and on their Notices page, which is where they go to act on it.

A staff message is filtered out of the guest feed in the database query itself,
so it cannot reach a guest screen by any route.

A notice, an offer or a closed kitchen reaches guests who *already* have the
page open within about half a minute — they do not have to reload. That is what
makes running an offer mid-event worth doing.

**Admin** — *Overview* is the money and traffic picture, with a date range and a
CSV export. *Orders* is every ticket in the venue. *Tables & QR* prints the
codes. *Settings* holds the venue-wide emergency stop and the blocklist.

---

## If something goes wrong mid-event

| Problem | What to do |
|---|---|
| One phone is spamming orders | Admin → Settings → Blocked guests. Type the order code, block that phone. |
| A kitchen is overwhelmed | That vendor → Shop → turn off *Accept app orders*. Menu stays readable. |
| Something is badly wrong | Admin → Settings → turn off *Accept orders venue-wide*. |
| An item ran out | Vendor → Menu → *Sold out* on that row. Takes effect immediately. |
| Someone forgot their password | Admin → Vendors → *Reset password*. A new one-time password is shown once. |
| The tables got rearranged | Admin → Tables & QR → type the new codes → *Replace all*. Orders already placed keep their old table number. |
| More people are standing than sitting | Admin → Settings → switch to *Mixed*. Phones already on the page follow within about half a minute; nobody has to reload. |
| A guest cannot load the page | Ask whether they are on Wi-Fi or data. On data, they need the public address to be running — check the tunnel window. On Wi-Fi, the venue address. |
| Guests are told "too many orders from this network" | They are sharing an address with the whole venue. Admin → Settings → raise *Orders per hour from one internet address*. Immediate. |
| The venue internet drops | The tunnel dies; guests on mobile data are cut off. Guests on Zaria Wi-Fi still work at the venue address. Announce that address, or fall back to the kiosks. |

---

## Where things live

```
server.py                 start here
app/
  config.py               settings, limits, retention period
  db.py                   schema (SQLite, whole francs, no decimals)
  security.py             passwords, sessions, CSRF, signed tables, rate limits
  catalog.py              menu reads and discount arithmetic
  orders.py               checkout and the order lifecycle
  routes_public.py        what a guest's phone talks to
  routes_vendor.py        vendor console API
  routes_admin.py         admin API
  qr.py                   QR encoder (no third-party library)
  seed.py                 the menus, loaded once on first run
web/                      the three browser apps
data/
  zaria.db                everything. This is the file to back up.
  secret.key              signs sessions and table QR codes. Never share it.
```

**Back up `data/zaria.db` after every event.** Copying the file while the server
is stopped is enough.

Do not delete or regenerate `data/secret.key` — it would sign every guest out
and invalidate every printed QR code.

---

## How it copes with a crowd

Measured on the venue machine, not estimated:

| | Result |
|---|---|
| Sending an order, normal night | 38 ms |
| Opening the app | 18 ms |
| 120 guests ordering in the same instant | all 120 served, 43 orders/second, slowest wait 2.8 s |
| 200 phones sitting on the page while 40 orders come in | every order through, no dropped requests, 29 ms typical |
| Orders lost or double-counted under that load | none |

A big night at Zaria might peak at three or four orders a second. The system
handles about forty, so there is roughly ten times the headroom needed.

Two things were changed to get there. The standard library's server queues only
5 waiting connections by default — when a crowd taps at once, the rest are
refused before any code runs; that is now 256. And because each open page holds
a connection, idle ones are released after 15 seconds so a phone left open on a
table costs nothing between polls.

The limit is one computer and one database file. If ordering ever outgrows that,
the answer is a rented server, not a rewrite.

---

## Money

Prices are whole Rwandan francs in integer columns. There is no cents field and
no ×100 conversion anywhere, so a price cannot drift by a rounding error.

The browser never sends a price. It sends item ids and quantities; the server
looks up the current price and recomputes the total. A discount is applied
server-side at checkout and rounded to the nearest 100 RWF so the cash handover
stays quick.

---

## Personal data

Guests give a name so a runner can call them. **The phone number is optional** —
the table number, or the collection code, is what actually finds the guest, and
demanding a number to buy a plate reads as data collection rather than
hospitality. Guests who want a call can still leave one.

Whatever they give is scrubbed automatically 90 days after an order
(`PII_RETENTION_DAYS` in `app/config.py`); the money and item records stay for
reporting. Admin can run the scrub early from Settings.

IP addresses and device identifiers are never stored raw — only a keyed hash, so
a copy of the database does not hand over a list of visitors.

Rwanda's Law 058/2021 on personal data protection expects a stated purpose and
retention period. Both are shown to the guest at checkout and on the admin
settings page.

---

## A permanent public address

`Start Zaria Ordering (public).bat` gives a temporary address that changes on
every restart. That is fine until you print something. For an address that
stays put — `order.zariacourt.rw`, say — you need a domain on a Cloudflare
account and a **named** tunnel:

```
cloudflared tunnel login
cloudflared tunnel create zaria
cloudflared tunnel route dns zaria order.zariacourt.rw
cloudflared tunnel run --url http://localhost:8080 zaria
```

Then set that address in Admin → Settings and print the QR codes against it.

Any HTTPS reverse proxy works just as well — Caddy is the least configuration.
Whatever sits in front, run the server with `--public`, which sets both
`ZARIA_HTTPS=1` (cookies marked `Secure`) and `ZARIA_TRUST_PROXY=1` (the
proxy's address header is believed). Never set `ZARIA_TRUST_PROXY=1` without a
proxy actually in front: anyone could then spoof `X-Forwarded-For` and walk
around every IP rate limit.
