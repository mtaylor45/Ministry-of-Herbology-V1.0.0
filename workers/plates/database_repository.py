"""The journal, against Postgres.

Mirrors ``grounds.database_repository``: SQLAlchemy Core over the tables in
``tables.py``, which mirror the frozen schema and never create it.

Two things the schema already decided, which this module leans on rather than
re-checking:

* ``CHECK (origin <> 'public_domain' OR license IS NOT NULL)`` — the database
  refuses an unsupported public-domain claim even if something upstream of here
  got it wrong. ``domain.Plate`` refuses first, so the constraint is a second
  fence and not the only one.
* ``approved boolean NOT NULL DEFAULT false`` with ``approved_by`` beside it —
  the row was built for approval to have an author, which is the argument in
  ``repository.py`` made in DDL a releases before anybody implemented it.

Plate images are **not** in the database. ``image_key`` names an object on the
operator's volume, and `storage.FilesystemPlateStore` is the only
thing that reads it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from . import storage
from .config import get_plate_settings
from .coverage import Coverage, build, generated_count, live_absence
from .domain import Plate
from .repository import (
    EmptyNoteError,
    Record,
    UnknownMemberError,
    UnknownPlateError,
    UnknownSpecimenError,
)
from .tables import field_note, member, plate


class DatabaseRepository:
    """Live mode. One engine, handed in, so tests can point at a throwaway."""

    def __init__(
        self, engine: AsyncEngine, store: storage.PlateImageStore | None = None
    ) -> None:
        self._engine = engine
        self._store = store

    def _image_store(self) -> storage.PlateImageStore:
        if self._store is not None:
            return self._store
        from .router import plate_store

        return plate_store()

    # ------------------------------------------------------------------ reads

    async def list_plates(self, approved: bool | None = None) -> list[Record]:
        query = select(plate).order_by(plate.c.created_at.asc(), plate.c.id.asc())
        if approved is not None:
            query = query.where(plate.c.approved.is_(approved))
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query)).mappings().all()
        return [dict(row) for row in rows]

    async def get_plate(self, plate_id: str) -> Record | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(plate).where(plate.c.id == _as_uuid(plate_id))
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    async def plate_image(self, plate_id: str, *, thumb: bool = False) -> bytes:
        row = await self.get_plate(plate_id)
        if row is None:
            raise UnknownPlateError(plate_id)
        key = (row.get("thumb_key") if thumb else None) or row["image_key"]
        return self._image_store().get(str(key))

    async def list_notes(self, specimen_id: str) -> list[Record]:
        query = (
            select(field_note, member)
            .join(member, field_note.c.written_by == member.c.id, isouter=True)
            .where(field_note.c.specimen_id == _as_uuid(specimen_id))
            .order_by(field_note.c.written_at.asc())
        )
        async with self._engine.connect() as connection:
            if not await self._specimen_exists(connection, specimen_id):
                raise UnknownSpecimenError(specimen_id)
            rows = (await connection.execute(query)).mappings().all()
        return [_note_record(row) for row in rows]

    # ----------------------------------------------------------------- writes

    async def create_plate(self, plate_model: Plate) -> Record:
        values = {
            "id": _as_uuid(plate_model.id),
            "species_id": _as_uuid(plate_model.species_id),
            "specimen_id": _as_uuid(plate_model.specimen_id),
            "image_key": plate_model.image_key,
            "thumb_key": plate_model.thumb_key,
            "origin": plate_model.origin,
            "source_id": _as_uuid(plate_model.source_id),
            "license": plate_model.license,
            "attribution": plate_model.attribution,
            "style": plate_model.style,
            # Never true on insert. The pipeline cannot approve, and a row that
            # arrived approved did not come from the pipeline.
            "approved": plate_model.approved,
            "approved_by": _as_uuid(plate_model.approved_by),
            "created_at": datetime.now(UTC),
        }
        async with self._engine.begin() as connection:
            await connection.execute(plate.insert().values(**values))
        created = await self.get_plate(plate_model.id)
        assert created is not None  # just inserted
        return created

    async def approve_plate(self, plate_id: str, member_id: str) -> Record:
        """Set ``approved`` and ``approved_by`` in one statement.

        One statement on purpose: two would admit a moment where the row says
        approved with nobody attached, which `domain.Plate` treats as
        malformed. The ``RETURNING``-free read afterwards keeps this mirroring
        ``get_plate`` rather than hand-rolling a row shape.
        """
        async with self._engine.begin() as connection:
            if not await self._member_exists(connection, member_id):
                raise UnknownMemberError(member_id)
            result = await connection.execute(
                plate.update()
                .where(plate.c.id == _as_uuid(plate_id))
                .values(approved=True, approved_by=_as_uuid(member_id))
            )
            if result.rowcount == 0:
                raise UnknownPlateError(plate_id)
        row = await self.get_plate(plate_id)
        assert row is not None  # just updated
        return row

    async def create_note(
        self, specimen_id: str, body: str, member_id: str | None = None
    ) -> Record:
        if not body or not body.strip():
            raise EmptyNoteError(
                "A field note is somebody's observation, and an empty one is a "
                "row implying an observation nobody made."
            )
        note_id = uuid.uuid4()
        async with self._engine.begin() as connection:
            if not await self._specimen_exists(connection, specimen_id):
                raise UnknownSpecimenError(specimen_id)
            if member_id is not None and not await self._member_exists(
                connection, member_id
            ):
                raise UnknownMemberError(member_id)
            await connection.execute(
                field_note.insert().values(
                    id=note_id,
                    specimen_id=_as_uuid(specimen_id),
                    body=body.strip(),
                    written_at=datetime.now(UTC),
                    written_by=_as_uuid(member_id),
                )
            )
        notes = await self.list_notes(specimen_id)
        return next(note for note in notes if note["id"] == note_id)

    async def coverage(self) -> Coverage:
        """One entry per specimen, in register order.

        **What a live deployment honestly cannot say.** The frozen schema has
        no column for a sourcing outcome: `plate` records plates that exist and
        nothing about attempts that produced none. So this cannot distinguish
        "every catalogue was asked and none had it" from "the worker has never
        run", and it does not try — `coverage.live_absence` returns `not_run`
        with a sentence that says exactly that, which is the kind the design
        put in the closed set for this case.

        The one cause it *can* establish is `store_unavailable`, because that
        is a fact about this deployment's configuration right now rather than
        about a past run. Escalated in `README.md` rather than papered over.
        """
        plates = await self.list_plates()
        specimens = await self._register()
        configured = (
            self._store is not None or get_plate_settings().image_dir is not None
        )
        absence = live_absence(configured)
        return build(specimens, plates, lambda _specimen: absence)

    async def generated_for_report(self) -> int:
        return generated_count(await self._register(), await self.list_plates())

    async def _register(self) -> list[Record]:
        """Every specimen, in register order, with what `SpecimenBrief` needs.

        Raw SQL: `specimen` is the inventory API's table and is deliberately not in
        this package's `tables.py`, which holds only the columns the journal
        reads or writes of its own. The display-name rule is the inventory API's too — nickname,
        else the species' first common name, else the accepted name — and is
        done here in SQL rather than reimplemented in Python so the Register and
        the journal cannot call one plant two different things.

        **"Register order" means the inventory API's order**, and the `ORDER BY` below is the
        one `inventory.database_repository.list_specimens` uses: `created_at`
        then `id`. The book pairs these entries with the plants `GET /specimens`
        returned, so a different order here would silently mis-pair every leaf
        after the first difference — the kind of defect that looks like a
        rendering bug and is a join bug. Checked against the inventory API's implementation
        rather than assumed; if the inventory API's ordering changes, this follows it.
        """
        from sqlalchemy import text

        query = text("""
            SELECT s.id,
                   s.species_id,
                   s.is_outdoor,
                   COALESCE(
                       NULLIF(s.nickname, ''),
                       INITCAP(sp.common_names[1]),
                       sp.accepted_name,
                       'Unnamed specimen'
                   ) AS display_name
            FROM specimen s
            LEFT JOIN species sp ON sp.id = s.species_id
            ORDER BY s.created_at ASC, s.id ASC
            """)
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query)).mappings().all()
        return [dict(row) for row in rows]

    # --------------------------------------------------------------- helpers

    async def _specimen_exists(self, connection: Any, specimen_id: str) -> bool:
        """Checked with raw SQL: ``specimen`` is the inventory API's table and not in
        ``tables.py``."""
        from sqlalchemy import text

        row = (
            await connection.execute(
                text("SELECT 1 FROM specimen WHERE id = :id"),
                {"id": _as_uuid(specimen_id)},
            )
        ).first()
        return row is not None

    async def _member_exists(self, connection: Any, member_id: str) -> bool:
        row = (
            await connection.execute(
                select(member.c.id).where(member.c.id == _as_uuid(member_id))
            )
        ).first()
        return row is not None


def _note_record(row: Any) -> Record:
    """Flatten the note-join into the shape ``schemas.note_out`` expects."""
    mapping = dict(row)
    author = (
        {
            "id": mapping["id_1"] if "id_1" in mapping else mapping.get("member_id"),
            "name": mapping.get("name"),
            "role": mapping.get("role"),
            "notify_prefs": mapping.get("notify_prefs") or {},
        }
        if mapping.get("name")
        else None
    )
    return {
        "id": mapping["id"],
        "specimen_id": mapping["specimen_id"],
        "body": mapping["body"],
        "written_at": mapping["written_at"],
        "written_by": mapping.get("written_by"),
        "member": author,
    }


def _as_uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
