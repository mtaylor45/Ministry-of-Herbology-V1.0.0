#!/bin/sh
# Which services of the stack are not where they should be, and why. The deployment.
#
#   scripts/stack_why.sh (MOH_STACK, default moh)
#
# Printed by `make stack-deploy` when the deploy does not converge in time and
# by CI when the app does not come up, so a hang ends as a sentence rather
# than a timeout: each service whose running replicas fall short, its last
# task errors, and the end of its log. Logs here are the services' own; the
# app writes no credential to them, and the feed-token paths are
# redacted at the source.
set -u
stack=${MOH_STACK:-moh}
lines=${MOH_WHY_LOG_LINES:-25}

docker service ls --filter "label=com.docker.stack.namespace=$stack" \
    --format '{{.Name}} {{.Replicas}}' | while read -r name replicas; do
    running=${replicas%%/*}
    wanted=${replicas#*/}
    wanted=${wanted%% *}
    [ "$running" = "$wanted" ] && continue
    echo
    echo "== $name: $replicas running"
    docker service ps "$name" --no-trunc \
        --format '  {{.CurrentState}}  {{.Error}}' 2>/dev/null | head -n 5
    echo "  -- last $lines log lines --"
    docker service logs --raw --tail "$lines" "$name" 2>&1 | sed 's/^/  /'
done
echo
docker service ls --filter "label=com.docker.stack.namespace=$stack" \
    --format 'table {{.Name}}\t{{.Replicas}}\t{{.Image}}'
