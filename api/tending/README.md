# Scheduling & Rules — the scheduler

Care rules, tasks, recurrence, completion logging and the tokenized ICS feeds.
Implements the `tending` paths of `contracts/openapi/openapi.yaml`; the contract
is frozen, so nothing here changes a response shape.

## Layout

| Module | What it does |
| --- | --- |
| `router.py` | HTTP only. Validates, delegates, serialises. |
| `service.py` | Generation on read, Morning Rounds, completion, feed rendering. |
| `domain.py` | The engine, pure: occurrences, identity, modifiers, seasons. |
| `defaults.py` | The care rules a fresh install gets, and what they are worth. |
| `titles.py` | the original-theme rule in one place: themed title and plain title, always paired. |
| `ics.py` | RFC 5545, via `icalendar`. |
| `push.py` | Calendar push: when a CalDAV feed owes one, and what it sends. |
| `tokens.py` | The one credential this application issues. |
| `frost.py` | The frost guard's scheduling half: an alert becomes a task. |
| `relocation.py` | The one call into the inventory API's write, for a plant that moves. |
| `environment.py` | The single seam onto the weather engine. |
| `repository.py` | The storage protocol, and which implementation answers. |
| `fixture_repository.py` | In-memory schedule seeded from `fixtures/` — mock mode. |
| `database_repository.py` | SQLAlchemy Core on Postgres — live mode. |
| `tables.py` | Core table metadata mirroring `contracts/schema/001_init.sql` and migration 007. |
| `db.py` | The engine, borrowed from the inventory API rather than duplicated. |

## The rules this code exists to keep

### A task's identity is its occurrence, never its due date

This is the one to read first, because it is the one that cannot be retrofitted.

A task id — and therefore its `ics_uid` — is a pure function of the *occurrence*
a rule generates: the nth cycle since the last time the job was actually done.
It does not contain the due date. Stretch a watering by four days for winter and
it is the same occurrence on a later day: same UID, `SEQUENCE` bumped, and the
subscriber's calendar moves the event it already has.

The earlier mock keyed the UID on the due date, which is stable right up until
something reschedules — and then every reschedule is a second event in
somebody's calendar, permanently, with no way to withdraw the first.

Completion moves the anchor. That retires the whole cycle counted from the old
one: those occurrences are now fiction, so they are marked `cancelled` rather
than deleted, because a subscribed feed can only say "this is gone" by saying
it. New cycles get new identities, which is correct — they are new jobs.

### The original-theme rule is a `NOT NULL` pair, not a style note

`title` and `plain_title` are both `NOT NULL` in the frozen schema. Everything
goes through `titles.titles_for`, so there is no code path that can produce one
without the other. A calendar SUMMARY reads `Tend Gilderoy — water 450 ml`: the
themed phrase names the plant, the plain half says what to do, and a person
reading their work calendar at seven in the morning gets an instruction rather
than a puzzle. The full plain title leads the event body.

### Nothing here invents a plant fact

Only modifiers a rule actually carries are applied. There is no ambient table of
"what plants like in winter" in this package and there must not be one — a
multiplier nobody configured is a care value nobody cited, wearing arithmetic.

The rules a fresh install gets are derived strictly from what the botany worker has
attested:

| What the botany worker has | What this package does |
| --- | --- |
| A cited interval | A rule at that citation's confidence |
| An uncited interval | A rule at `unknown`, and every task it generates carries the reason in `detail` |
| A per-specimen override | The household's own instruction, which outranks the species |
| No interval at all | **No rule**, and the plant is named in the rounds' `unscheduled` list with the reason |

That last row matters. A plant that silently drops off the schedule looks
exactly like a plant that needs nothing, which is the failure the design spends
two pages naming in the weather engines. It arrives here through the door marked
"sensible default", and is refused at it.

Ten of the twelve fixture species carry an uncited watering interval, so the
marked path is the common one, not the edge case.

### Certainty is carried through, never laundered

The weather engine's water balance returns `confidence`, `degraded` and
`degradations[]`. A task generated from it carries all three, plus
this package's own caveat when the balance series ends before the day it is
being used to schedule. The plain-language version goes on `detail`, which is in
the frozen contract, so a client that knows nothing about the structured fields
still shows the reader that the instruction is a guess.

Under the design nothing measures the soil, so where the weather engine's model has an opinion it
is the *only* authority: an outdoor plant the balance calls comfortable does not
also get an interval watering behind the model's back. The interval is the
fallback for plants the model declines to judge, and nothing else.

### A frost alert is answered, and let go of

The weather engine raises the alert; this package raises the *task*, and an earlier release is the
releases where `FrostAlert.task_id` stopped being `null`. Four decisions are worth
reading, and all four are written out in `frost.py`:

- **`monitor` is deliberately not a task.** It is the weather engine's word for "watching,
  nothing to do", and a task nobody can perform is what teaches a household to
  tick things off without reading them. The alert is still shown in Morning
  Rounds, which is where a thing to watch belongs.
- **A frost task's identity is the night, not the deadline.** The night is its
  anchor and `OUTSTANDING_INDEX` its index, so a sunset that moves or an
  advisory that arrives late updates the event the subscriber already has. A
  different *night* is a different job, and the one it replaces is withdrawn.
- **The plant goes back out after three consecutive forecast nights above its
  own threshold** — the plan's rule and the frost scenario's, not this
  package's. The threshold is the one E states on the alert; it is never
  recomputed here from a species minimum and a margin, because that arithmetic
  is `workers/weather/tasks.frost_threshold_c` and a second copy of it is the
  failure this package spends the rest of this file avoiding. The nights counted
  are the ones *after* the cold night the plant came in for: counting from the
  day it was carried inside counts the mild evenings before the freeze and sends
  it back out into it.
- **A withdrawn task is `satisfied`/`forecast_change`, never deleted.** A
  forecast that changes is the normal case. On screen the task says the frost
  passed; in the calendar the event is cancelled by UID with a bumped
  `SEQUENCE`, because a subscribed feed has no other way to say "this is gone".
  A task whose deadline has *already* passed is left exactly as it is: it was
  missed, not withdrawn, and "satisfied by a change in the forecast" would be a
  lie told about a plant that froze.

And a frost task says, in words, on `detail`, that it rests on a forecast. the design says nothing measures the soil in this house; nothing measures the air where
the plant stands either, and an instruction that implies otherwise is worse than
a hedged one.

### A completion that moves a plant moves it

Completing a `bring_indoors` or `return_outdoors` task with a `new_location_id`
calls the inventory API's own `update_specimen` (`relocation.py`) — one import of
somebody else's module, in a file that does nothing else. The inventory API's store keeps the
denormalised `is_outdoor` flag in step with the location, which is exactly why
the move goes through C rather than being re-derived here.

The move happens *before* the completion. A relocation that cannot be performed
refuses the whole request and ticks nothing off: a 200 over a plant still
standing in a freeze is the failure an earlier release exists to close. And because the contract
documents `new_location_id` as "set when completing a bring_indoors task", a
completion of anything else that carries one is refused rather than obeyed or
quietly dropped.

### The feed token is a credential

It is the only one this application issues. Minted from `secrets`,
one per feed, never logged — this package imports no logger and calls no
`print`, and a test asserts it — compared in constant time, and rotated as well
as flagged on revoke, so a revoked URL stops resolving rather than merely being
marked. A revoked feed publishes no URL at all. An unknown token and a revoked
one get the same 404: distinguishing them tells an unauthenticated caller that a
token they hold was once real.

### The feed list is never stored by anybody

`GET` and `POST /tending/feeds` answer `Cache-Control: no-store`, and so do a
refused create and the ICS 404: every feed in the list carries its
tokenised address. Contract 2.0.0 (A, an earlier release) withholds the address from the list
altogether; until then, nothing keeps a copy of it.

## Calendar push

A feed with `push_target: caldav` pushes its events to the household's own
CalDAV calendar through the hub's adapter (`workers.hub.calendar`).
`push_target: google` is refused with a 422 and a sentence: Google push needs an
OAuth client and a token store this project does not have.

- **What** is exactly what the ICS feed serves for the same feed — one window
  read (`service.window_tasks`), the same filters and one-per-UID rule
  (`service.feed_events`), each event from `ics.event_for`. A task that leaves a
  feed while still in its window (its plant was carried indoors and the feed is
  outdoor-only) is pushed once as `STATUS:CANCELLED`, because a subscriber's
  calendar drops it and nobody `DELETE`s.
- **When**: a feed *owes* a push when one of its events has a UID or `SEQUENCE`
  the server was not sent, read against `push_state` — the adapter's own
  idempotence rule, asked as a question. It is asked after every request that
  runs generation or changes the schedule (a FastAPI background task), and by a
  sweep every 60 s in each API process that runs generation itself, which is how
  weather that settled a task is found while nobody has the app open. Owing sets
  `push_dirty_since`; a clean push that started after it clears it.
- **Every change bumps `SEQUENCE`.** Only a moved due date did, so rain
  settling a task cancelled its event at the old sequence — a client may ignore
  that, and push never sent it.
- **Revoke stops it at once.** The revoke cancels the push in flight in its
  process; every push re-reads its feed between batches of eight events, which
  stops one running on the other replica within a batch.
- **`push_status`** is derived, never stored: `off`, `awaiting_operator` (no
  `moh_caldav_<feed_id>` secret yet — a setup step), `failing` (`push_error` is
  set), `ok`. `push_error` is the hub's redacted sentence, run through
  `workers.hub.credentials.credential_reason` again and refused whole if it
  carries anything credential-shaped or the feed's token.
- **Nothing secret is kept or served.** The CalDAV credential lives only in the
  operator's secret file and the hub's adapter reads it at push time; `push_config`
  stays `{}` and `push_state` is never served. Nothing in this package logs: a
  push that cannot run leaves its feed owing, and the sweep tries again.

## Two modes, one protocol

`MOH_MOCK_MODE=true` (the default, the design) serves the whole API from
`fixtures/`, writes included — completion, feed creation and revocation all work
there, because the earlier exit criterion is demonstrated on the mock stack before it
is demonstrated on a deployment. Mock-mode writes live in the process; restart
the API and the schedule regenerates from the fixtures.

Set it false with `MOH_DATABASE_URL` and the same router talks to Postgres,
which is what `infra/stack/docker-stack.yml` does.

## Generation runs on read

Every endpoint that needs today's schedule materialises it first. Because every
task id is a pure function of its occurrence, running it twice writes nothing
the first run did not.

**This is a deliberate shape, and it has a cost worth stating.** The natural
home for a nightly rule evaluation is an Arq job, and `workers/` belongs to
another parts of the project — reaching in would break the ownership rule, so the scheduled job is
escalated rather than smuggled. Morning Rounds therefore does the generation
work on the request. That is fine for one household's dozen plants and would not
be fine for a thousand. The seam is `service.generate_tasks`: a worker calls the
same function on a schedule and these endpoints become pure reads, with no other
change.

## What is not here

- **A Google push.** Refused, above. **A real CalDAV server** has not been
  pushed to from this package's tests: they use a fake in the hub's style, and an
  HTTPS fake for the running-app check.
- **"Satisfied by rain" is an earlier release's**, with the weather engine. The state is *consumed* — when
  The weather engine's balance says a watering was satisfied, the task says so and the calendar
  cancels the event — but nothing in this package computes it. The baseline
  weather fixture has no rain on its closing days, so the mock stack currently
  shows an empty `satisfied` list; the path is covered by unit tests rather than
  by the fixture. The frost guard's withdrawal writes the same `satisfied` state
  for its own reason (`forecast_change`), and that one *is* driven end to end.
- **Future outdoor waterings are not projected.** Working out which day a
  deficit will next cross its threshold is the weather engine's engine. A `water_balance` rule
  produces the single outstanding watering, held at one identity for as long as
  it goes undone. Indoor interval rules fill the calendar's horizon.
- **A return date for a plant that is *already* indoors.** Once a plant has
  actually been moved inside it leaves the weather engine's frost guard — an indoor plant is never
  frost-alerted — so nothing states a threshold to judge a return against any
  more. Guessing one from a species minimum would invent the care value this
  project refuses to invent, and "the next three nights look mild" in January
  would carry a citrus out to die. The plant is named in Morning Rounds'
  `unscheduled` list with that reason instead, and the fix is asked of A: either
  a threshold the specimen carries, or an alert the weather engine keeps raising for a plant it
  has put indoors. In mock mode the fixtures keep the alert open, so the return
  suggestion is demonstrable there today.
- **A worker.** Generation still runs on read, for the reason below.

## Tests

They live in `tests/` inside this package, because the ownership rule puts the repository's
top-level `tests/` in the test suite's hands.

```
.venv/bin/pytest api/tending -q              # no database, no network
```

`test_tending_frost_guard.py` resets the inventory API's mock Register around each of
its end-to-end tests as well as this package's schedule: a relocation is a write
into the inventory API's store, and one test's moved lemon must not be the next test's starting
position.

The suite is network-free by construction: an autouse fixture fails any test
that opens a socket.

The live-Postgres suite skips unless it is given a database it may create tables
in:

```
MOH_TEST_DATABASE_URL=postgresql+asyncpg://herbology@127.0.0.1:5432/herbology_test \
  .venv/bin/pytest api/tending -q
```

It cuts its tables out of `contracts/schema/001_init.sql` rather than retyping
them, so a column that moves in the frozen schema breaks the tests instead of
quietly passing them.
