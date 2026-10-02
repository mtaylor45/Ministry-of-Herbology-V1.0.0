#!/bin/sh
# Wait until every service of the stack runs what it should. The deployment.
#
#   scripts/stack_wait.sh (MOH_STACK, default moh; MOH_DEPLOY_TIMEOUT, default 600)
#
# `make stack-deploy` runs this after `docker stack deploy --detach`. It used
# to pass --detach=false and let the CLI wait, which clean-machine
# job hung twice: on a worker that crash-looped (fair enough, but it never
# said which), and on a stack that was entirely healthy, where the CLI's
# per-service wait sat on a service `docker service update --detach=false`
# reported converged in five seconds. This asks the one question that
# matters — does each service run as many tasks as it wants — and requires the
# answer three times running, five seconds apart, so a task that starts and
# dies is not counted as up, and while swarm reports a rolling update still in
# progress the service is not done. A paused update fails at once. Out of
# time, it says what is not running and why.
set -u
stack=${MOH_STACK:-moh}
deadline=$(( $(date +%s) + ${MOH_DEPLOY_TIMEOUT:-600} ))
steady=0
while :; do
    short=$(docker service ls --filter "label=com.docker.stack.namespace=$stack" \
        --format '{{.Name}} {{.Replicas}}' | while read -r name replicas; do
            running=${replicas%%/*}
            wanted=${replicas#*/}
            wanted=${wanted%% *}
            [ "$running" = "$wanted" ] || { echo "$name $replicas"; continue; }
            # On an update the old tasks still count above, so swarm's own
            # rollout state decides whether it has finished.
            state=$(docker service inspect "$name" \
                --format '{{if .UpdateStatus}}{{.UpdateStatus.State}}{{end}}' 2>/dev/null)
            case "$state" in
                updating|rollback_started) echo "$name $state" ;;
                paused|rollback_paused) echo "$name $state PAUSED" ;;
            esac
        done)
    case "$short" in
        *PAUSED*)
            echo "A rolling update stopped:"
            echo "$short" | sed 's/^/  /'
            MOH_STACK="$stack" "$(dirname "$0")/stack_why.sh"
            exit 1 ;;
    esac
    if [ -z "$short" ] && [ -n "$(docker service ls -q --filter "label=com.docker.stack.namespace=$stack")" ]; then
        steady=$((steady + 1))
        if [ "$steady" -ge 3 ]; then
            echo "Every service of $stack is running what it should."
            exit 0
        fi
    else
        steady=0
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "Not converged in ${MOH_DEPLOY_TIMEOUT:-600}s. Short of replicas:"
        echo "$short" | sed 's/^/  /'
        MOH_STACK="$stack" "$(dirname "$0")/stack_why.sh"
        exit 1
    fi
    sleep 5
done
