"""The Arq bootstrap every worker shares.

live in four parts of the project' directories (D, E, F, K) and every one of them needs
the same answer to the same question: which Redis?

Why this exists at all: until the deployment deployed the stack and watched the
workers fall over, no ``WorkerSettings`` declared ``redis_settings``. Arq
therefore used its own default of ``localhost:6379``, every worker exited with
``ConnectionError: Error 111``, and a deployment did no background work — no
weather ingest, no taxon resolution, no Home Assistant polling, no plates.
``MOH_REDIS_URL`` was documented, set by the dev compose and set by the swarm
stack, and nothing read it.

Nothing caught it because the unit tests call the task functions directly and
never boot Arq, and because the *enqueue* side in ``api/inventory/enrichment.py``
reads the URL correctly — so jobs arrived in the right Redis and simply nobody
drained them. ``tests/test_worker_bootstrap.py`` is the guard now.

The metaclass is load-bearing rather than clever. Arq reads ``redis_settings``
as an attribute of the settings class, but importing a worker module must not
require Arq to be installed: the API and the scenario suite import
``workers/weather/tasks.py`` for its engines, and E deliberately kept Arq out of
that path. A property on the metaclass is read like a plain class attribute and
runs only when something actually asks — which is Arq, at worker startup.
"""

from __future__ import annotations

import os
from typing import Any

#: The queue each worker drains. Botany keeps Arq's own default
#: queue because the API's enrichment enqueue (``api/inventory/enrichment.py``)
#: has always sent there; the other three had been sharing it, so a cron job one
#: worker enqueued was as likely to be picked up — and dropped as "function not
#: found" — by another. Each now has its own.
ARQ_DEFAULT_QUEUE = "arq:queue"
QUEUES: dict[str, str] = {
    "botany": ARQ_DEFAULT_QUEUE,
    "weather": "moh:queue:weather",
    "hub": "moh:queue:hub",
    "plates": "moh:queue:plates",
}


def queue_for(worker: str) -> str:
    """The queue to enqueue onto for ``worker`` ("botany", "weather", ...)."""
    return QUEUES[worker]


#: Arq's own default, and what the four workers were silently using.
DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def redis_url() -> str:
    """The configured Redis, read at the moment it is needed.

    Read from the environment rather than from a worker's settings object
    because there are four of those, one of them does not exist, and they
    would all say the same thing.
    """
    return os.environ.get("MOH_REDIS_URL") or DEFAULT_REDIS_URL


class ArqBootstrap(type):
    """Gives a ``WorkerSettings`` class a lazily-resolved ``redis_settings`` and
    its own ``queue_name``.

    ``queue_name`` is put in the class's own namespace because that is the only
    place Arq looks: ``arq.worker.get_kwargs`` reads ``settings_cls.__dict__``
    and nothing else. That is also why ``redis_settings`` — a property here, so
    that importing a worker module never needs Redis configured — is invisible
    to the ``arq`` CLI, and why the worker image starts through
    ``infra/docker/run_worker.py``, which reads it with ``getattr`` and passes
    it explicitly (B, an earlier release; the earlier version of this module relied on the CLI and
    never worked). ``tests/test_worker_bootstrap.py`` now asserts on what
    ``get_kwargs`` actually returns.
    """

    def __new__(mcs, name: str, bases: tuple[type, ...], namespace: dict[str, Any]):
        module = namespace.get("__module__", "")
        parts = module.split(".")
        if len(parts) >= 2 and parts[0] == "workers" and parts[1] in QUEUES:
            namespace.setdefault("queue_name", QUEUES[parts[1]])
        return super().__new__(mcs, name, bases, namespace)

    @property
    def redis_settings(cls) -> Any:
        from arq.connections import RedisSettings

        return RedisSettings.from_dsn(redis_url())
