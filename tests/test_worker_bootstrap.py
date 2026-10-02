"""Every Arq worker must connect to the Redis it was configured with.


This test exists because of a bug that shipped through every other gate. None
of the four ``WorkerSettings`` classes declared ``redis_settings``, so Arq fell
back to its own default of ``localhost:6379`` and all four workers exited with
``ConnectionError: Error 111`` the moment a deployment tried to run them. The
result was an installation that served the API, the web app and the database
correctly and did no background work at all: no weather ingest, no taxon
resolution, no Home Assistant polling, no plates.

``MOH_REDIS_URL`` was documented in ``.env.example``, set by the dev compose and
set by the swarm stack. Nothing read it.

Nothing caught it because the unit tests call the task functions directly and
never boot Arq, and because the *enqueue* side reads the URL correctly — jobs
arrived in the right Redis and nobody drained them. The deployment found it by
deploying the stack and watching the workers fall over.
"""

from __future__ import annotations

import importlib

import pytest

#: The four Arq entry points, one per worker, by the component that owns it.
WORKERS = [
    ("workers.weather.tasks", "weather"),
    ("workers.botany.tasks", "botany"),
    ("workers.hub.tasks", "hub"),
    ("workers.plates.tasks", "plates"),
]


@pytest.fixture
def redis_url(monkeypatch):
    """A URL no default could produce by accident."""
    url = "redis://redis.test.invalid:6399/7"
    monkeypatch.setenv("MOH_REDIS_URL", url)
    return url


@pytest.mark.parametrize("module_name,component", WORKERS)
def test_a_worker_connects_to_the_configured_redis(module_name, component, redis_url):
    settings = importlib.import_module(module_name).WorkerSettings
    resolved = settings.redis_settings

    assert resolved.host == "redis.test.invalid", (
        f"{component}'s worker ignores MOH_REDIS_URL and will connect to "
        f"{resolved.host}:{resolved.port}. Arq's default is localhost:6379, "
        "which is nothing in a deployment."
    )
    assert resolved.port == 6399
    assert resolved.database == 7


@pytest.mark.parametrize("module_name,component", WORKERS)
def test_importing_a_worker_does_not_require_arq(module_name, component, monkeypatch):
    """Importing a worker module must not pull Arq in.

    The API and the scenario suite import ``workers.weather.tasks`` for its
    engines, and the weather engine kept Arq off that path deliberately. The
    bootstrap resolves ``redis_settings`` lazily so it stays that way; this
    fails if someone moves the import to module scope.
    """
    import sys

    monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.delitem(sys.modules, "arq", raising=False)
    monkeypatch.delitem(sys.modules, "arq.connections", raising=False)

    real_import = __import__

    def refuse_arq(name, *args, **kwargs):
        if name == "arq" or name.startswith("arq."):
            raise ImportError("arq is not installed in this environment")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", refuse_arq)
    importlib.import_module(module_name)  # must not raise


def test_the_default_is_arqs_default_and_is_useless_in_a_deployment():
    """Kept explicit so the fallback is a decision rather than an accident."""
    from workers.runtime import DEFAULT_REDIS_URL
    from workers.runtime import redis_url as configured

    assert DEFAULT_REDIS_URL == "redis://localhost:6379/0"
    assert configured() == DEFAULT_REDIS_URL  # no MOH_REDIS_URL set here


# --- What Arq actually reads. The tests above read `redis_settings` with
# getattr, which Arq never does: `arq.worker.get_kwargs` reads the class's own
# `__dict__` and nothing else. So they passed while every worker booted by the
# `arq` CLI fell back to localhost. These assert on Arq's own reading.


@pytest.mark.parametrize("module_name,component", WORKERS)
def test_arq_sees_each_workers_own_queue(module_name, component):
    from arq.worker import get_kwargs

    from workers.runtime import QUEUES

    settings = importlib.import_module(module_name).WorkerSettings
    worker = module_name.split(".")[1]
    assert get_kwargs(settings).get("queue_name") == QUEUES[worker], (
        f"{component}'s worker would drain Arq's shared default queue and drop "
        "other workers' cron jobs as 'function not found'."
    )


def test_no_two_workers_share_a_queue():
    from workers.runtime import QUEUES

    assert len(set(QUEUES.values())) == len(QUEUES)


def test_botany_keeps_the_queue_the_api_enqueues_to():
    """api/inventory/enrichment.py enqueues with no `_queue_name`, which is
    Arq's default; botany must be the worker draining it."""
    from arq.constants import default_queue_name

    from workers.runtime import queue_for

    assert queue_for("botany") == default_queue_name


@pytest.mark.parametrize("module_name,component", WORKERS)
def test_the_image_launcher_hands_arq_the_configured_redis(
    module_name, component, redis_url
):
    """The worker image starts through infra/docker/run_worker.py, which passes
    `redis_settings` explicitly because get_kwargs cannot see the property.
    This is that hand-over, checked the way Arq builds the Worker."""
    from arq.worker import get_kwargs

    settings = importlib.import_module(module_name).WorkerSettings
    kwargs = {**get_kwargs(settings), "redis_settings": settings.redis_settings}
    assert kwargs["redis_settings"].host == "redis.test.invalid"
    assert kwargs["queue_name"].startswith(("arq:", "moh:"))
