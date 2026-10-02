#!/bin/sh
# Restore a backup, and prove it. The deployment.
#
#   scripts/restore.sh --from backups/moh-herbology-....dump --into moh_restore_check
#   scripts/restore.sh --from backups/moh-herbology-....dump --into herbology --force
#
# The first form is the drill: restore into a scratch database beside the live
# one, count what came back, then drop it. Nothing in production is touched, so
# there is no excuse for never having done it. The second form is the real
# thing, and it overwrites a database, which is why it needs --force.
#
# TimescaleDB restores are not plain Postgres restores. The extension keeps its
# own catalog, and its triggers will fight a restore that inserts into
# hypertables behind its back. So:
#
#   1. CREATE EXTENSION timescaledb in the empty target, *before* the restore.
#      pg_restore will find it already there and carry on.
#   2. SELECT timescaledb_pre_restore() — puts the database in restoring mode
#      and stops the background workers. It works by ALTER DATABASE, so it
#      takes effect for connections opened afterwards; that is why these are
#      three separate psql sessions rather than one.
#   3. pg_restore.
#   4. SELECT timescaledb_post_restore() — restarts the workers and puts the
#      policies back. Skipping this leaves a database that looks fine and
#      quietly never refreshes a continuous aggregate again.

set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=scripts/lib/moh_db.sh
. "$SCRIPT_DIR/lib/moh_db.sh"

FROM=''
INTO=''
FORCE=no
KEEP=no

while [ $# -gt 0 ]; do
    case "$1" in
        --from)  [ $# -ge 2 ] || moh_die "--from needs a dump file."
                 FROM=$2; shift 2 ;;
        --into)  [ $# -ge 2 ] || moh_die "--into needs a database name."
                 INTO=$2; shift 2 ;;
        --force) FORCE=yes; shift ;;
        --keep)  KEEP=yes; shift ;;
        -h|--help) sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)       moh_die "Unknown option: $1" ;;
    esac
done

[ -n "$FROM" ] || moh_die "Need --from <dump file>. Try --help."
[ -r "$FROM" ] || moh_die "Cannot read $FROM."
INTO=${INTO:-${MOH_DB_NAME}_restore_check}

MOH_DB_CID=$(moh_db_container)
export MOH_DB_CID

exists=$(moh_psql_db postgres -tAc \
    "SELECT count(*) FROM pg_database WHERE datname = '$INTO'")

if [ "$exists" != "0" ]; then
    if [ "$FORCE" != "yes" ]; then
        moh_die "Database '$INTO' already exists.

Restoring into it would replace what is there. If that is what you mean, pass
--force. If you wanted the drill, pick a name that does not exist yet:
  scripts/restore.sh --from '$FROM' --into ${MOH_DB_NAME}_restore_check"
    fi
    echo "dropping and recreating $INTO"
    # Sessions on the target keep DROP DATABASE waiting forever, and the API
    # and workers hold pooled connections. Ending them is the point of --force.
    moh_psql_db postgres -q -c \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
         WHERE datname = '$INTO' AND pid <> pg_backend_pid()" -o /dev/null
    moh_psql_db postgres -q -c "DROP DATABASE \"$INTO\""
fi

echo "creating $INTO"
moh_psql_db postgres -q -c "CREATE DATABASE \"$INTO\""

echo "preparing TimescaleDB"
moh_psql_db "$INTO" -q -c "CREATE EXTENSION IF NOT EXISTS timescaledb" -o /dev/null
moh_psql_db "$INTO" -q -c "SELECT timescaledb_pre_restore()" -o /dev/null

echo "restoring from $FROM"
# --no-owner and --no-privileges so the dump lands under whatever role this
# installation uses; the operator who restores is rarely the one who dumped.
# pg_restore reads the archive from stdin when given no filename.
restore_status=0
docker exec -i "$MOH_DB_CID" \
    pg_restore --no-owner --no-privileges --dbname "$INTO" \
        --username "$MOH_DB_USER" < "$FROM" || restore_status=$?

echo "finishing TimescaleDB"
moh_psql_db "$INTO" -q -c "SELECT timescaledb_post_restore()" -o /dev/null

echo
echo "Restored into '$INTO'. What came back:"
moh_psql_db "$INTO" -c "
SELECT 'specimen'    AS relation, count(*) FROM specimen
UNION ALL SELECT 'site',          count(*) FROM site
UNION ALL SELECT 'reading',       count(*) FROM reading
UNION ALL SELECT 'weather_obs',   count(*) FROM weather_obs
UNION ALL SELECT 'task',          count(*) FROM task
ORDER BY relation"

# The three things a restore silently loses if post_restore is skipped, or if
# the extension was not in place before pg_restore ran. Counting rows alone
# would not catch any of them: the data comes back and the machinery does not.
echo
echo "And the TimescaleDB machinery:"
moh_psql_db "$INTO" -c "
SELECT 'hypertables'           AS thing, count(*) FROM timescaledb_information.hypertables
UNION ALL
SELECT 'continuous aggregates', count(*) FROM timescaledb_information.continuous_aggregates
UNION ALL
SELECT 'background jobs',       count(*) FROM timescaledb_information.jobs
ORDER BY thing"
echo "Against the schema as it stands: 3 hypertables, 3 continuous aggregates,"
echo "and at least 4 jobs (three refresh policies and one retention policy)."

if [ "$restore_status" != "0" ]; then
    echo
    echo "pg_restore exited $restore_status. It reports a non-zero status for"
    echo "warnings as well as failures, so read what it printed above before"
    echo "deciding: counts that look right usually mean the warnings were"
    echo "about objects the dump could not own, which is expected here."
fi

if [ "$KEEP" != "yes" ] && [ "$INTO" != "$MOH_DB_NAME" ]; then
    echo
    echo "Dropping the scratch database. Pass --keep to look around in it first."
    moh_psql_db postgres -q -c "DROP DATABASE \"$INTO\""
fi
