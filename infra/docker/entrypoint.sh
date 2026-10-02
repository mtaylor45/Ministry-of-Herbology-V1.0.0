#!/bin/sh
# The Ministry of Herbology — secret-file entrypoint. The deployment.
#
# anything that grants access is a Docker swarm secret, mounted as
# a file and read from disk. Environment variables carrying a credential leak
# into `docker service inspect`, into `docker inspect` on the task, into process
# listings and into crash reports; the *path* to a secret leaks nothing.
#
# So the stack sets MOH_<NAME>_FILE=/run/secrets/<something> and this script
# turns each one into MOH_<NAME> in the child process's environment immediately
# before exec. The service definition, which is what `inspect` prints, never
# holds a value.
#
# Two honest limits, both written down in docs/deploy/README.md:
#
#   * The value does end up in the child's own environment, so anything that
#     can already read /proc/1/environ inside this container can read it. That
#     is a much smaller blast radius than the service definition, but it is not
#     zero. Closing it needs pydantic-settings' `secrets_dir` in code this
#     parts of the project does not own — escalated to the maintainers.
#   * Trailing newlines are stripped. `openssl rand -base64 32 > secret.txt`
#     leaves one, and a password that silently gains a newline is a bad evening.
#     No other whitespace is touched.
#
# Only MOH_-prefixed names are scanned, so a value that happens to contain a
# line looking like `FOO_FILE=` cannot conjure a variable.

set -eu

for name in $(env | sed -n 's/^\(MOH_[A-Za-z0-9_]*\)_FILE=.*/\1/p'); do
    eval "path=\${${name}_FILE}"
    if [ ! -r "$path" ]; then
        echo "moh-entrypoint: \$${name}_FILE points at $path, which is not readable." >&2
        echo "moh-entrypoint: is the swarm secret attached to this service?" >&2
        exit 1
    fi
    # $(cat) strips trailing newlines, which is the behaviour we want here.
    value=$(cat "$path")
    if [ -z "$value" ]; then
        # A warning, not a failure. Swarm will not start a service that refers
        # to a secret which does not exist, so an operator with no Home
        # Assistant still has to create moh_ha_token — blank. Treating empty as
        # fatal made the documented way to deploy without Home Assistant a
        # crash loop, which is how this was found. Empty means "not
        # configured", and every setting that takes a credential already
        # understands that: workers.hub.settings.is_configured is exactly this
        # test.
        echo "moh-entrypoint: $name is empty ($path); treating it as unset." >&2
    fi
    export "$name=$value"
    unset "${name}_FILE"
done

# The database URL is assembled here rather than supplied whole, so that the
# password can be a secret while the host, port, user and database name stay
# ordinary configuration. Percent-encoding matters: a generated password is
# quite likely to contain a `/`, a `+` or an `@`, and any of the three turns a
# correct password into a connection to somewhere else.
if [ -z "${MOH_DATABASE_URL:-}" ] && [ -n "${MOH_DB_HOST:-}" ]; then
    MOH_DATABASE_URL=$(python3 - <<'PY'
import os
from urllib.parse import quote

driver = os.environ.get("MOH_DB_DRIVER", "postgresql+asyncpg")
user = quote(os.environ.get("MOH_DB_USER", "herbology"), safe="")
password = quote(os.environ.get("MOH_DB_PASSWORD", ""), safe="")
host = os.environ["MOH_DB_HOST"]
port = os.environ.get("MOH_DB_PORT", "5432")
name = quote(os.environ.get("MOH_DB_NAME", "herbology"), safe="")
credentials = f"{user}:{password}@" if password else f"{user}@"
print(f"{driver}://{credentials}{host}:{port}/{name}")
PY
)
    export MOH_DATABASE_URL
fi
# Assembled or not, the bare password has no further use in this process.
unset MOH_DB_PASSWORD || true

exec "$@"
