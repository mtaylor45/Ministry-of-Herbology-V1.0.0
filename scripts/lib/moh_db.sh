# shellcheck shell=sh
# Finding the database container, and talking to it. The deployment.
#
# Sourced by migrate.sh, backup.sh and restore.sh. Every one of them reaches
# the database the same way: `docker exec` into the running Postgres task.
#
# Why exec rather than a network connection from the host:
#
#   * No password. The official Postgres entrypoint writes `local all all trust`
#     into pg_hba.conf, so a connection over the container's own Unix socket
#     needs no credential. Everything arriving over TCP still faces
#     scram-sha-256. A backup script that never handles the database password
#     cannot leak it into a shell history, a cron log or a process listing.
#   * Matching versions. pg_dump refuses to dump a server newer than itself, and
#     a restore across TimescaleDB versions is its own adventure. The binaries
#     inside the container are the server's own, by construction.
#   * No published port. The stack keeps Postgres on an internal overlay network
#     with nothing bound to the host, and these scripts do not ask it to change.
#
# Configuration, all overridable from the environment:
#
#   MOH_STACK swarm stack name (default: moh)
#   MOH_DB_SERVICE the database service (default: ${MOH_STACK}_db)
#   MOH_DB_CONTAINER an explicit container id/name, skipping discovery
#   MOH_DB_USER database role (default: herbology)
#   MOH_DB_NAME database name (default: herbology)

MOH_STACK="${MOH_STACK:-moh}"
MOH_DB_SERVICE="${MOH_DB_SERVICE:-${MOH_STACK}_db}"
MOH_DB_USER="${MOH_DB_USER:-herbology}"
MOH_DB_NAME="${MOH_DB_NAME:-herbology}"

moh_die() {
    echo "$*" >&2
    exit 1
}

# Echoes the id of the container running Postgres, or explains why it cannot.
moh_db_container() {
    if [ -n "${MOH_DB_CONTAINER:-}" ]; then
        docker inspect --format '{{.Id}}' "$MOH_DB_CONTAINER" 2>/dev/null \
            || moh_die "No container called '$MOH_DB_CONTAINER'."
        return
    fi

    # A swarm task carries the service name as a label; a compose service
    # carries its own. Try both, so these scripts work against the production
    # stack and against `make dev` without being told which is which.
    for filter in \
        "label=com.docker.swarm.service.name=${MOH_DB_SERVICE}" \
        "label=com.docker.compose.service=db" \
        "name=${MOH_DB_SERVICE}"
    do
        id=$(docker ps --filter "$filter" --format '{{.ID}}' | head -n 1)
        [ -n "$id" ] && { echo "$id"; return; }
    done

    moh_die "Could not find a running container for the database service
'${MOH_DB_SERVICE}' on this node.

  * On a multi-node swarm the database task may be on another node. Find it
    with:  docker service ps ${MOH_DB_SERVICE}
    then run this script again on that node.
  * If your stack is not called '${MOH_STACK}', set MOH_STACK.
  * To point at one container directly, set MOH_DB_CONTAINER."
}

# psql inside that container, failing loudly on the first error.
moh_psql() {
    docker exec -i "$MOH_DB_CID" \
        psql -v ON_ERROR_STOP=1 -U "$MOH_DB_USER" -d "$MOH_DB_NAME" "$@"
}

# sha256sum on Linux, shasum on macOS. Echoes the bare hex digest.
moh_sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d' ' -f1
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | cut -d' ' -f1
    else
        moh_die "Need sha256sum or shasum to checksum $1."
    fi
}

# psql inside that container, against a database other than MOH_DB_NAME.
# Creating and dropping a database cannot be done from inside it.
moh_psql_db() {
    db=$1
    shift
    docker exec -i "$MOH_DB_CID" \
        psql -v ON_ERROR_STOP=1 -U "$MOH_DB_USER" -d "$db" "$@"
}
