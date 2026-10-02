"""Care rules, tasks, Morning Rounds and calendar feeds.

decisions live in ``tending.service`` and ``tending.domain``, and storage is
``FixtureRepository`` when ``MOH_MOCK_MODE=true`` and ``DatabaseRepository``
when a Postgres is attached.

Two things the earlier mock's docstring called contract rather than mock detail, and
was right about both, are kept and hardened:

* every task carries a themed ``title`` *and* a ``plain_title`` — see ``tending.titles``;
* the ICS UID is stable per task. The mock derived it from the due date, which
  is stable only until something reschedules; it is now derived from the
  occurrence's identity, so a moved task updates its calendar event in place
  instead of leaving a second one behind. See ``tending.domain``.

No route is added here that ``contracts/openapi/openapi.yaml`` does not declare.
"""

from datetime import datetime
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)

from app.settings import get_settings
from tending import push, schemas, service
from tending.relocation import UnknownLocationError
from tending.relocation import UnknownSpecimenError as MovedSpecimenMissingError
from tending.repository import (
    Completion,
    TaskQuery,
    TendingRepository,
    UnknownFeedError,
    UnknownMemberError,
    UnknownSpecimenError,
    get_repository,
)
from tending.service import MisplacedRelocationError
from tending.titles import TASK_TYPES


def _base_url() -> str:
    return get_settings().public_base_url


#: The calendar push sweep runs for the app's lifetime (``tending.push``): it
#: is what finds weather that settled a task while nobody had the app open.
router = APIRouter(tags=["tending"], lifespan=push.sweeping(get_repository, _base_url))

Repo = Depends(get_repository)


def _push_after(
    background: BackgroundTasks, repo: TendingRepository, *, changed: bool = False
) -> None:
    """After the response: push any CalDAV feed this request left owing one.

    Added to every request that runs generation or changes the schedule,
    because generation is where rain, sensors, re-anchoring and frost
    withdrawal are discovered. A read has just generated, so its push reads
    the store as it stands. A write (``changed``) generates once more first:
    a completion re-anchors the plant's later occurrences, and those exist
    only after the next pass. With no CalDAV feed, either costs one read.
    """
    background.add_task(push.after_change, repo, _base_url(), generate=changed)


#: the design. Every feed in a list carries its tokenised address, and the
#: token is the only credential this app issues to a person, so no browser or
#: proxy may keep a copy of any response that carries one — or of a refusal
#: for a URL that had one in it.
NO_STORE = {"Cache-Control": "no-store"}

#: What a create may ask for. ``google`` is in the contract's enum and refused.
PUSH_TARGETS = frozenset({"none", "caldav"})

GOOGLE_REFUSED = (
    "Google push is not available in this version of the Ministry. Subscribe "
    "to this feed's address in Google Calendar instead — Google refreshes a "
    "subscribed calendar on its own schedule, often twelve hours or more — or "
    "use push_target caldav with a CalDAV calendar."
)


# ----------------------------------------------------------------- the rounds


@router.get("/tending/rounds")
async def get_morning_rounds(
    background: BackgroundTasks,
    on: str | None = None,
    repo: TendingRepository = Repo,
) -> dict[str, Any]:
    """Morning Rounds — what needs doing today, and what could not be judged."""
    day = None
    if on:
        try:
            day = datetime.fromisoformat(on).date()
        except ValueError:
            raise HTTPException(status_code=422, detail="Malformed date") from None
    body = await service.morning_rounds(repo, day)
    _push_after(background, repo)
    return body


# ----------------------------------------------------------------------- tasks


@router.get("/tending/tasks")
async def list_tasks(
    background: BackgroundTasks,
    status_: str | None = Query(default=None, alias="status"),
    specimen_id: str | None = None,
    due_before: datetime | None = None,
    due_after: datetime | None = None,
    repo: TendingRepository = Repo,
) -> list[dict[str, Any]]:
    tasks = await service.list_tasks(
        repo,
        TaskQuery(
            status=status_,
            specimen_id=specimen_id,
            due_before=due_before,
            due_after=due_after,
        ),
    )
    _push_after(background, repo)
    return tasks


@router.post("/tending/tasks/complete-batch")
async def complete_tasks(
    body: schemas.BatchCompletion,
    background: BackgroundTasks,
    repo: TendingRepository = Repo,
) -> list[dict[str, Any]]:
    """Batch completion — what the Morning Rounds screen sends.

    Declared before the single-task route so that ``complete-batch`` is never
    read as a ``task_id``. Unknown or already-finished ids are skipped rather
    than refused: a batch of six where one was completed on a phone thirty
    seconds ago should tick off the other five, not fail the lot.
    """
    try:
        completed = await service.complete(
            repo,
            [str(task_id) for task_id in body.task_ids],
            Completion(completed_by=body.completed_by),
        )
    except UnknownMemberError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    _push_after(background, repo, changed=True)
    return completed


@router.post("/tending/tasks/{task_id}/complete")
async def complete_task(
    task_id: str,
    background: BackgroundTasks,
    body: schemas.TaskCompletion | None = None,
    repo: TendingRepository = Repo,
) -> dict[str, Any]:
    """One-tap completion, attributed to a member and logged as a task event.

    A ``bring_indoors`` completion also *moves* the plant, through the inventory API's
    own write. A move that cannot be performed
    refuses the whole request: a 200 over a plant still standing in a freeze is
    the failure this release closes, so nothing is ticked off unless the plant
    actually went somewhere.
    """
    body = body or schemas.TaskCompletion()
    try:
        completed = await service.complete(
            repo,
            [task_id],
            Completion(
                completed_by=body.completed_by,
                amount_ml=body.amount_ml,
                notes=body.notes,
                new_location_id=body.new_location_id,
            ),
        )
    except (
        UnknownMemberError,
        UnknownLocationError,
        MovedSpecimenMissingError,
        MisplacedRelocationError,
    ) as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    if not completed:
        raise HTTPException(status_code=404, detail="No such open task")
    _push_after(background, repo, changed=True)
    return completed[0]


# ------------------------------------------------------------------ care rules


@router.get("/tending/care-rules")
async def list_care_rules(
    specimen_id: str | None = None, repo: TendingRepository = Repo
) -> list[dict[str, Any]]:
    rows = await repo.care_rules(specimen_id)
    return [schemas.care_rule_out(row) for row in rows]


@router.post("/tending/care-rules", status_code=201)
async def create_care_rule(
    body: schemas.CareRuleCreate,
    background: BackgroundTasks,
    repo: TendingRepository = Repo,
) -> dict[str, Any]:
    if body.task_type not in TASK_TYPES:
        raise HTTPException(
            status_code=422, detail=f"Unknown task type: {body.task_type}"
        )
    if not body.species_id and not body.specimen_id:
        raise HTTPException(
            status_code=422,
            detail="A care rule applies to a species or a specimen; give one.",
        )
    try:
        row = await repo.create_care_rule(body.model_dump())
    except UnknownSpecimenError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    # A new rule is generated into tasks on the next read; the push after this
    # one, or the sweep, carries them. Pushing here is cheap and harmless.
    _push_after(background, repo, changed=True)
    return schemas.care_rule_out(row)


# ---------------------------------------------------------------------- feeds


@router.get("/tending/feeds")
async def list_calendar_feeds(
    response: Response, repo: TendingRepository = Repo
) -> list[dict[str, Any]]:
    response.headers.update(NO_STORE)
    base, hub = _base_url(), push.hub_settings()
    return [
        schemas.feed_out(row, base_url=base, push_status=push.status_of(row, hub))
        for row in await repo.feeds()
    ]


@router.post("/tending/feeds", status_code=201)
async def create_calendar_feed(
    body: schemas.CalendarFeedCreate,
    response: Response,
    background: BackgroundTasks,
    repo: TendingRepository = Repo,
) -> dict[str, Any]:
    """One feed per member and filter set, at its own tokenized URL.

    ``push_target: google`` is refused rather than accepted and never honoured: Google push needs an
    OAuth client and a per-member token
    store this project does not have. The enum keeps the value for a later
    version; this one says so in a sentence.
    """
    response.headers.update(NO_STORE)
    if body.push_target == "google":
        raise HTTPException(status_code=422, detail=GOOGLE_REFUSED, headers=NO_STORE)
    if body.push_target not in PUSH_TARGETS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown push target: {body.push_target}. " "Use caldav or none.",
            headers=NO_STORE,
        )
    try:
        row = await repo.create_feed(body.model_dump())
    except UnknownMemberError as error:
        raise HTTPException(
            status_code=422, detail=str(error), headers=NO_STORE
        ) from None
    if push.is_pushing(row):
        _push_after(background, repo, changed=True)
    return schemas.feed_out(row, base_url=_base_url(), push_status=push.status_of(row))


@router.post("/tending/feeds/{feed_id}/revoke", status_code=204)
async def revoke_calendar_feed(
    feed_id: str, repo: TendingRepository = Repo
) -> Response:
    """Revoke one feed. The others keep working — that is the whole point.

    The token is rotated as well as marked revoked, so the URL somebody pasted
    into a calendar stops resolving immediately rather than merely being
    flagged. Its calendar push stops too: every push re-reads its feed under
    that feed's lock and a revoked feed is never pushed or written to again. No other feed's row,
    state or secret is touched.
    """
    try:
        await repo.revoke_feed(feed_id)
    except UnknownFeedError:
        raise HTTPException(status_code=404, detail="No such feed") from None
    push.stop(feed_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/calendar/{token}.ics")
async def get_calendar_ics(
    token: str, background: BackgroundTasks, repo: TendingRepository = Repo
) -> Response:
    """The ICS feed itself. Unauthenticated — the token is the secret.

    A revoked or unknown token gets the same 404. Distinguishing them would
    confirm to an unauthenticated caller that a token they hold was once real.
    """
    document = await service.render_feed(repo, token, base_url=_base_url())
    if document is None:
        raise HTTPException(
            status_code=404, detail="No such calendar feed", headers=NO_STORE
        )
    # A subscriber's refresh runs generation, which may have found rain.
    _push_after(background, repo)
    return Response(
        document,
        media_type="text/calendar; charset=utf-8",
        headers={
            # Neither a proxy nor a browser should hold a copy of a document
            # fetched with a credential in its URL.
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'inline; filename="ministry-of-herbology.ics"',
        },
    )
