"""Start one Arq worker, with the Redis the deployment configured. The deployment.

    WORKER_MODULE=workers.weather.tasks python /srv/run_worker.py

This is ``arq workers.<x>.tasks.WorkerSettings`` with one difference, and the
difference is the point. Arq builds a worker from ``settings_cls.__dict__``
(``arq.worker.get_kwargs``), and the four ``WorkerSettings`` classes get
``redis_settings`` from a property on their metaclass (``workers/runtime.py``),
which a class's ``__dict__`` never contains. So the CLI dropped it, every
worker fell back to Arq's default of localhost:6379 and exited with
``ConnectionError: Error 111``, swarm restarted it, and a deployment did no
background work at all — no weather, no taxon resolution, no hub, no plates.

CI's clean-machine job found it: ``make stack-deploy`` waits for every
service to converge, four never did, and the job sat in §8 until it timed out.

Here the attribute is read with ``getattr``, which runs the property, and
handed to Arq as an explicit keyword, which Arq lets override the settings
class. Logging is configured as the CLI configures it.
"""

from __future__ import annotations

import logging.config
import os
import sys


def main() -> None:
    from arq.logs import default_log_config
    from arq.utils import import_string
    from arq.worker import run_worker

    module = os.environ.get("WORKER_MODULE")
    if not module:
        sys.exit(
            "WORKER_MODULE is not set: workers.weather.tasks, workers.hub.tasks, ..."
        )
    settings = import_string(f"{module}.WorkerSettings")
    logging.config.dictConfig(default_log_config(verbose=False))
    run_worker(settings, redis_settings=settings.redis_settings)


if __name__ == "__main__":
    main()
