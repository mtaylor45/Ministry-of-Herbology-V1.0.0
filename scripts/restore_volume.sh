#!/bin/sh
# Put an archived volume back. The deployment.
#
#   scripts/restore_volume.sh --from backups/moh_plates-images-....tar.gz --into moh_plates-images
#   scripts/restore_volume.sh --from ... --into moh_plates-images --force
#
# The counterpart of backup_volumes.sh: unpacks one archive into one named
# volume through a throwaway alpine container. The volume is created if it
# does not exist. A volume that already has files in it is refused unless
# --force, which empties it first — a restore layered over a half-broken
# directory is neither the backup nor the present, and nobody can say which
# picture came from where.
#
# Scale the services that mount the volume to 0 before a --force restore and
# back afterwards; docs/deploy/README.md §13 gives the two lines. The API
# serves a picture the moment it is on disk, so a restore under a running API
# is not dangerous, only confusing for whoever is looking at the map meanwhile.
#
# Nothing here touches the database. The rows that point at these files come
# back with scripts/restore.sh, and the two have to be from the same backup
# or the map has layers with no picture and pictures with no layer.

set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=scripts/lib/moh_db.sh
. "$SCRIPT_DIR/lib/moh_db.sh"

FROM=''
INTO=''
FORCE=no

while [ $# -gt 0 ]; do
    case "$1" in
        --from)  [ $# -ge 2 ] || moh_die "--from needs an archive."
                 FROM=$2; shift 2 ;;
        --into)  [ $# -ge 2 ] || moh_die "--into needs a volume name."
                 INTO=$2; shift 2 ;;
        --force) FORCE=yes; shift ;;
        -h|--help) sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)       moh_die "Unknown option: $1" ;;
    esac
done

[ -n "$FROM" ] || moh_die "Need --from <archive>. Try --help."
[ -r "$FROM" ] || moh_die "Cannot read $FROM."
[ -n "$INTO" ] || moh_die "Need --into <volume>, e.g. ${MOH_STACK}_plates-images."

from_dir=$(CDPATH='' cd -- "$(dirname -- "$FROM")" && pwd)
from_name=$(basename -- "$FROM")

if docker volume inspect "$INTO" >/dev/null 2>&1; then
    # Anything at all in it, dotfiles included.
    count=$(docker run --rm -v "$INTO:/data:ro" alpine:3 \
        sh -c 'find /data -mindepth 1 | head -n 1 | wc -l' | tr -d ' ')
    if [ "$count" != "0" ]; then
        [ "$FORCE" = "yes" ] || moh_die "Volume '$INTO' is not empty.

Restoring into it would mix what is there with what is in the archive. If
you mean to replace the contents, pass --force, which empties it first.
Scale the services that mount it to 0 before you do; README §13."
        echo "emptying $INTO"
        docker run --rm -v "$INTO:/data" alpine:3 \
            sh -c 'find /data -mindepth 1 -delete'
    fi
else
    echo "creating $INTO"
    docker volume create "$INTO" >/dev/null
fi

echo "restoring $from_name into $INTO"
docker run --rm \
    -v "$INTO:/data" \
    -v "$from_dir:/in:ro" \
    alpine:3 \
    tar xzf "/in/$from_name" -C /data

files=$(docker run --rm -v "$INTO:/data:ro" alpine:3 \
    sh -c 'find /data -type f | wc -l' | tr -d ' ')
echo "$INTO now holds $files file(s)."
echo "The rows that point at them come from scripts/restore.sh, from the same backup."
