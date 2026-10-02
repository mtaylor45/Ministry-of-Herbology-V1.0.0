"""The three jobs, end to end against the mock Ministry. Owner: The hub.

Every test here runs with no database, no API and no network: the mock reader
answers from the frozen fixtures and the memory channel records what would have
gone out. That is the whole an earlier release demonstration path, and it is the one the releases
exit criterion is shown on before it is shown on a deployment.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from workers.hub.notify import jobs
from workers.hub.notify.channels import MemoryChannel
from workers.hub.notify.model import Recipient
from workers.hub.notify.policy import MemoryLedger

#: 07:30 local in the fixture site's zone (America/Indiana/Indianapolis, UTC−4
#: in October), which is after the default rounds hour and outside quiet hours.
MORNING = datetime(2026, 10, 23, 11, 30, tzinfo=UTC)
#: 23:30 local — inside quiet hours, and the hour the brief's Freeze Warning
#: scenario is about.
NIGHT = datetime(2026, 10, 24, 3, 30, tzinfo=UTC)


@pytest.fixture
def ctx(settings, ministry, channel, recipient):
    return {
        "settings": settings,
        "reader": ministry,
        "channel": channel,
        "recipients": [recipient],
        "ledger": MemoryLedger(),
        "now": MORNING,
    }


# ------------------------------------------------------------------- rounds


def test_the_rounds_go_out_once_in_the_morning(run, ctx, channel):
    report = run(jobs.notify_rounds(ctx))
    assert report["ok"] is True
    assert len(report["sent"]) == 1
    assert channel.titles() == ["Today's rounds: 3 tasks"]


def test_the_rounds_are_not_sent_twice_in_one_day(run, ctx, channel):
    """The cron runs hourly. The member gets one list."""
    run(jobs.notify_rounds(ctx))
    second = run(jobs.notify_rounds({**ctx, "now": MORNING + timedelta(hours=3)}))
    assert second["sent"] == []
    assert any("not new news" in item["reason"] for item in second["skipped"])
    assert len(channel.sent) == 1


def test_the_rounds_wait_for_the_local_morning(run, ctx, channel):
    """05:00 local. The cron fired; the job declined, and said why."""
    early = run(jobs.notify_rounds({**ctx, "now": MORNING.replace(hour=9)}))
    assert early["sent"] == []
    assert any("too early" in item["reason"] for item in early["skipped"])
    assert channel.sent == []


def test_the_mock_stack_demonstrates_the_hedged_path_because_that_is_what_it_is(
    run, ctx, channel
):
    """The no-invented-plant-facts rule: nothing here invents a plant fact.

    The mock's tasks come from fixtures, not from the scheduler's scheduler, so
    every one is stamped ``unknown`` and ``degraded`` — and the notification a
    reviewer sees in mock mode says so. A mock that produced confident-looking
    tasks would be this package asserting care facts with no citation.
    """
    run(jobs.notify_rounds(ctx))
    message = channel.messages()[0]
    assert "demonstration rather than as advice" in message
    assert channel.sent[0][0].certainty.confidence == "unknown"


def test_the_notification_names_the_plant_nobody_could_schedule(run, ctx, channel):
    """The mock world contains one on purpose. A plant with no task looks
    exactly like a plant that needs nothing."""
    run(jobs.notify_rounds(ctx))
    assert "1 plant could not be scheduled at all" in channel.messages()[0]


def test_the_notification_does_not_pretend_the_soil_was_measured(run, ctx, channel):
    """the design, on the wire rather than in a docstring."""
    run(jobs.notify_rounds(ctx))
    assert "Nothing measures the soil" in channel.messages()[0]


def test_a_day_with_nothing_due_interrupts_nobody(run, ctx, channel, ministry):
    async def empty():
        return {"date": "2026-10-23", "due": [], "unscheduled": []}

    ministry.rounds = empty
    report = run(jobs.notify_rounds(ctx))
    assert channel.sent == []
    assert any("no all-clear" in item["reason"] for item in report["skipped"])


# -------------------------------------------------------------------- frost


def test_a_frost_warning_arrives_at_half_past_eleven_at_night(run, ctx, channel):
    """The brief's own case, inverted: a warning issued at 2 PM for that night
    is not something to learn about at 3. Quiet hours do not hold it."""
    report = run(jobs.notify_frost({**ctx, "now": NIGHT}))
    assert report["ok"] is True
    assert len(report["sent"]) == 1
    notification, _, body = channel.sent[0]
    assert notification.urgent is True
    assert body["data"]["push"] == {"interruption-level": "time-sensitive"}


def test_the_frost_message_carries_the_nws_headline_and_the_action(run, ctx, channel):
    run(jobs.notify_frost({**ctx, "now": NIGHT}))
    message = channel.messages()[0]
    assert "Freeze Warning in effect from 2 AM to 9 AM" in message
    assert "Bring indoors" in message or "Cover" in message


def test_the_same_forecast_is_not_announced_twice(run, ctx, channel):
    """The frost job runs every fifteen minutes. It says one thing once."""
    run(jobs.notify_frost({**ctx, "now": NIGHT}))
    again = run(jobs.notify_frost({**ctx, "now": NIGHT + timedelta(minutes=15)}))
    assert again["sent"] == []
    assert len(channel.sent) == 1


def test_a_forecast_that_gets_worse_gets_through(run, ctx, channel, ministry):
    """The reason the key is the content and not the night.

    A dedupe on the date alone would swallow the escalation, which is the one
    frost notification that matters most.
    """
    run(jobs.notify_frost({**ctx, "now": NIGHT}))
    original = ministry.frost

    async def colder():
        report = dict(await original())
        report["alerts"] = [
            {**alert, "forecast_low_c": -9.0, "action": "bring_indoors"}
            for alert in report["alerts"]
        ]
        return report

    ministry.frost = colder
    worse = run(jobs.notify_frost({**ctx, "now": NIGHT + timedelta(hours=1)}))
    assert len(worse["sent"]) == 1
    assert "-9.0 °C" in channel.messages()[1]


def test_a_night_with_no_frost_says_nothing(run, ctx, channel, ministry):
    async def clear():
        return {"alerts": [], "unassessable": []}

    ministry.frost = clear
    report = run(jobs.notify_frost({**ctx, "now": NIGHT}))
    assert channel.sent == []
    assert any("no open frost alert" in item["reason"] for item in report["skipped"])


# ------------------------------------------------------------------- health


def health(status="down", last_ok_at=None, **overrides):
    row = {
        "kind": "home_assistant",
        "name": "Home Assistant",
        "status": status,
        "last_error": "home_assistant: connection refused",
        "last_ok_at": last_ok_at,
    }
    row.update(overrides)
    return {"integrations": [row]}


def test_an_adapter_that_has_been_down_for_an_hour_is_worth_saying(run, ctx, channel):
    stale_since = MORNING - timedelta(hours=1)
    report = run(
        jobs.notify_integration_health(
            {**ctx, "health": health(last_ok_at=stale_since)}
        )
    )
    assert len(report["sent"]) == 1
    assert "Home Assistant is not answering" in channel.titles()[0]


def test_a_hub_that_rebooted_five_minutes_ago_interrupts_nobody(run, ctx, channel):
    """A blip is not a fault, and a health alert people swipe away is worse
    than none on the day it means something."""
    recent = MORNING - timedelta(minutes=5)
    report = run(
        jobs.notify_integration_health({**ctx, "health": health(last_ok_at=recent)})
    )
    assert channel.sent == []
    assert any("grace period" in note for note in report["notes"])


def test_an_unconfigured_integration_is_never_reported_as_a_fault(run, ctx, channel):
    run(
        jobs.notify_integration_health({**ctx, "health": health(status="unconfigured")})
    )
    assert channel.sent == []


def test_the_health_job_reads_the_hub_health_report_when_none_is_given(run, ctx):
    """It is the hub's own job and needs no HTTP call — the seam is a function."""
    report = run(jobs.notify_integration_health({k: v for k, v in ctx.items()}))
    assert report["job"] == "notify_integration_health"
    assert "broken" in report


# ----------------------------------------------------- failure is never silent


def test_a_notification_the_hub_refused_is_not_recorded_as_said(run, ctx, channel):
    """The difference between a frost warning ten minutes late and one that
    never arrives. A ledger that recorded the attempt would make the retry
    impossible."""

    class RefusingChannel:
        def __init__(self):
            self.attempts = 0

        async def send(self, notification, recipient):
            from workers.hub.notify.channels import Delivery

            self.attempts += 1
            return Delivery(
                kind=notification.kind,
                service=recipient.service,
                member_id=recipient.member_id,
                ok=False,
                reason="home_assistant: the hub is unreachable",
                dedupe_key=notification.dedupe_key,
            )

    refusing = RefusingChannel()
    first = run(jobs.notify_frost({**ctx, "channel": refusing, "now": NIGHT}))
    assert first["ok"] is False
    assert first["notified"] == []
    run(
        jobs.notify_frost(
            {**ctx, "channel": refusing, "now": NIGHT + timedelta(minutes=15)}
        )
    )
    assert refusing.attempts == 2


def test_a_delivery_failure_lands_on_integration_last_error(run, ctx, connection):
    """Under the design there is no second route, so "not delivered" is a fault
    the Ministry Office has to show without anybody reading logs."""

    class RefusingChannel:
        async def send(self, notification, recipient):
            from workers.hub.notify.channels import Delivery

            return Delivery(
                kind=notification.kind,
                service=recipient.service,
                member_id=recipient.member_id,
                ok=False,
                reason="home_assistant: the hub is unreachable",
            )

    run(
        jobs.notify_frost(
            {
                **ctx,
                "channel": RefusingChannel(),
                "connection": connection,
                "now": NIGHT,
            }
        )
    )
    updates = connection.matching("UPDATE integration SET last_error")
    assert updates
    assert "could not be delivered" in updates[0][1][1]


def test_an_unreachable_api_is_reported_rather_than_raised(run, ctx, ministry):
    """Arq logging an exception is not the same as a household being told."""

    async def broken():
        raise RuntimeError("ministry_api: connection refused")

    ministry.rounds = broken
    report = run(jobs.notify_rounds(ctx))
    assert report["sent"] == []
    assert any("could not read the rounds" in note for note in report["notes"])


def test_a_member_with_no_companion_app_is_noted_and_not_counted_as_broken(
    run, ctx, settings, ministry, channel
):
    without = {k: v for k, v in ctx.items() if k != "recipients"}
    ministry.members = _members_without_prefs
    report = run(jobs.notify_rounds(without))
    assert channel.sent == []
    assert any("no Home Assistant notify service" in note for note in report["notes"])
    assert report["ok"] is True


async def _members_without_prefs():
    return [{"id": "m-1", "name": "Keeper", "notify_prefs": {}}]


def test_a_deployment_wide_notify_service_covers_a_member_with_no_prefs(
    run, ctx, ministry, channel
):
    """One household, one phone, nobody who wants to edit a JSON blob to get
    their watering reminders."""
    from workers.hub.settings import HubSettings

    settings = HubSettings(
        mock_mode=True,
        fixtures_dir=ctx["settings"].fixtures_dir,
        ha_notify_service="notify.everyone",
    )
    ministry.members = _members_without_prefs
    without = {k: v for k, v in ctx.items() if k != "recipients"}
    report = run(jobs.notify_rounds({**without, "settings": settings}))
    assert len(report["sent"]) == 1
    assert channel.sent[0][1].service == "notify.everyone"


# --------------------------------------------------- every job says why it was quiet


@pytest.mark.parametrize(
    "job",
    [jobs.notify_rounds, jobs.notify_frost, jobs.notify_integration_health],
)
def test_every_job_explains_itself_even_when_it_sent_nothing(run, ctx, ministry, job):
    """ "Why did I not get my rounds this morning?" is answerable from the
    report, or the answer is a log file and an afternoon.

    A world with nothing to say, rather than a clock that holds things back:
    frost deliberately ignores the rounds hour and the quiet window, so the
    only way it is silent is that there is no frost.
    """

    async def nothing_due():
        return {"date": "2026-10-23", "due": [], "unscheduled": []}

    async def no_frost():
        return {"alerts": [], "unassessable": []}

    ministry.rounds = nothing_due
    ministry.frost = no_frost
    quiet = {**ctx, "now": MORNING.replace(hour=9), "health": {"integrations": []}}
    report = run(job(quiet))
    assert report["ok"] is True
    assert "skipped" in report and "notes" in report
    assert report["sent"] == []


def test_one_message_is_sent_once_even_when_two_members_share_a_phone(
    run, ctx, channel
):
    """Two members, one kitchen tablet. It chimes once.

    A dedupe key that named the member instead of the destination would make
    the tablet chime twice for the same frost, which is how a household learns
    to ignore it.
    """
    shared = [
        Recipient(
            member_id=f"m-{index}",
            name=f"Member {index}",
            service="notify.the_kitchen_tablet",
        )
        for index in (1, 2)
    ]
    report = run(jobs.notify_frost({**ctx, "recipients": shared, "now": NIGHT}))
    assert len(channel.sent) == 1
    assert any("not new news" in item["reason"] for item in report["skipped"])


def test_two_members_with_their_own_phones_are_both_told(run, ctx, channel):
    """The flip side, and the reason the key is the service and not a constant."""
    separate = [
        Recipient(member_id="m-1", name="One", service="notify.mobile_app_one"),
        Recipient(member_id="m-2", name="Two", service="notify.mobile_app_two"),
    ]
    run(jobs.notify_frost({**ctx, "recipients": separate, "now": NIGHT}))
    assert len(channel.sent) == 2


def test_the_jobs_and_the_prefs_switches_have_not_drifted_apart():
    """Three kinds, three jobs, three switches in ``notify_prefs``."""
    from workers.hub.notify.model import KINDS

    assert set(jobs.JOB_FOR_KIND) == set(KINDS) == {"rounds", "frost", "health"}


def test_nothing_in_the_notification_path_opens_a_socket(run, ctx, channel):
    """The autouse fixture fails any connection attempt. That this passes is
    the assertion: mock mode is the whole demonstration path."""
    run(jobs.notify_rounds(ctx))
    run(jobs.notify_frost({**ctx, "now": NIGHT}))
    assert isinstance(channel, MemoryChannel)
    assert len(channel.sent) == 2


# ---------------------------------------------- the MQTT seam, filled at last


def test_the_mqtt_job_publishes_the_real_rounds_rather_than_a_zero(run, ctx):
    """an earlier release left ``publish_to_mqtt`` with a ``ctx`` nothing filled.

    A deployed worker therefore published a permanent ``0`` on
    ``herbology/rounds/due`` and a permanent ``OFF`` on the frost sensor — the
    contract's topics carrying nothing, which is the silent failure this
    parts of the project exists to prevent.
    """
    from workers.hub import tasks
    from workers.hub.mqtt import MemoryPublisher

    publisher = MemoryPublisher()
    report = run(
        tasks.publish_to_mqtt(
            {
                "settings": ctx["settings"],
                "reader": ctx["reader"],
                "publisher": publisher,
            }
        )
    )
    assert report["ok"] is True
    assert publisher.payload_for("herbology/rounds/due") == "3"
    assert publisher.payload_for("herbology/frost/state") == "ON"
    assert publisher.payload_for("herbology/frost/next") == "2026-10-23"


def test_the_mqtt_job_publishes_nothing_when_it_could_not_read(run, ctx):
    """A retained zero cannot be taken back.

    The availability topic can say "we are not answering"; a retained ``0`` on
    a task count says "there is nothing to do", forever, to anything watching.
    """
    from workers.hub import tasks
    from workers.hub.mqtt import MemoryPublisher

    async def broken():
        raise RuntimeError("ministry_api: connection refused")

    ctx["reader"].rounds = broken
    publisher = MemoryPublisher()
    report = run(
        tasks.publish_to_mqtt(
            {
                "settings": ctx["settings"],
                "reader": ctx["reader"],
                "publisher": publisher,
            }
        )
    )
    assert report["ok"] is False
    assert publisher.sent == []


def test_a_plant_that_could_not_be_assessed_does_not_turn_the_frost_sensor_on(run, ctx):
    """An automation that closed the vents on "we do not know" acts on nothing."""
    from workers.hub import tasks
    from workers.hub.mqtt import MemoryPublisher

    async def only_unassessable():
        return {
            "alerts": [],
            "unassessable": [{"specimen_id": "x", "reason": "no data"}],
        }

    ctx["reader"].frost = only_unassessable
    publisher = MemoryPublisher()
    run(
        tasks.publish_to_mqtt(
            {
                "settings": ctx["settings"],
                "reader": ctx["reader"],
                "publisher": publisher,
            }
        )
    )
    assert publisher.payload_for("herbology/frost/state") == "OFF"
    assert publisher.payload_for("herbology/frost/next") == "unknown"


def test_the_mqtt_attributes_carry_the_plain_title_and_no_more(run, ctx):
    """The allow-list in ``mqtt._task_attributes`` is the guard; this is what
    reaches it. A broker retains what it is given."""
    import json

    from workers.hub import tasks
    from workers.hub.mqtt import MemoryPublisher

    publisher = MemoryPublisher()
    run(
        tasks.publish_to_mqtt(
            {
                "settings": ctx["settings"],
                "reader": ctx["reader"],
                "publisher": publisher,
            }
        )
    )
    payload = json.loads(publisher.payload_for("herbology/rounds/due/attributes"))
    first = payload["tasks"][0]
    assert set(first) == {"id", "specimen", "kind", "due_on"}
    assert first["kind"].startswith("Water ")
