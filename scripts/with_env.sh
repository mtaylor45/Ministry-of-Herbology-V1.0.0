#!/bin/sh
# Run a command with an env file's variables exported. The deployment.
#
#   scripts/with_env.sh .env.deploy -- docker stack deploy -c ... moh
#
# Why not `set -a;. ./.env.deploy; set +a`, which is the usual trick: that
# hands the file to the shell as a *script*. The very first value this project
# asks an operator for breaks it —
#
#   MOH_NWS_USER_AGENT=ministry-of-herbology (you@example.net)
#
# is a syntax error, because the parentheses are shell syntax. The operator
# then has to know to quote it, and nothing tells them until the deploy fails
# with `Syntax error: "(" unexpected`, which names neither the file nor the
# line.
#
# It is also a quiet hazard: sourcing means any command substitution in the
# file runs, with whatever privileges the deploy has. An env file should be
# data.
#
# So this reads KEY=VALUE lines and nothing else. No expansion, no
# substitution, no quoting rules to learn. A `#` comment line and a blank line
# are skipped, a leading `export ` is tolerated, and one matched pair of
# surrounding quotes is stripped so that a file written either way works.

set -eu

[ $# -ge 1 ] || { echo "usage: $0 <env-file> [--] <command> [args...]" >&2; exit 2; }
env_file=$1
shift
[ "${1:-}" = "--" ] && shift
[ $# -ge 1 ] || { echo "$0: no command given" >&2; exit 2; }

if [ -f "$env_file" ]; then
    # `|| [ -n "$line" ]` so a final line with no trailing newline is not lost.
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            ''|'#'*) continue ;;
        esac
        line=${line#export }
        case "$line" in
            *=*) ;;
            *) continue ;;
        esac
        key=${line%%=*}
        value=${line#*=}
        # Trailing whitespace on the key is a typo, not a name.
        key=$(printf '%s' "$key" | tr -d ' \t')
        case "$key" in
            ''|*[!A-Za-z0-9_]*)
                echo "$0: ignoring line with an unusable name: $line" >&2
                continue ;;
        esac
        # One matched pair of surrounding quotes, so both styles of file work.
        case "$value" in
            \"*\") value=${value#\"}; value=${value%\"} ;;
            \'*\') value=${value#\'}; value=${value%\'} ;;
        esac
        export "$key=$value"
    done < "$env_file"
fi

exec "$@"
