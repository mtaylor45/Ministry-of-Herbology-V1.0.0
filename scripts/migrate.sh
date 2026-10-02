#!/bin/sh
# Apply pending schema migrations to a live database. The deployment.
#
#   scripts/migrate.sh status what has run, what has not
#   scripts/migrate.sh apply run everything pending, in order
#   scripts/migrate.sh apply --dry-run say what apply would do
#   scripts/migrate.sh baseline record every file as applied
#   scripts/migrate.sh baseline --through 003 record files up to 003 as applied
#
# Why this exists. The dev compose mounts contracts/schema/ into
# /docker-entrypoint-initdb.d, which the Postgres image runs *only when the data
# directory is empty*. That is a fine way to create a database and no way at all
# to upgrade one: on the second and every later start it is silently skipped, so
# a new migration file never reaches a database that already has data in it.
# the design asks for a real upgrade path, and this is it.
#
# `contracts/` is frozen and belongs to the maintainers; this script only reads it.
#
# The ledger lives in its own schema, moh_deploy, so that it is unmistakably
# operational bookkeeping rather than part of the frozen contract.
#
# Atomicity. Each file is applied inside one transaction, together with the
# ledger row that records it, so a migration either lands completely and is
# recorded or does neither. A file whose first 20 lines contain the marker
#
#     -- moh:no-transaction
#
# is applied without that wrapper, for the DDL Postgres refuses to run inside a
# transaction block (CREATE INDEX CONCURRENTLY, a continuous aggregate built
# WITH DATA, ALTER TYPE ... ADD VALUE on older servers). Such a file is recorded
# after the fact, and this script says so at the time, because a failure partway
# through one of those leaves the database in a state only a human can judge.
# None of the migrations in the tree today needs it.

set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)
SCHEMA_DIR="${MOH_SCHEMA_DIR:-$REPO_ROOT/contracts/schema}"

# shellcheck source=scripts/lib/moh_db.sh
. "$SCRIPT_DIR/lib/moh_db.sh"

usage() {
    sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

LEDGER_DDL="
-- The IF NOT EXISTS clauses below are the normal case, and their notices
-- would otherwise head every single run.
SET client_min_messages = warning;
CREATE SCHEMA IF NOT EXISTS moh_deploy;
COMMENT ON SCHEMA moh_deploy IS
    'Deployment bookkeeping. Not part of the frozen contract.';
CREATE TABLE IF NOT EXISTS moh_deploy.schema_migration (
    filename    text PRIMARY KEY,
    sha256      text        NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now(),
    applied_by  text        NOT NULL DEFAULT current_user
);
COMMENT ON TABLE moh_deploy.schema_migration IS
    'One row per file in contracts/schema/ that has been applied here.';
"

migration_files() {
    # Numbered, forward-only, applied in filename order. `sort` on a zero-padded
    # three-digit prefix is the same as sorting on the number.
    find "$SCHEMA_DIR" -maxdepth 1 -name '[0-9][0-9][0-9]_*.sql' | sort
}

is_applied() {
    [ "$(moh_psql -tAc "SELECT count(*) FROM moh_deploy.schema_migration
                        WHERE filename = '$1'")" != "0" ]
}

recorded_sha() {
    moh_psql -tAc "SELECT sha256 FROM moh_deploy.schema_migration
                   WHERE filename = '$1'"
}

wants_no_transaction() {
    head -n 20 "$1" | grep -q '^-- moh:no-transaction'
}

record_sql() {
    printf "INSERT INTO moh_deploy.schema_migration (filename, sha256)
            VALUES ('%s', '%s');\n" "$1" "$2"
}

cmd_status() {
    moh_psql -q <<SQL
$LEDGER_DDL
SQL
    printf '%-34s %-9s %s\n' 'MIGRATION' 'STATE' 'APPLIED AT'
    pending=0
    changed=0
    for path in $(migration_files); do
        name=$(basename "$path")
        sha=$(moh_sha256 "$path")
        if is_applied "$name"; then
            was=$(recorded_sha "$name")
            at=$(moh_psql -tAc "SELECT applied_at FROM moh_deploy.schema_migration
                                WHERE filename = '$name'")
            if [ "$was" = "$sha" ]; then
                printf '%-34s %-9s %s\n' "$name" 'applied' "$at"
            else
                # Forward-only means an applied file never changes again. If one
                # has, the database and the repository disagree about what ran,
                # and no tool can work out which is right.
                printf '%-34s %-9s %s\n' "$name" 'CHANGED' "$at (applied $was)"
                changed=$((changed + 1))
            fi
        else
            printf '%-34s %-9s %s\n' "$name" 'pending' '-'
            pending=$((pending + 1))
        fi
    done
    echo
    if [ "$changed" -gt 0 ]; then
        echo "$changed applied migration(s) no longer match the file on disk."
        echo "contracts/schema/ is forward-only, so this should be impossible;"
        echo "apply will refuse to run until you have worked out which is wrong."
    fi
    if [ "$pending" -eq 0 ]; then
        [ "$changed" -eq 0 ] && echo "Up to date."
    else
        echo "$pending migration(s) pending. Run: scripts/migrate.sh apply"
    fi
}

cmd_apply() {
    dry_run=${1:-no}
    moh_psql -q <<SQL
$LEDGER_DDL
SQL
    applied=0
    for path in $(migration_files); do
        name=$(basename "$path")
        sha=$(moh_sha256 "$path")

        if is_applied "$name"; then
            was=$(recorded_sha "$name")
            [ "$was" = "$sha" ] && continue
            moh_die "$name has already been applied here, but its contents have
changed since (recorded $was, on disk $sha).

contracts/schema/ is forward-only: an applied file is never edited. Work out
which of the two is wrong before going any further — this script will not
guess, and re-running the file is very unlikely to be the right answer."
        fi

        if [ "$dry_run" = "yes" ]; then
            echo "would apply $name"
            applied=$((applied + 1))
            continue
        fi

        if wants_no_transaction "$path"; then
            echo "applying $name (outside a transaction, at its own request)"
            if ! moh_psql -q -o /dev/null < "$path"; then
                moh_die "$name failed, and it asked not to be wrapped in a
transaction, so some of it may have landed. Nothing has been recorded as
applied. Inspect the database before re-running: this file is not safe to
simply try again."
            fi
            # Recorded separately, so a failure above leaves it pending and a
            # human decides what half-landed. Hence the marker being rare.
            record_sql "$name" "$sha" | moh_psql -q
        else
            echo "applying $name"
            # The migration and its ledger row commit together or not at all.
            if ! { cat "$path"; record_sql "$name" "$sha"; } \
                    | moh_psql -q -o /dev/null --single-transaction; then
                moh_die "$name failed and was rolled back in full; the error
psql printed above is the one to read. Nothing was applied and nothing was
recorded, so fixing the cause and re-running apply is safe."
            fi
        fi
        applied=$((applied + 1))
    done

    if [ "$applied" -eq 0 ]; then
        echo "Nothing to do; the database is up to date."
    elif [ "$dry_run" = "yes" ]; then
        echo "$applied migration(s) would be applied."
    else
        echo "$applied migration(s) applied."
    fi
}

cmd_baseline() {
    through=${1:-}
    moh_psql -q <<SQL
$LEDGER_DDL
SQL
    marked=0
    for path in $(migration_files); do
        name=$(basename "$path")
        if [ -n "$through" ]; then
            # Compare the numeric prefixes, with leading zeros stripped so that
            # no shell is tempted to read 008 as octal.
            this=$(printf '%s' "${name%%_*}" | sed 's/^0*//;s/^$/0/')
            last=$(printf '%s' "${through%%_*}" | sed 's/^0*//;s/^$/0/')
            [ "$this" -le "$last" ] || continue
        fi
        is_applied "$name" && continue
        record_sql "$name" "$(moh_sha256 "$path")" | moh_psql -q
        echo "recorded $name as already applied"
        marked=$((marked + 1))
    done
    echo "$marked migration(s) recorded without being run."
    if [ "$marked" -gt 0 ]; then
        echo
        echo "Nothing was executed. Only do this against a database whose schema"
        echo "already matches those files — typically one the dev compose built"
        echo "from docker-entrypoint-initdb.d before this ledger existed."
    fi
}

[ $# -ge 1 ] || usage 1
command=$1
shift

MOH_DB_CID=$(moh_db_container)
export MOH_DB_CID

case "$command" in
    status)
        cmd_status
        ;;
    apply)
        case "${1:-}" in
            --dry-run) cmd_apply yes ;;
            '')        cmd_apply no ;;
            *)         moh_die "Unknown option for apply: $1" ;;
        esac
        ;;
    baseline)
        case "${1:-}" in
            --through) [ $# -ge 2 ] || moh_die "--through needs a prefix, e.g. 003"
                       cmd_baseline "$2" ;;
            '')        cmd_baseline ;;
            *)         moh_die "Unknown option for baseline: $1" ;;
        esac
        ;;
    -h|--help|help)
        usage 0
        ;;
    *)
        echo "Unknown command: $command" >&2
        usage 1
        ;;
esac
