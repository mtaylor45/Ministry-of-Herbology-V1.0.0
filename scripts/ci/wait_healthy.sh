#!/bin/sh
# Wait for §8's two checks to pass, as the guide runs them. The deployment.
#
# The guide says "give it a minute or two" and then curls both; a job cannot
# eyeball `make stack-ps`, so this retries the guide's own two commands until
# they answer, and also waits for the web app, then gives up by name.
set -u
deadline=$(( $(date +%s) + ${MOH_WAIT_SECONDS:-300} ))
while :; do
    # Port 80, as the guide has it: Nginx answers /healthz itself only there,
    # where swarm's healthcheck asks; on 443 the path is the web app's.
    nginx=$(curl -s -o /dev/null -w '%{http_code}' http://localhost/healthz || true)
    api=$(curl -sk https://localhost/api/v1/healthz || true)
    web=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost/ || true)
    case "$api" in
        *'"live"'*) api_ok=yes ;;
        *) api_ok=no ;;
    esac
    if [ "$nginx" = 200 ] && [ "$api_ok" = yes ] && [ "$web" = 200 ]; then
        echo "nginx http /healthz 200; API $api; web app / 200"
        exit 0
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "Not healthy in ${MOH_WAIT_SECONDS:-300}s: nginx=$nginx web=$web api=$api" >&2
        "$(dirname "$0")/../stack_why.sh" >&2
        exit 1
    fi
    sleep 5
done
