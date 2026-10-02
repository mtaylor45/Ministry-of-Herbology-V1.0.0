"""When to interrupt somebody, and when not to. Owner: The hub.

The copy tests cover what a notification says. These cover the harder half:
whether it is sent at all. A notification nobody wanted trains the reader to
swipe the next one away, and the next one is the freeze warning.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from workers.hub.notify.model import Certainty, Notification, Recipient
from workers.hub.notify.policy import (
    HEALTH_GRACE_S,
    Decision,
    MemoryLedger,
    health_is_sustained,
    in_quiet_hours,
    local_now,
    may_send,
    window_start,
)

MORNING = datetime(2026, 10, 23, 7, 30, tzinfo=UTC)
MIDNIGHT = datetime(2026, 10, 23, 23, 30, tzinfo=UTC)


def note(kind="rounds", key="k1", urgent=False):
    return Notification(
        kind=kind,
        title="t",
        body="b",
        dedupe_key=key,
        urgent=urgent,
        certainty=Certainty(),
    )


# ------------------------------------------------------------- the local clock


def test_local_time_is_the_sites_and_not_the_servers():
    """Timestamps are stored UTC; local time is resolved per-site (the project conventions).

    Seven in the morning means seven where the plants are.
    """
    at = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)
    local = local_now(at, "America/Indiana/Indianapolis")
    assert local.hour == 7


def test_an_unusable_timezone_falls_back_to_utc_rather_than_killing_the_job():
    """A notification an hour early is a nuisance. A job that dies on a typo in
    ``site.timezone`` is a household that gets nothing and no explanation."""
    assert local_now(MORNING, "Not/AZone").hour == MORNING.hour
    assert local_now(MORNING, None).hour == MORNING.hour


@pytest.mark.parametrize(
    ("hour", "quiet"),
    [
        (22, True),
        (23, True),
        (0, True),
        (6, True),
        (7, False),
        (12, False),
        (21, False),
    ],
)
def test_the_quiet_window_wraps_midnight(hour, quiet, recipient):
    """22 to 7 is nine hours of night, not fifteen hours of day."""
    assert in_quiet_hours(hour, recipient) is quiet


def test_a_member_with_no_quiet_hours_has_none(recipient):
    always = Recipient.from_member_row(
        {
            "id": "m",
            "name": "n",
            "notify_prefs": {
                "home_assistant": {"service": "notify.x", "quiet_hours": [0, 0]}
            },
        }
    )
    assert in_quiet_hours(3, always) is False


# ------------------------------------------------------------------ the gate


def test_rounds_wait_for_the_hour_the_member_chose(recipient):
    early = may_send(note(), recipient, local=MORNING.replace(hour=5))
    assert not early
    assert "too early" in early.reason
    assert may_send(note(), recipient, local=MORNING.replace(hour=8))


def test_rounds_are_held_during_quiet_hours(recipient):
    decision = may_send(note(), recipient, local=MORNING.replace(hour=23))
    assert not decision
    assert "quiet hours" in decision.reason


def test_frost_overrides_quiet_hours_and_says_so(recipient):
    """A person who asked not to be disturbed after ten did not mean "let the
    lemon tree die quietly". Stated, so it is a decision and not an oversight."""
    decision = may_send(note(kind="frost", urgent=True), recipient, local=MIDNIGHT)
    assert decision
    assert "time-critical" in decision.reason


def test_a_household_that_disagrees_can_turn_frost_off(recipient):
    """The override is only defensible because the switch exists."""
    no_frost = Recipient.from_member_row(
        {
            "id": "m",
            "name": "n",
            "notify_prefs": {"home_assistant": {"service": "notify.x", "frost": False}},
        }
    )
    decision = may_send(note(kind="frost", urgent=True), no_frost, local=MIDNIGHT)
    assert not decision
    assert "frost turned off" in decision.reason


def test_the_same_news_is_not_sent_twice(recipient):
    decision = may_send(
        note(), recipient, local=MORNING.replace(hour=9), already_sent={"k1"}
    )
    assert not decision
    assert "not new news" in decision.reason


def test_a_member_with_no_notify_service_is_skipped_and_not_an_error(recipient):
    nobody = Recipient(member_id="m", name="Nobody", service="")
    decision = may_send(note(), nobody, local=MORNING.replace(hour=9))
    assert not decision
    assert "no Home Assistant notify service" in decision.reason


def test_every_refusal_carries_a_reason(recipient):
    """ "Why did I not get my rounds?" has to be answerable from the report."""
    decision = may_send(note(), recipient, local=MORNING.replace(hour=3))
    assert isinstance(decision, Decision)
    assert decision.reason


# ------------------------------------------------------------ health's grace


def test_one_failed_poll_is_not_worth_a_notification():
    """A hub reboots. A container restarts. A blip is not a fault."""
    now = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    fresh = {"last_ok_at": now - timedelta(minutes=5)}
    assert health_is_sustained(fresh, now=now) is False


def test_a_failure_that_outlives_the_grace_period_is_worth_saying():
    now = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    old = {"last_ok_at": now - timedelta(seconds=HEALTH_GRACE_S + 60)}
    assert health_is_sustained(old, now=now) is True


def test_a_hub_that_has_never_once_answered_is_reported_immediately():
    """It has had its grace period since the deployment started, and "this has
    never worked" is exactly the setup problem worth telling somebody about."""
    now = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    assert health_is_sustained({"last_ok_at": None}, now=now) is True


def test_an_iso_timestamp_from_a_json_row_is_understood():
    now = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    row = {"last_ok_at": "2026-10-23T11:00:00+00:00"}
    assert health_is_sustained(row, now=now) is True


# ----------------------------------------------------------------- the ledger


def test_the_memory_ledger_forgets_outside_the_window(run):
    ledger = MemoryLedger()
    now = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    run(ledger.record("notify_rounds", ["old"], at=now - timedelta(days=3)))
    run(ledger.record("notify_rounds", ["new"], at=now))
    assert run(ledger.sent_keys(window_start(now))) == {"new"}


def test_the_memory_ledger_is_honest_about_not_surviving_a_restart():
    """Stated rather than hidden. The deployed stack has a database."""
    assert MemoryLedger().is_durable is False


# --------------------------------------------------- the notify_prefs reading


def test_a_member_with_no_prefs_is_not_a_recipient_and_not_a_fault():
    """The normal state of a household where one person has the app and two
    do not. Returning ``None`` keeps it out of every error count."""
    assert (
        Recipient.from_member_row({"id": "m", "name": "n", "notify_prefs": {}}) is None
    )


def test_an_archived_member_is_not_notified():
    row = {
        "id": "m",
        "name": "n",
        "archived_at": "2026-01-01T00:00:00Z",
        "notify_prefs": {"home_assistant": {"service": "notify.x"}},
    }
    assert Recipient.from_member_row(row) is None


def test_each_kind_can_be_turned_off_on_its_own():
    row = {
        "id": "m",
        "name": "n",
        "notify_prefs": {
            "home_assistant": {"service": "notify.x", "rounds": False, "health": False}
        },
    }
    recipient = Recipient.from_member_row(row)
    assert recipient.wants("frost") is True
    assert recipient.wants("rounds") is False
    assert recipient.wants("health") is False


def test_a_nonsense_pref_falls_back_rather_than_raising():
    """``notify_prefs`` is an open jsonb blob a person can hand-edit. A typo in
    it must not stop the frost warning."""
    row = {
        "id": "m",
        "name": "n",
        "notify_prefs": {
            "home_assistant": {
                "service": "notify.x",
                "rounds_hour": "breakfast",
                "quiet_hours": "never",
            }
        },
    }
    recipient = Recipient.from_member_row(row)
    assert recipient.rounds_hour == 7
    assert (recipient.quiet_from, recipient.quiet_to) == (22, 7)
