#!/bin/sh
# `docker stack rm` returns before the containers are gone, and a volume in use
# cannot be removed. Wait until nothing of the stack is left. The deployment.
set -u
stack=${MOH_STACK:-moh}
deadline=$(( $(date +%s) + 180 ))
while [ -n "$(docker ps -aq --filter "label=com.docker.stack.namespace=$stack")" ] \
   || [ -n "$(docker network ls -q --filter "label=com.docker.stack.namespace=$stack")" ]; do
    [ "$(date +%s)" -lt "$deadline" ] || { echo "stack $stack still has containers" >&2; exit 1; }
    sleep 2
done
# Exited task containers hold their volumes too; they are the stack's, and gone.
docker container prune -f >/dev/null
echo "stack $stack is gone"
