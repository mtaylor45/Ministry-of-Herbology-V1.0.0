"""Calendar push, end to end on the mock stack, against a fake CalDAV server.

the design as tests. The fake is an ``httpx.MockTransport`` in the hub's style:
one resource per path with an ETag, ``If-None-Match: *`` and ``If-Match``
honoured, every request recorded with the moment it arrived. So "a completion
reaches the server", "a revoked feed gets no further PUT" and "nothing secret
leaves" are assertions on traffic, not on this package's own report.

The CalDAV credential here is real-shaped on purpose, and the collection path
carries the username the way Fastmail's and Nextcloud's do, so a leak of
either would be caught.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from icalendar import Calendar

from tending import push
from tending.tests.caldav_fake import _UID, PASSWORD, USERNAME, FakeCaldav

MEMBER = "01890050-0000-7000-8000-000000000001"
HOST = "caldav.example.net"
COLLECTION = f"https://{HOST}/dav/calendars/user/alice@example.net/plants/"
FIVE_MINUTES = 300.0


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeCaldav]:
    server = FakeCaldav()
    monkeypatch.setattr(
        push,
        "client_factory",
        lambda _target: httpx.AsyncClient(
            transport=httpx.MockTransport(server.handler)
        ),
    )
    yield server


@pytest.fixture
def secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``MOH_SECRETS_DIR``, empty: every CalDAV feed awaits its operator."""
    directory = tmp_path / "secrets"
    directory.mkdir()
    monkeypatch.setenv("MOH_SECRETS_DIR", str(directory))
    return directory


def provision(
    secrets: Path,
    feed_id: str,
    lines: str | None = None,
    collection: str = COLLECTION,
) -> Path:
    path = secrets / f"moh_caldav_{feed_id}"
    path.write_text(lines or f"{collection}\n{USERNAME}\n{PASSWORD}\n")
    return path


def create_feed(client, name: str = "Pushed", **extra) -> dict:
    response = client.post(
        "/api/v1/tending/feeds",
        json={"member_id": MEMBER, "name": name, "push_target": "caldav", **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def feed(client, feed_id: str) -> dict:
    return next(
        f for f in client.get("/api/v1/tending/feeds").json() if f["id"] == feed_id
    )


def ics_path(row: dict) -> str:
    return row["https_url"].replace("http://localhost:8000", "")


def pushing_feed(
    client, secrets: Path, name: str = "Pushed", collection: str = COLLECTION
) -> dict:
    """A CalDAV feed with its secret in place and its first push done."""
    created = create_feed(client, name)
    provision(secrets, created["id"], collection=collection)
    client.get("/api/v1/tending/rounds")  # any read: the push follows it
    return created


def first_due_task(client) -> dict:
    return client.get("/api/v1/tending/rounds").json()["due"][0]


def uid_of(task_id: str) -> str:
    from tending.fixture_repository import fixture_repository

    return str(fixture_repository()._tasks[task_id]["ics_uid"])


def subscribed(client, row: dict) -> dict[str, tuple[int, str]]:
    """UID → (SEQUENCE, STATUS) of the ICS feed a subscriber would fetch."""
    return {
        # icalendar 7 types a property as a union of every value class, most
        # of which ``int()`` cannot take; SEQUENCE is a vInt and prints as one.
        str(c["UID"]): (int(str(c["SEQUENCE"])), str(c["STATUS"]))
        for c in Calendar.from_ical(client.get(ics_path(row)).text).walk()
        if c.name == "VEVENT"
    }


def put_uid(request: httpx.Request) -> str:
    found = _UID.search(request.content.decode())
    assert found
    return found.group(1)


# ------------------------------------------------------------ push_status


def test_a_feed_without_push_is_off(client, secrets):
    row = client.get("/api/v1/tending/feeds").json()[0]
    assert row["push_target"] == "none"
    assert row["push_status"] == "off"
    assert row["push_last_ok_at"] is None
    assert row["push_error"] is None


def test_a_caldav_feed_without_its_secret_is_awaiting_the_operator(
    client, secrets, fake
):
    created = create_feed(client)
    assert created["push_status"] == "awaiting_operator"
    client.post(f"/api/v1/tending/tasks/{first_due_task(client)['id']}/complete")
    row = feed(client, created["id"])
    assert row["push_status"] == "awaiting_operator"
    assert row["push_error"] is None, "a setup step is not a failure"
    assert fake.requests == []


def test_the_secret_arriving_starts_the_push_without_another_change(
    client, secrets, fake
):
    created = create_feed(client)
    provision(secrets, created["id"])
    assert feed(client, created["id"])["push_status"] == "ok"
    client.get("/api/v1/tending/rounds")
    assert fake.puts(), "the first read after the secret appears pushes"
    row = feed(client, created["id"])
    assert row["push_status"] == "ok"
    assert row["push_last_ok_at"]
    assert row["push_error"] is None


# ------------------------------------------------------------ what is pushed


def test_the_pushed_calendar_is_the_subscribed_calendar(client, secrets, fake):
    created = pushing_feed(client, secrets)
    calendar = subscribed(client, created)
    assert calendar, "the fixture household has a schedule"
    assert fake.held() == calendar


def test_a_completion_reaches_the_server_with_its_sequence_bumped(
    client, secrets, fake
):
    """the earlier exit criterion, measured: the full fixture feed, one completion.

    Completing a watering also re-anchors that plant's later occurrences, so
    their events move too; every one of them goes out, and nothing else does.
    """
    created = pushing_feed(client, secrets)
    before = fake.held()
    task = first_due_task(client)
    uid = uid_of(task["id"])
    seen = len(fake.requests)

    started = time.perf_counter()
    response = client.post(f"/api/v1/tending/tasks/{task['id']}/complete")
    assert response.status_code == 200

    puts = fake.puts(seen)
    arrived = next(at for at, request in puts if put_uid(request) == uid)
    assert arrived - started < FIVE_MINUTES
    assert fake.held()[uid][0] == before[uid][0] + 1
    for _at, request in puts:
        written = put_uid(request)
        assert written not in before or fake.held()[written][0] > before[written][0]
    # And the server already holds exactly the subscribed calendar: read
    # before the subscriber's fetch, so no later push can have helped.
    held = fake.held()
    assert held == subscribed(client, created)


def test_a_change_in_certainty_alone_reaches_the_calendar(client):
    """Same day, same status, same title — only how sure the task is changed.

    The feed carries ``X-MOH-CONFIDENCE``, so a subscriber holding the old
    event holds a stale certainty unless the ``SEQUENCE`` rises.
    """
    from tending.fixture_repository import fixture_repository

    row = feed(client, client.get("/api/v1/tending/feeds").json()[0]["id"])
    before = subscribed(client, row)
    task = first_due_task(client)
    repo = fixture_repository()
    stored = dict(repo._tasks[task["id"]])
    lower = "low" if stored["confidence"] != "low" else "unknown"
    asyncio.run(repo.upsert_tasks([{**stored, "confidence": lower}]))
    after = subscribed(client, row)
    uid = uid_of(task["id"])
    # The next read regenerates the task at its computed certainty, which is a
    # second change back: what matters is that each change raised it.
    assert after[uid][0] > before[uid][0]


def test_a_batch_completion_pushes_every_task_it_ticked(client, secrets, fake):
    created = pushing_feed(client, secrets)
    due = client.get("/api/v1/tending/rounds").json()["due"][:3]
    seen = len(fake.requests)
    client.post(
        "/api/v1/tending/tasks/complete-batch",
        json={"task_ids": [t["id"] for t in due]},
    )
    written = {put_uid(request) for _at, request in fake.puts(seen)}
    assert {uid_of(t["id"]) for t in due} <= written
    held = fake.held()
    assert held == subscribed(client, created)


def test_a_repeat_push_costs_no_request(client, secrets, fake):
    """Idempotent by UID and SEQUENCE: nothing changed, nothing is sent."""
    pushing_feed(client, secrets)
    seen = len(fake.requests)
    client.get("/api/v1/tending/rounds")
    client.get("/api/v1/tending/tasks")
    assert fake.requests[seen:] == []


def test_a_satisfied_task_is_cancelled_by_the_sweep_with_nobody_in_the_app(
    client, secrets, fake, monkeypatch
):
    """Weather is discovered when generation runs; the sweep runs it unasked."""
    from tending import environment
    from tending.domain import Environment
    from tending.fixture_repository import fixture_repository

    created = pushing_feed(client, secrets)
    due = client.get("/api/v1/tending/rounds").json()["due"]
    # An outdoor plant on the water balance: the one kind rain can settle.
    task = next(t for t in due if t["specimen"]["is_outdoor"])
    uid = uid_of(task["id"])
    seen = len(fake.requests)

    # Rain arrives in the weather engine's answer for this one plant. No request is made after
    # it, so only the sweep can discover it.
    real = environment.fixture_environments

    def rained(specimen_ids, waterings=None):
        out = real(specimen_ids, waterings)
        out[task["specimen"]["id"]] = Environment(
            applies=True,
            balance_status="satisfied",
            satisfied_by="rain",
            confidence="high",
        )
        return out

    monkeypatch.setattr(environment, "fixture_environments", rained)
    results = asyncio.run(
        push.push_owed(
            fixture_repository(), base_url="http://localhost:8000", generate=True
        )
    )

    assert results[created["id"]] == "ok"
    bodies = {put_uid(r): r.content.decode() for _at, r in fake.puts(seen)}
    assert uid in bodies
    assert "STATUS:CANCELLED" in bodies[uid]
    assert "Already satisfied by rain" in bodies[uid].replace("\r\n ", "")
    calendar = subscribed(client, created)
    assert fake.held() == calendar


def test_the_sweep_runs_on_its_own(client, secrets, fake):
    from tending.fixture_repository import fixture_repository

    created = create_feed(client)
    provision(secrets, created["id"])

    async def run() -> None:
        async def repository():
            return fixture_repository()

        sweeper = asyncio.create_task(
            push.sweep_forever(
                repository, lambda: "http://localhost:8000", interval_s=0.01
            )
        )
        for _ in range(200):
            await asyncio.sleep(0.01)
            if fake.puts():
                break
        sweeper.cancel()

    asyncio.run(run())
    assert fake.puts()
    assert feed(client, created["id"])["push_status"] == "ok"


# ------------------------------------------------------------ failure


def test_a_refused_login_is_failing_with_a_sentence_that_leaks_nothing(
    client, secrets, fake
):
    created = create_feed(client)
    provision(secrets, created["id"])
    fake.status = 401
    client.get("/api/v1/tending/rounds")

    row = feed(client, created["id"])
    assert row["push_status"] == "failing"
    error = row["push_error"]
    assert error and HOST in error and "app password" in error
    for secret in (USERNAME, PASSWORD, "/dav/calendars", "alice", str(secrets)):
        assert secret not in error


def test_a_failure_clears_on_the_next_clean_push(client, secrets, fake):
    created = create_feed(client)
    provision(secrets, created["id"])
    fake.status = 503
    client.get("/api/v1/tending/rounds")
    assert feed(client, created["id"])["push_status"] == "failing"

    fake.status = None
    client.get("/api/v1/tending/rounds")
    row = feed(client, created["id"])
    assert row["push_status"] == "ok"
    assert row["push_error"] is None


def test_an_unusable_secret_is_failing_and_says_why(client, secrets, fake):
    created = create_feed(client)
    provision(secrets, created["id"], lines=f"{COLLECTION}\n{USERNAME}\n")
    client.get("/api/v1/tending/rounds")
    row = feed(client, created["id"])
    assert row["push_status"] == "failing"
    assert "three lines" in row["push_error"]
    assert USERNAME not in row["push_error"]
    assert fake.requests == []


# ------------------------------------------------------------ revoke


def test_revoking_one_of_two_pushing_feeds_stops_only_that_one(client, secrets, fake):
    from tending.fixture_repository import fixture_repository

    kitchen = f"https://{HOST}/dav/kitchen/"
    phone = f"https://{HOST}/dav/old-phone/"
    kept = pushing_feed(client, secrets, "Kitchen", collection=kitchen)
    doomed = pushing_feed(client, secrets, "Old phone", collection=phone)
    assert any(r.url.path.startswith("/dav/old-phone/") for _at, r in fake.puts())
    kept_secret = (secrets / f"moh_caldav_{kept['id']}").read_text()
    kept_before = feed(client, kept["id"])

    assert (
        client.post(f"/api/v1/tending/feeds/{doomed['id']}/revoke").status_code == 204
    )
    doomed_row = asyncio.run(fixture_repository().feed(doomed["id"]))
    assert doomed_row is not None
    doomed_state = dict(doomed_row["push_state"])

    seen = len(fake.requests)
    task = first_due_task(client)
    client.post(f"/api/v1/tending/tasks/{task['id']}/complete")

    paths = [r.url.path for _at, r in fake.requests[seen:]]
    assert paths, "the kept feed still pushes"
    assert all(path.startswith("/dav/kitchen/") for path in paths)
    assert feed(client, doomed["id"])["push_status"] == "off"
    after = asyncio.run(fixture_repository().feed(doomed["id"]))
    assert after is not None and after["push_state"] == doomed_state
    # The other feed's secret and standing are untouched.
    assert (secrets / f"moh_caldav_{kept['id']}").read_text() == kept_secret
    assert (secrets / f"moh_caldav_{doomed['id']}").exists(), "the operator's to remove"
    row = feed(client, kept["id"])
    assert row["push_status"] == "ok"
    assert row["push_last_ok_at"] >= kept_before["push_last_ok_at"]


def test_a_revoked_feed_is_never_pushed_even_by_a_queued_push(client, secrets, fake):
    """A push that was already owed when the revoke landed sends nothing."""
    from tending.fixture_repository import fixture_repository

    created = create_feed(client)
    provision(secrets, created["id"])
    client.post(f"/api/v1/tending/feeds/{created['id']}/revoke")
    result = asyncio.run(
        push.push_feed(
            fixture_repository(), created["id"], base_url="http://localhost:8000"
        )
    )
    assert result == "off"
    assert fake.requests == []


# ------------------------------------------------------------ leaks


def test_the_feed_token_never_leaves_in_a_push(client, secrets, fake):
    """The only credential this app issues to a person. Not in any byte sent."""
    from tending.fixture_repository import fixture_repository

    created = pushing_feed(client, secrets)
    token = ics_path(created).rsplit("/", 1)[-1].removesuffix(".ics")
    assert len(token) >= 16
    client.post(f"/api/v1/tending/tasks/{first_due_task(client)['id']}/complete")
    fake.status = 401
    client.post(f"/api/v1/tending/tasks/{first_due_task(client)['id']}/complete")

    assert fake.requests
    for _at, request in fake.requests:
        assert token not in str(request.url)
        assert token not in request.content.decode()
        assert all(token not in value for value in request.headers.values())
    row = asyncio.run(fixture_repository().feed(created["id"]))
    assert row is not None
    assert token not in str(row["push_state"])
    assert token not in str(row["push_error"])
    assert row["push_config"] == {}


def test_the_caldav_credential_is_never_served(client, secrets, fake):
    pushing_feed(client, secrets)
    fake.status = 401
    client.get("/api/v1/tending/rounds")
    text = client.get("/api/v1/tending/feeds").text
    for secret in (USERNAME, PASSWORD, COLLECTION, str(secrets)):
        assert secret not in text
    assert "push_state" not in text and "push_config" not in text


def test_safe_error_replaces_a_sentence_that_carries_the_feed_token():
    token = "tok_" + "x" * 30
    feed_row = {"token": token}
    assert token not in push.safe_error(f"failed at /calendar/{token}.ics", feed_row)
    assert token not in push.safe_error(f"odd: {token}", feed_row)
    assert push.safe_error("A plain sentence.", feed_row) == "A plain sentence."


# ------------------------------------------------------------ the plan


def _row(uid: str, *, outdoor: bool, sequence: int = 0, status: str = "due") -> dict:
    return {
        "id": uid,
        "specimen": {"id": "s-" + uid, "display_name": "Fern", "is_outdoor": outdoor},
        "specimen_id": "s-" + uid,
        "task_type": "water",
        "due_at": datetime(2026, 10, 2, tzinfo=UTC),
        "all_day": True,
        "status": status,
        "title": "Tend the Fern",
        "plain_title": "Water the Fern",
        "ics_uid": uid,
        "ics_sequence": sequence,
    }


def test_a_task_that_leaves_the_feed_is_cancelled_once_and_returns_above_it():
    """Carried indoors, an outdoor-only feed loses it; a subscriber's does too."""
    outdoor_only = {"id": "f", "filters": {"outdoor": True}}
    state = {"a": {"sequence": 2, "etag": '"1"'}}

    tasks, in_feed, withdrawn = push.plan(
        outdoor_only, [_row("a", outdoor=False, sequence=2)], state
    )
    assert in_feed == set() and withdrawn == {"a"}
    [cancelled] = tasks
    assert cancelled["status"] == "cancelled" and cancelled["ics_sequence"] == 3
    assert push.owes(tasks, state)

    # Once the cancellation landed: marked, and not pushed again.
    state = {"a": {"sequence": 3, "etag": '"2"', "left": True}}
    tasks, _, withdrawn = push.plan(
        outdoor_only, [_row("a", outdoor=False, sequence=2)], state
    )
    assert tasks == [] and withdrawn == set()

    # Back outdoors: written again, above the cancellation's sequence.
    tasks, in_feed, _ = push.plan(
        outdoor_only, [_row("a", outdoor=True, sequence=2)], state
    )
    assert in_feed == {"a"}
    assert tasks[0]["ics_sequence"] == 4 and tasks[0]["status"] == "due"


def test_a_change_during_a_push_stays_owed():
    """``push_dirty_since`` clears only when the push started after it."""
    from tending.fixture_repository import FixtureRepository
    from tending.repository import PushOutcome

    async def run() -> None:
        repo = FixtureRepository()
        created = await repo.create_feed(
            {"member_id": MEMBER, "name": "x", "push_target": "caldav"}
        )
        started = datetime.now(UTC)
        await repo.mark_push_owed(created["id"], started + timedelta(seconds=1))
        await repo.record_push(
            created["id"], PushOutcome(state={}, started_at=started, ok_at=started)
        )
        row = await repo.feed(created["id"])
        assert row is not None and row["push_dirty_since"] is not None

        await repo.record_push(
            created["id"],
            PushOutcome(
                state={}, started_at=started + timedelta(seconds=2), ok_at=started
            ),
        )
        row = await repo.feed(created["id"])
        assert row is not None and row["push_dirty_since"] is None

    asyncio.run(run())


def _held_transport(server: FakeCaldav, on_first) -> httpx.MockTransport:
    """The fake, but the first request waits on ``on_first`` before answering."""
    first = True

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first
        if first:
            first = False
            await on_first()
        return server.handler(request)

    return httpx.MockTransport(handler)


def test_a_revoke_cancels_the_push_already_in_flight(secrets, monkeypatch):
    """the design, at once: the request on the wire may land, nothing after it."""
    from tending.fixture_repository import FixtureRepository

    server = FakeCaldav()

    async def run() -> tuple[str, int]:
        repo = FixtureRepository()
        created = await repo.create_feed(
            {"member_id": MEMBER, "name": "Old phone", "push_target": "caldav"}
        )
        feed_id = str(created["id"])
        provision(secrets, feed_id)
        arrived, release = asyncio.Event(), asyncio.Event()

        async def on_first() -> None:
            arrived.set()
            await release.wait()

        monkeypatch.setattr(
            push,
            "client_factory",
            lambda _t: httpx.AsyncClient(transport=_held_transport(server, on_first)),
        )
        from tending import service

        await service.generate_tasks(repo)
        pushing = asyncio.create_task(
            push.push_feed(repo, feed_id, base_url="http://localhost:8000")
        )
        # Bounded, so a push that never starts fails the test instead of hanging.
        await asyncio.wait_for(arrived.wait(), timeout=5)
        await repo.revoke_feed(feed_id)  # what the revoke route does, in order
        push.stop(feed_id)
        release.set()
        return await pushing, len(server.requests)

    result, requests = asyncio.run(run())
    assert result == "off"
    assert requests <= 1


def test_a_revoke_on_another_replica_stops_the_push_within_one_batch(
    secrets, monkeypatch
):
    """No ``stop`` here: only the stored revoke, as another replica would see it."""
    from tending.fixture_repository import FixtureRepository

    server = FakeCaldav()

    async def run() -> tuple[str, int, int]:
        repo = FixtureRepository()
        created = await repo.create_feed(
            {"member_id": MEMBER, "name": "Old phone", "push_target": "caldav"}
        )
        feed_id = str(created["id"])
        provision(secrets, feed_id)

        async def on_first() -> None:
            await repo.revoke_feed(feed_id)

        monkeypatch.setattr(
            push,
            "client_factory",
            lambda _t: httpx.AsyncClient(transport=_held_transport(server, on_first)),
        )
        from tending import service

        now = datetime.now(UTC)
        await service.generate_tasks(repo, today=now.date())
        window = await service.window_tasks(repo, now)
        owed = len(service.feed_events(window, created))
        result = await push.push_feed(
            repo, feed_id, base_url="http://localhost:8000", window=window, now=now
        )
        return result, len(server.puts()), owed

    result, puts, owed = asyncio.run(run())
    assert owed > push.PUSH_BATCH, "a feed big enough to need more than one batch"
    assert result == "off"
    assert puts <= push.PUSH_BATCH
