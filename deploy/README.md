# Putting it on a server

The goal is three addresses that work from any network — Zaria Wi-Fi, a boss's
home Wi-Fi, a phone on mobile data — and that keep working when the venue
laptop is closed.

| Console | Address | Who gets the link |
|---|---|---|
| Guests | `order.zariacourt.rw` | printed on the table QR codes |
| Kitchens | `vendor.zariacourt.rw` | the four vendor accounts |
| Owner | `admin.zariacourt.rw` | you |

They are three separate sites. Ask the guest address for `/admin` and it
answers exactly as it would for a page that does not exist. Behind them it is
one program over one database, because it has to be: an order placed on the
guest site has to appear on a kitchen screen a second later.

---

## What you have to buy

Two things, and nothing else. Neither can be avoided if the links are to work
with the laptop shut.

| | Roughly | Why |
|---|---|---|
| A small server | **$4–6 / month** | Something has to be running to price orders and hold the database. Hetzner CX22, DigitalOcean, Vultr and Linode are all fine; the smallest size is far more than this needs. |
| A domain | **$10–15 / year** | Three subdomains come free with it. Without one you would be handing people a bare IP address, which cannot have HTTPS and looks like nothing anyone should type a password into. |

That is about **$70 in the first year**. There is no per-order cost and no
payment-provider fee, because no money moves through the software.

**Why not free hosting.** Netlify, Vercel and GitHub Pages serve files. They
cannot run a program or keep a database, and this is both. Render's free tier
wipes its disk on every deploy, which means it wipes the orders. A free tier
that sleeps when idle is worse than useless here — the kitchen screen would go
blank between rushes.

---

## Installing it

About an hour, once. Everything below is on the server, over SSH.

**1. A user and the files.** The system needs Python 3 and nothing else — no
`pip install`, ever, so there is no virtualenv to build and nothing to go stale.

```sh
sudo adduser --system --group --home /opt/zaria-order zaria
sudo git clone <your repo> /opt/zaria-order
sudo chown -R zaria:zaria /opt/zaria-order
```

**2. Point the domain at it.** Three A records, all to this server's IP:

```
order    A    <server IP>
vendor   A    <server IP>
admin    A    <server IP>
```

Wait until `dig +short order.zariacourt.rw` answers before going on. Caddy
cannot get a certificate for a name that does not resolve yet.

**3. Caddy, for HTTPS.**

```sh
sudo apt install -y caddy
sudo cp /opt/zaria-order/deploy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile          # put your real domain in
sudo systemctl reload caddy
```

Certificates are obtained and renewed automatically. Nothing to buy, nothing
to diarise.

**4. The service.**

```sh
sudo cp /opt/zaria-order/deploy/zaria.service /etc/systemd/system/
sudo nano /etc/systemd/system/zaria.service   # the three host names
sudo systemctl daemon-reload
sudo systemctl enable --now zaria
systemctl status zaria
```

`Restart=always` brings it back if it ever stops, and `enable` brings it back
after a reboot.

**5. Close everything else.**

```sh
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw enable
```

The Python server listens on `127.0.0.1` only, so Caddy is the sole way in.

**6. First run.** Open `https://admin.zariacourt.rw`. The first start creates
the database, loads the menus and writes one-time passwords to
`data/FIRST-RUN-PASSWORDS.txt`. Hand them out in person, make everyone change
theirs, then delete that file.

**7. The address the QR codes carry.** Admin → Settings → *Public address* →
`https://order.zariacourt.rw`. **Set this before printing anything.** QR codes
encode it, so changing it later means reprinting every table.

**8. Backups.**

```sh
sudo cp /opt/zaria-order/deploy/backup.sh /opt/zaria-order/
sudo chmod +x /opt/zaria-order/backup.sh
sudo crontab -e        # 15 4 * * * /opt/zaria-order/backup.sh
```

Then, once, actually restore one somewhere else and open it. A backup nobody
has opened is a hope, not a backup.

---

## Moving tonight's data up

If the laptop has orders worth keeping, stop both sides first — copying a live
SQLite file can capture a half-written page.

```sh
# on the laptop
python -c "import sqlite3;s=sqlite3.connect(r'data/zaria.db');d=sqlite3.connect('move.db');
with d: s.backup(d)"
scp move.db zaria@<server>:/tmp/

# on the server
sudo systemctl stop zaria
sudo -u zaria cp /tmp/move.db /opt/zaria-order/data/zaria.db
sudo systemctl start zaria
```

Take `data/secret.key` too, or leave it behind deliberately — it signs sessions
and every printed table QR code. Keeping it means printed codes stay valid;
replacing it means they all have to be reprinted.

---

## After it is up

| Want | Do |
|---|---|
| Update the code | `git pull` then `sudo systemctl restart zaria` |
| See what it is doing | `journalctl -u zaria -f` |
| Lock the owner's console to your own connection | Uncomment the `remote_ip` lines in the Caddyfile |
| Stop ordering venue-wide | Admin → Settings |

**Keep the laptop set-up working.** `Start Zaria Ordering.bat` still runs the
whole system on the venue network with no internet at all. If the venue's line
goes down mid-event, that is the fallback — and it is the reason the kiosks are
worth keeping.
