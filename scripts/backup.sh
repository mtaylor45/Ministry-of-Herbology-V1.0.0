#!/bin/sh
# Take a backup of the live database. The deployment.
#
#   scripts/backup.sh write to ./backups/
#   scripts/backup.sh --out /srv/backups write somewhere else
#   scripts/backup.sh --to-stdout > dump stream it, e.g. into a pipe
#
# Format. `pg_dump -Fc` — the custom format — because it compresses, and
# because pg_restore can then reorder, filter and parallelise on the way back
# in. A plain SQL dump cannot do any of that, and with TimescaleDB it matters:
# the restore has to create hypertables before their data arrives.
#
# TimescaleDB. `timescaledb_pre_restore()` and `timescaledb_post_restore()`
# bracket the restore, not the dump, so they live in restore.sh. What the dump
# does need is the whole database including the _timescaledb_catalog schema,
# which a default pg_dump already covers.
#
# The continuous aggregates (reading_hourly, reading_daily, weather_daily) are
# materialised hypertables, so their contents come along in the dump. They are
# also derivable from `reading` and `weather_obs`, so a restore that lost them
# would only be slow to catch up, not wrong.
#
# What this deliberately does not do: encrypt, rotate, or copy the file
# anywhere. A backup on the same disk as the database is not a backup; getting
# it off this machine is the operator's job and docs/deploy/README.md says so.

set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=scripts/lib/moh_db.sh
. "$SCRIPT_DIR/lib/moh_db.sh"

OUT_DIR="${MOH_BACKUP_DIR:-$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)/backups}"
TO_STDOUT=no

while [ $# -gt 0 ]; do
    case "$1" in
        --out)       [ $# -ge 2 ] || moh_die "--out needs a directory."
                     OUT_DIR=$2; shift 2 ;;
        --to-stdout) TO_STDOUT=yes; shift ;;
        -h|--help)   sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)           moh_die "Unknown option: $1" ;;
    esac
done

MOH_DB_CID=$(moh_db_container)
export MOH_DB_CID

# Nothing here about ownership or dropping objects: for an archive format those
# are pg_restore's decisions, not pg_dump's, and pg_dump silently ignores them.
# restore.sh passes them at the other end, where they take effect.
dump() {
    docker exec -i "$MOH_DB_CID" \
        pg_dump -U "$MOH_DB_USER" -d "$MOH_DB_NAME" \
            --format=custom --compress=9
}

if [ "$TO_STDOUT" = "yes" ]; then
    dump
    exit 0
fi

mkdir -p "$OUT_DIR"
stamp=$(date -u '+%Y%m%dT%H%M%SZ')
target="$OUT_DIR/moh-${MOH_DB_NAME}-${stamp}.dump"

# Write to a partial name first. A backup interrupted halfway must not be left
# sitting there with a plausible filename, waiting to be restored one bad day.
dump > "$target.partial"
mv "$target.partial" "$target"

size=$(wc -c < "$target" | tr -d ' ')
echo "$target"
echo "${size} bytes"
echo
echo "Not a backup yet: it is on the same machine as the database. Copy it"
echo "somewhere else, then prove it by restoring into a scratch database:"
echo "  scripts/restore.sh --from '$target' --into moh_restore_check"
