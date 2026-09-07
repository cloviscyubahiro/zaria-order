#!/bin/sh
# Nightly backup of the one file that matters.
#
#   sudo cp deploy/backup.sh /opt/zaria-order/backup.sh
#   sudo chmod +x /opt/zaria-order/backup.sh
#   sudo crontab -e     ->     15 4 * * * /opt/zaria-order/backup.sh
#
# sqlite3's .backup is used rather than cp because the database is live: copying
# the file while a write is in flight can capture a torn page, and the copy that
# looks fine tonight is the one that will not open the morning you need it.
set -eu

DIR=/opt/zaria-order/data
OUT=/opt/zaria-order/backups
KEEP=30

mkdir -p "$OUT"
STAMP=$(date +%Y-%m-%d_%H%M)
sqlite3 "$DIR/zaria.db" ".backup '$OUT/zaria-$STAMP.db'"

# A backup nobody has opened is a hope, not a backup.
sqlite3 "$OUT/zaria-$STAMP.db" "PRAGMA integrity_check;" | grep -q '^ok$' || {
	echo "backup $STAMP FAILED integrity check" >&2
	exit 1
}

gzip -f "$OUT/zaria-$STAMP.db"
ls -1t "$OUT"/zaria-*.db.gz | tail -n +$((KEEP + 1)) | xargs -r rm --

echo "zaria-$STAMP.db.gz ok"
