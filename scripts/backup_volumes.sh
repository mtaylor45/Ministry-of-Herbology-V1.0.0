#!/bin/sh
# Archive the volumes that hold pictures rather than rows. The deployment.
#
#   scripts/backup_volumes.sh write to ./backups/
#   scripts/backup_volumes.sh --out /srv/backups write somewhere else
#   scripts/backup_volumes.sh --volume moh_plates-images one volume, by full name
#
# `pg_dump` knows nothing about three of the stack's volumes, and a restore
# that brings back the database without them is a map whose layers all 404,
# a book with no plates and a growth log with no photographs — which is what
# the contract says that looks like. So
# `make backup` runs this after backup.sh:
#
#   <stack>_grounds-images plans and surveys (MOH_GROUNDS_IMAGE_DIR)
#   <stack>_plates-images the Journal's plates (MOH_PLATES_IMAGE_DIR)
#   <stack>_photos-images household photographs (MOH_PHOTOS_IMAGE_DIR)
#
# Each becomes one tar.gz, written through a throwaway alpine container that
# mounts the volume read-only; nothing runs inside the stack and nothing is
# stopped. The archive keeps numeric ownership, so a restore puts the files
# back owned by the `herbology` user the images run as.
#
# Written to a .partial name and renamed on completion, like the dump: an
# archive interrupted halfway must not sit there looking restorable.
#
# Same honest limit as backup.sh: a file on the same disk as the volume is
# not a backup. Copy it somewhere else.
#
#   MOH_STACK swarm stack (or compose project) name default: moh
#   MOH_VOLUMES short names to archive, space separated default: the three above
#   MOH_BACKUP_DIR where to write default: ./backups

set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=scripts/lib/moh_db.sh
. "$SCRIPT_DIR/lib/moh_db.sh"

OUT_DIR="${MOH_BACKUP_DIR:-$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)/backups}"
VOLUMES=""
ONLY=""

while [ $# -gt 0 ]; do
    case "$1" in
        --out)     [ $# -ge 2 ] || moh_die "--out needs a directory."
                   OUT_DIR=$2; shift 2 ;;
        --volume)  [ $# -ge 2 ] || moh_die "--volume needs a volume name."
                   ONLY=$2; shift 2 ;;
        -h|--help) sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)         moh_die "Unknown option: $1" ;;
    esac
done

if [ -n "$ONLY" ]; then
    VOLUMES=$ONLY
else
    for short in ${MOH_VOLUMES:-grounds-images plates-images photos-images}; do
        VOLUMES="$VOLUMES ${MOH_STACK}_${short}"
    done
fi

mkdir -p "$OUT_DIR"
# tar inside the container writes as root; the directory has to be reachable
# by absolute path for the bind mount.
OUT_DIR=$(CDPATH='' cd -- "$OUT_DIR" && pwd)
stamp=$(date -u '+%Y%m%dT%H%M%SZ')

for volume in $VOLUMES; do
    docker volume inspect "$volume" >/dev/null 2>&1 || moh_die "No volume called '$volume'.

  * docker volume ls --filter name=${MOH_STACK}_   lists what the stack has.
  * A stack deployed before the image volumes existed gains them on its next
    \`make stack-deploy\`; until then there is nothing to archive.
  * If your stack is not called '${MOH_STACK}', set MOH_STACK."

    target="$OUT_DIR/$volume-$stamp.tar.gz"
    docker run --rm \
        -v "$volume:/data:ro" \
        -v "$OUT_DIR:/out" \
        alpine:3 \
        tar czf "/out/$(basename "$target").partial" -C /data .
    mv "$target.partial" "$target"
    size=$(wc -c < "$target" | tr -d ' ')
    echo "$target"
    echo "${size} bytes"
done

echo
echo "Not a backup yet: these are on the same machine as the volumes. Copy them"
echo "somewhere else with the database dump. To put one back:"
echo "  scripts/restore_volume.sh --from <archive> --into <volume>"
