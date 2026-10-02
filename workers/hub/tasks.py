"""Home & IoT worker — the hub.

The Home Assistant adapter and the MQTT publish-back, as Arq jobs.

## What this file is responsible for

The releases's exit criterion is **indoor and outdoor readings stored every 5–15
minutes**. The weather engine landed the outdoor half; :func:`poll_home_assistant` is
the indoor half, and it is the *only* route to indoor
conditions — there is no direct Nest integration and none is planned. If this
job stops, nothing else fills in behind it.

That makes one failure worse than being wrong: **being silent**. A job that
stops running leaves the last readings in place, the Almanac draws a line
through the gap, and a household sees a chart that looks like a steady 21 °C
room. So every run here leaves a mark whether it worked or not —
``integration.last_ok_at`` and ``integration.last_error`` for the current
state, ``job_run`` for the history — and every entity that was asked for and
did not produce a reading is *named* in the job's return value, with a reason.
Nothing is dropped quietly.

## Shape

Every job returns a plain dict rather than writing and staying silent, so a
run's outcome is visible in Arq's result store and in a test with no database
— the same rule the weather engine's jobs follow, and for the same reason: a job
that can only be observed by querying Postgres is a job nobody checks.

Where ``ctx`` carries a ``connection``, rows are persisted through
:mod:`workers.hub.store`; where it does not — mock mode, and every test — the
job still does the work and reports it.

## Cadence

``poll_home_assistant`` is scheduled every five minutes, the fast end of the
releases's 5–15 minute band, and each ``sensor_source`` then decides for itself
whether it is due via its own ``poll_seconds``. A thermostat is not a soil
probe: the cron sets the *finest* cadence available, the row sets the one it
wants.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, ClassVar

from workers.runtime import ArqBootstrap

from .entities import SOIL_METRICS, SUPPORTED_METRICS  # noqa: F401
from .health import IntegrationHealth, SourceHealth, health_report, redact
from .mapping import SensorSource, pollable, validation_errors
from .mqtt import (  # noqa: F401 — the topic layout is contract, re-exported
    DISCOVERY_PREFIX,
    MQTT_PREFIX,
    MemoryPublisher,
    availability,
    discovery_messages,
    discovery_topic,
    frost_messages,
    object_id_for,
    publish_all,
    rounds_messages,
    specimen_messages,
    state_topic,
)
from .notify.jobs import (
    notify_frost,
    notify_integration_health,
    notify_rounds,
)
from .settings import HubSettings, get_settings
from .sources.base import HOME_ASSISTANT, HubUnavailable, PollResult

#: The ``integration`` row this worker keeps. ``kind`` is from the schema's
#: CHECK constraint; ``name`` is what the Ministry Office prints.
HA_INTEGRATION = (HOME_ASSISTANT, "Home Assistant")
MQTT_INTEGRATION = ("mqtt", "MQTT broker")


def _settings(ctx: dict[str, Any]) -> HubSettings:
    settings = ctx.get("settings")
    return settings if isinstance(settings, HubSettings) else get_settings()


def _secrets(settings: HubSettings) -> tuple[str, ...]:
    """The values :func:`~workers.hub.health.redact` must remove literally."""
    return tuple(
        value
        for value in (
            settings.ha_token.get_secret_value(),
            settings.mqtt_password.get_secret_value(),
        )
        if value
    )


async def _sources_for(ctx: dict[str, Any]) -> list[SensorSource]:
    """The configured sources: from ``ctx``, then the database, then the mock.

    The ``ctx`` override exists for the API, which may already hold them, and
    for tests. Everything else is the ordinary path.
    """
    provided = ctx.get("sources")
    if provided is not None:
        return [
            item if isinstance(item, SensorSource) else SensorSource.from_row(item)
            for item in provided
        ]
    connection = ctx.get("connection")
    if connection is not None:
        from . import store

        rows = await store.read_sensor_sources(connection)
        return [SensorSource.from_row(dict(row)) for row in rows]
    from . import world

    return world.sensor_sources(_settings(ctx))


async def poll_home_assistant(
    ctx: dict[str, Any], source_id: str | None = None
) -> dict[str, Any]:
    """Read every due sensor source and store what came back.

    ``source_id`` polls one row regardless of whether it is due — what the
    "test this sensor" button in the Ministry Office needs, and what someone
    debugging a mapping wants.

    The return value is the whole story of the run: what was polled, what was
    stored, and every entity that was asked for and did not answer, with a
    reason each. That list is the point of this job as much as the readings
    are.
    """
    from . import store
    from .factory import get_source

    settings = _settings(ctx)
    started_at = datetime.now(UTC)
    secrets = _secrets(settings)

    sources = await _sources_for(ctx)
    problems: list[str] = []
    for source in sources:
        problems.extend(validation_errors(source))

    candidates = pollable(sources)
    if source_id:
        due = [source for source in candidates if source.id == source_id]
        if not due:
            return _report(
                started_at,
                ok=False,
                error=f"no enabled Home Assistant source with id {source_id}",
                sources=len(sources),
            )
    else:
        due = [source for source in candidates if source.is_due(started_at)]

    if not due:
        # Not an error and not a success: nothing was asked of Home Assistant,
        # so nothing was learned about it. Stamping `last_ok_at` here would
        # make a deployment with every source disabled look healthy forever.
        return _report(
            started_at,
            ok=True,
            sources=len(sources),
            polled=0,
            skipped_sources=[source.name for source in candidates],
            problems=problems,
            note="no source was due",
        )

    source_api = ctx.get("source") or get_source()
    result: PollResult = await source_api.poll(due, now=started_at)

    connection = ctx.get("connection")
    stored = 0
    if connection is not None and result.readings:
        stored = await store.write_readings(connection, result.readings)
        touched = sorted({reading.time.date() for reading in result.readings})
        await store.refresh_aggregates(connection, touched[0], touched[-1])

    error = _error_for(result, due, problems, secrets)
    finished_at = datetime.now(UTC)
    # The report and the ``job_run`` row carry the *redacted* error, not the
    # fetcher's own. ``PollResult.error`` is whatever Home Assistant or httpx
    # said, and both can quote a URL somebody put credentials in.
    detail = {**result.to_dict(), "error": error, "ok": result.ok and not error}
    if connection is not None:
        kind, name = HA_INTEGRATION
        if result.ok:
            await store.record_ok(connection, kind, name, finished_at)
        if error:
            await store.record_error(connection, kind, name, error)
        await store.record_job_run(
            connection,
            "poll_home_assistant",
            started_at=started_at,
            finished_at=finished_at,
            ok=result.ok and not error,
            detail=detail,
        )

    return _report(
        started_at,
        ok=result.ok and not error,
        error=error,
        sources=len(sources),
        polled=len(due),
        stored=stored,
        problems=problems,
        finished_at=finished_at,
        # ``ok`` and ``error`` are decided above, over the whole run rather
        # than over the fetch alone: a hub that answered and produced nothing
        # is a failure the fetch does not know about.
        **{k: v for k, v in detail.items() if k not in {"ok", "error"}},
    )


def _error_for(
    result: PollResult,
    due: list[SensorSource],
    problems: list[str],
    secrets: tuple[str, ...],
) -> str | None:
    """What belongs on ``integration.last_error`` after this run.

    Three cases, in order of how much they tell an operator:

    1. Home Assistant could not be reached — say that, and nothing else.
    2. It answered and **not one** mapped entity produced a reading. That is
       a working hub and a broken configuration, and it is the case that would
       otherwise pass as success: the job ran, no exception was raised, and
       the hypertable stayed empty.
    3. Some entities were refused, or a row is misconfigured. Named, because a
       partly-working mapping is the one people never get round to fixing.

    The result is always redacted. This string is rendered in the Ministry
    Office, and a Home Assistant error can quote a URL somebody put
    credentials in.
    """
    if result.error:
        return redact(result.error, secrets)
    reasons: list[str] = list(problems)
    if due and not result.readings:
        detail = ", ".join(
            sorted({f"{item.entity_id}: {item.reason}" for item in result.skipped})
        )
        reasons.insert(
            0,
            "Home Assistant answered, but no mapped entity produced a reading"
            + (f" ({detail})" if detail else ""),
        )
    elif result.skipped:
        detail = ", ".join(
            sorted({f"{item.entity_id}: {item.reason}" for item in result.skipped})
        )
        reasons.append(f"some entities produced no reading ({detail})")
    return redact("; ".join(reasons), secrets) if reasons else None


async def check_home_assistant(ctx: dict[str, Any]) -> dict[str, Any]:
    """Ask Home Assistant whether it is there, and record the answer.

    Separate from the poll on purpose. A deployment with no sources configured
    yet still needs the Ministry Office to say whether the hub is reachable —
    that is the screen someone looks at *while* setting it up, and a health
    check that only runs when there is something to poll is a health check
    that is absent exactly when it is wanted.
    """
    from . import store
    from .factory import get_source

    settings = _settings(ctx)
    started_at = datetime.now(UTC)
    source_api = ctx.get("source") or get_source()
    connection = ctx.get("connection")
    kind, name = HA_INTEGRATION

    if not settings.is_configured and not settings.mock_mode:
        return {
            "job": "check_home_assistant",
            "ok": False,
            "status": "unconfigured",
            "error": "MOH_HA_BASE_URL and MOH_HA_TOKEN are not set",
        }

    try:
        message = await source_api.probe()
    except HubUnavailable as exc:
        error = redact(str(exc), _secrets(settings)) or str(exc)
        if connection is not None:
            await store.record_error(connection, kind, name, error)
        return {
            "job": "check_home_assistant",
            "ok": False,
            "status": "down",
            "error": error,
        }

    finished_at = datetime.now(UTC)
    if connection is not None:
        await store.record_ok(connection, kind, name, finished_at)
    return {
        "job": "check_home_assistant",
        "ok": True,
        "status": "ok",
        "message": message,
        "took_ms": round((finished_at - started_at).total_seconds() * 1000, 1),
        "is_mock": getattr(source_api.fetcher, "is_mock", False),
    }


async def hub_health(ctx: dict[str, Any]) -> dict[str, Any]:
    """What the Ministry Office screen shows: is the hub actually answering?

    The report distinguishes four things a single "is it up" boolean cannot:
    an integration nobody has configured, one that is configured and failing,
    one that has not been *heard from* — no error, no recent success, which is
    what a stopped worker looks like — and a source that is configured, fine
    as far as the hub is concerned, and has not produced a reading in hours.
    """
    from . import store, world

    settings = _settings(ctx)
    now = datetime.now(UTC)
    connection = ctx.get("connection")

    if connection is not None:
        rows = await store.read_integrations(connection)
        integrations = [IntegrationHealth.from_row(dict(row)) for row in rows]
    else:
        integrations = world.integrations(settings)

    sources = await _sources_for(ctx)
    return health_report(
        integrations,
        [SourceHealth.from_source(source) for source in sources],
        now=now,
        floor_s=settings.source_stale_after_s,
    )


async def publish_to_mqtt(ctx: dict[str, Any]) -> dict[str, Any]:
    """Publish the Ministry's state back into Home Assistant over MQTT.

    ``contracts/events/mqtt.md`` is the contract: retained discovery configs,
    retained state, one availability topic that everything hangs off. Every
    message goes through :func:`~workers.hub.mqtt.guard`, which refuses a
    payload carrying anything credential-shaped — the contract's "nothing
    secret goes in a payload", enforced rather than remembered.

    **an earlier release adds the transport.** Outside mock mode, with a broker named and
    ``aiomqtt`` installed, this connects through
    :func:`~workers.hub.mqtt.connect_publisher` and stamps the MQTT
    integration row — ``last_ok_at`` or a redacted ``last_error`` — so the
    Ministry Office reads its health like Home Assistant's. Otherwise it
    builds and guards every message and reports what it *would* send, which
    is what most tests assert: the bytes on the topic, not the library.

    **an earlier release fills the seam this job was left with.** Nothing put ``rounds``
    or ``frost`` into ``ctx``, so a deployed worker published a permanent zero
    on ``herbology/rounds/due`` and a permanent ``OFF`` on the frost
    binary_sensor — the contract's topics, carrying nothing, which is precisely
    the silent failure this parts of the project exists to prevent. It now reads the same
    two endpoints the notification jobs read
    (:mod:`workers.hub.notify.state`), so a household can hang a Home Assistant
    automation off the frost sensor and have it mean something.

    A read that fails is reported and **nothing is published**. Publishing a
    zero because the API did not answer would retain that zero on the broker
    until something replaced it, which is worse than an entity going
    unavailable: the availability topic can say "we are not answering", and a
    retained zero cannot be taken back.
    """
    rounds = ctx.get("rounds")
    frost = ctx.get("frost")
    specimens = ctx.get("specimens")
    read_error: str | None = None
    if rounds is None or frost is None or specimens is None:
        from .notify.state import build_reader

        settings = _settings(ctx)
        reader = ctx.get("reader") or build_reader(settings)
        try:
            if rounds is None:
                rounds = await reader.rounds()
            if frost is None:
                frost = await reader.frost()
            if specimens is None and hasattr(reader, "specimens"):
                specimens = specimen_states(await reader.specimens(), rounds)
        except Exception as exc:  # noqa: BLE001 - reported, never raised at Arq
            read_error = redact(
                f"could not read the Ministry's state: {exc}", _secrets(settings)
            )
    if read_error:
        return {
            "job": "publish_to_mqtt",
            "ok": False,
            "error": read_error,
            "published": 0,
            "topics": [],
        }

    rounds = rounds or {}
    frost = frost or {}
    specimens = specimens or []
    version = str(ctx.get("sw_version") or "1.0.0")

    messages = [availability(True)]
    messages += discovery_messages(
        specimen_ids=[
            str(row.get("specimen_id") or row.get("id")) for row in specimens
        ],
        sw_version=version,
    )
    messages += rounds_messages(**_rounds_state(rounds))
    messages += frost_messages(**_frost_state(frost))
    for row in specimens:
        messages += specimen_messages(
            str(row.get("specimen_id") or row.get("id")),
            water_due=bool(row.get("water_due")),
            deficit_mm=row.get("deficit_mm"),
        )

    publisher = ctx.get("publisher")
    settings = _settings(ctx)
    if publisher is None and _live_mqtt(settings):
        return await _publish_live(ctx, settings, messages)
    publisher = publisher or MemoryPublisher()
    sent = await publish_all(publisher, messages)
    return _published(sent, type(publisher).__name__)


def specimen_states(
    specimens: Sequence[Mapping[str, Any]], rounds: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """Each plant's two MQTT entities, from the specimen list and the round.

    ``water_due`` is ON when today's round has a watering for that plant —
    The scheduler's answer, not one this worker computes. ``deficit_mm`` is ``None``,
    which publishes ``unknown``: the per-plant water balance is one request per
    plant to the weather engine's endpoint, not yet made here, and an unknown deficit must not
    be published as a zero (see :func:`~workers.hub.mqtt.specimen_messages`).
    Archived plants are left out, so a plant that died does not keep an entity
    saying it is thirsty.
    """
    due = {
        str((task.get("specimen") or {}).get("id"))
        for task in (rounds or {}).get("due") or ()
        if isinstance(task, Mapping) and task.get("task_type") == "water"
    }
    return [
        {
            "specimen_id": str(row["id"]),
            "water_due": str(row["id"]) in due,
            "deficit_mm": None,
        }
        for row in specimens
        if isinstance(row, Mapping)
        and row.get("id")
        and row.get("status") != "archived"
    ]


def _live_mqtt(settings: HubSettings) -> bool:
    """A broker is named, a client is installed, and this is not mock mode."""
    from .world import _is_configured

    return not settings.mock_mode and _is_configured("mqtt", settings)


def _published(sent: Sequence[Any], transport: str) -> dict[str, Any]:
    return {
        "job": "publish_to_mqtt",
        "ok": True,
        "published": len(sent),
        "retained": sum(1 for message in sent if message.retain),
        "topics": [message.topic for message in sent],
        "transport": transport,
    }


async def _publish_live(
    ctx: dict[str, Any], settings: HubSettings, messages: Sequence[Any]
) -> dict[str, Any]:
    """Publish over the broker and leave the result on MQTT's integration row.

    The same rule the Home Assistant jobs follow: ``last_ok_at`` when it
    worked, a redacted ``last_error`` when it did not, so the Ministry Office
    reads MQTT's health off the row rather than out of a log.
    """
    from . import store
    from .mqtt import connect_publisher
    from .world import HUB_INTEGRATIONS

    name = dict(HUB_INTEGRATIONS)["mqtt"]
    connection = ctx.get("connection")
    try:
        async with connect_publisher(
            settings, client_module=ctx.get("mqtt_client_module")
        ) as publisher:
            sent = await publish_all(publisher, messages)
    except Exception as exc:  # noqa: BLE001 - recorded, never raised at Arq
        error = redact(f"{exc}", _secrets(settings)) or type(exc).__name__
        if connection is not None:
            await store.record_error(connection, "mqtt", name, error)
        return {
            "job": "publish_to_mqtt",
            "ok": False,
            "error": error,
            "published": 0,
            "topics": [],
        }
    if connection is not None:
        await store.record_ok(connection, "mqtt", name, datetime.now(UTC))
    return _published(sent, type(publisher).__name__)


def _rounds_state(rounds: Mapping[str, Any]) -> dict[str, Any]:
    """``MorningRounds`` into the three things the contract's topics carry.

    Accepts the already-counted shape too (``{"due": 4, "overdue": 1}``), which
    is what a caller with the numbers to hand passes and what the earlier tests use.
    A ``due`` that is a list is counted; a ``due`` that is a number is taken as
    the count.

    ``overdue`` is derived from the tasks themselves rather than asked for:
    ``MorningRounds`` has no overdue field, and a task whose ``due_at`` is
    before today is what "overdue" means.
    """
    raw = rounds.get("due")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return {
            "due": int(raw),
            "overdue": int(rounds.get("overdue") or 0),
            "tasks": rounds.get("tasks") or (),
        }
    rows = raw if isinstance(raw, Sequence) and not isinstance(raw, str) else ()
    tasks = [task for task in rows if isinstance(task, Mapping)]
    today = str(rounds.get("date") or "")
    overdue = sum(
        1 for task in tasks if today and str(task.get("due_at") or "")[:10] < today
    )
    return {
        "due": len(tasks),
        "overdue": overdue,
        "tasks": [_task_row(task) for task in tasks],
    }


def _task_row(task: Mapping[str, Any]) -> dict[str, Any]:
    """The four fields ``mqtt._task_attributes`` allows, named as it expects.

    The allow-list there is the guard; this is the translation. The original-theme rule plain
    title is what a dashboard shows, for the same reason a notification does.
    """
    specimen = task.get("specimen")
    name = ""
    if isinstance(specimen, Mapping):
        name = str(specimen.get("nickname") or specimen.get("display_name") or "")
    return {
        "id": task.get("id", ""),
        "specimen": name,
        "kind": task.get("plain_title") or task.get("task_type") or "",
        "due_on": str(task.get("due_at") or "")[:10] or None,
    }


def _frost_state(frost: Mapping[str, Any]) -> dict[str, Any]:
    """``FrostReport`` into the frost binary_sensor and the next-frost date.

    ``unassessable`` deliberately does not turn the sensor ``ON``. A plant that
    could not be judged is not a plant known to be at risk, and an automation
    that closed the greenhouse vents on "we do not know" would be acting on
    nothing. It is carried in the attributes instead, where a dashboard can
    show it and ``herbology/frost/next`` stays ``unknown`` rather than
    becoming a date nobody computed.
    """
    if "active" in frost:
        return {
            "active": bool(frost.get("active")),
            "night": frost.get("night"),
            "low_c": frost.get("low_c"),
            "specimens": frost.get("specimens") or (),
            "next_frost": frost.get("next"),
        }
    alerts = [
        alert
        for alert in (frost.get("alerts") or ())
        if isinstance(alert, Mapping) and str(alert.get("state") or "open") == "open"
    ]
    nights = sorted(
        str(alert.get("night_of")) for alert in alerts if alert.get("night_of")
    )
    lows = [
        float(alert["forecast_low_c"])
        for alert in alerts
        if isinstance(alert.get("forecast_low_c"), (int, float))
    ]
    names = []
    for alert in alerts:
        specimen = alert.get("specimen")
        if isinstance(specimen, Mapping):
            names.append(
                str(specimen.get("nickname") or specimen.get("display_name") or "")
            )
    return {
        "active": bool(alerts),
        "night": nights[0] if nights else None,
        "low_c": min(lows) if lows else None,
        "specimens": [name for name in names if name],
        "next_frost": nights[0] if nights else None,
    }


def _report(
    started_at: datetime,
    *,
    ok: bool,
    error: str | None = None,
    finished_at: datetime | None = None,
    **extra: Any,
) -> dict[str, Any]:
    finished = finished_at or datetime.now(UTC)
    return {
        "job": "poll_home_assistant",
        "ok": ok,
        "error": error,
        "started_at": started_at.isoformat(),
        "took_ms": round((finished - started_at).total_seconds() * 1000, 1),
        **extra,
    }


class WorkerSettings(metaclass=ArqBootstrap):
    """Arq entrypoint.

    The schedules follow the releases's exit criterion — indoor readings stored
    every 5–15 minutes. Five for the poll, which is the finest cadence any row
    asks for; five for the health check, offset by two minutes so the Ministry
    Office learns the hub is down from a cheap ``GET /api/`` rather than from
    a poll that had to time out first.
    """

    functions: ClassVar[list] = [
        poll_home_assistant,
        check_home_assistant,
        hub_health,
        publish_to_mqtt,
        notify_rounds,
        notify_frost,
        notify_integration_health,
    ]

    cron_jobs: ClassVar[list] = []


def _build_cron_jobs() -> list[Any]:
    """Built lazily so importing this module never requires Arq to be installed.

    :data:`SUPPORTED_METRICS` and the topic helpers are imported by other
    parts of the project and by the mocks, neither of which runs jobs. A missing
    scheduler dependency must not take the adapter's constants down with it.
    """
    try:
        from arq import cron
    except ImportError:  # pragma: no cover - arq is a declared dependency
        return []

    return [
        cron(poll_home_assistant, minute=set(range(0, 60, 5)), run_at_startup=True),
        cron(
            check_home_assistant,
            minute={2, 7, 12, 17, 22, 27, 32, 37, 42, 47, 52, 57},
            run_at_startup=True,
        ),
        # After the poll and after the scheduler's rules have run for the morning.
        cron(publish_to_mqtt, minute={10, 40}),
        # --- notifications ------------------------------------------
        #
        # Frost every fifteen minutes, and that cadence is the requirement
        # rather than a preference: the brief's own example is a Freeze
        # Warning issued at 2 PM for that night, and a daily job learns about
        # it the following morning. The job is cheap — one GET, and nothing
        # sent unless the forecast is new news — so the interval is set by how
        # late an alert may be, not by how much it costs.
        cron(notify_frost, minute={0, 15, 30, 45}),
        # Rounds hourly: the job itself decides whether the site's local clock
        # has reached the hour the member asked for, because a cron in UTC
        # cannot know that and a household that moves through a DST change
        # would otherwise get their rounds an hour out twice a year.
        cron(notify_rounds, minute={5}),
        # Health hourly, well after the poll and the health check have had a
        # chance to run and record. It waits out its own grace period on top.
        cron(notify_integration_health, minute={25}),
    ]


WorkerSettings.cron_jobs = _build_cron_jobs()
