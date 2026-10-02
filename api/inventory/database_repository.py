"""The live Register, on Postgres.

Same protocol as the fixture store, so the router is unchanged between mock and
live mode. Reads hydrate a page of specimens with three extra queries — one for
locations, one for species, one for portraits — rather than one per row; writes
run in a single transaction so the ``is_outdoor`` invariant cannot be observed
half-applied, and a move and its ``relocate`` log entry land together.

Photographs: the row holds ``image_key``; the bytes are on the operator's
volume behind ``photo_images``, which is ``None`` when ``MOH_PHOTOS_IMAGE_DIR``
is unset — the lists still answer, the upload and the image route refuse. ``Photo.log_entry_id`` is
``log_entry.photo_id`` read backwards, as a correlated subquery rather than the outer join the
design
names: the schema does not make ``photo_id`` unique, and an outer join would
hand back one photo row per citing entry. The earliest entry wins, so the
answer is deterministic either way.

The statement builders are module-level functions so their shape can be
asserted by compiling them against the Postgres dialect without a database
(``tests/test_inventory_sql_shape.py``); the live suite still skips unless one
is attached.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from inventory.domain import (
    ARCHIVED_STATUS,
    RELOCATE_KIND,
    is_group_for,
    is_outdoor_for,
    normalise_sun_exposure,
    relocation_data,
)
from inventory.photos import PhotoImageStore, thumb_key_for
from inventory.repository import (
    Record,
    SpecimenPage,
    SpecimenQuery,
    UnknownLocationError,
    UnknownMemberError,
    UnknownPhotoError,
    UnknownSpeciesError,
    UnknownSpecimenError,
)
from inventory.schemas import photo_url
from inventory.tables import (
    SPECIMEN_WRITABLE,
    location,
    log_entry,
    member,
    photo,
    site,
    species,
    specimen,
)


class NoSiteError(LookupError):
    """A location was created before any site existed. The router answers 422."""

    def __init__(self) -> None:
        super().__init__("No site exists yet; create one before adding locations.")


def _as_uuid(value: Any) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


#: A location's live specimen count, excluding archived plants. Correlated so it
#: rides along with whichever locations the outer query selected.
_SPECIMEN_COUNT = (
    select(func.count())
    .select_from(specimen)
    .where(specimen.c.location_id == location.c.id, specimen.c.archived_at.is_(None))
    .correlate(location)
    .scalar_subquery()
    .label("specimen_count")
)


#: ``log_entry.photo_id`` read backwards: the earliest entry citing a photo,
#: correlated to the photo row it rides along with. See the module docstring
#: for why this is a subquery and not the outer join the design names.
_LOG_ENTRY_ID = (
    select(log_entry.c.id)
    .where(log_entry.c.photo_id == photo.c.id)
    .order_by(log_entry.c.occurred_at, log_entry.c.id)
    .limit(1)
    .correlate(photo)
    .scalar_subquery()
    .label("log_entry_id")
)


def photos_statement(specimen_id: Any, order: str) -> Select[Any]:
    """One specimen's photographs with their citing entry, in ``?order=``."""
    stmt = select(photo, _LOG_ENTRY_ID).where(
        photo.c.specimen_id == _as_uuid(specimen_id)
    )
    if order == "oldest":
        return stmt.order_by(photo.c.taken_at.asc(), photo.c.id.asc())
    return stmt.order_by(photo.c.taken_at.desc(), photo.c.id.desc())


def own_photo_statement(specimen_id: Any, photo_id: Any) -> Select[Any]:
    """A photo *of this specimen*, or nothing: the same id under another plant
    is nothing."""
    return select(photo, _LOG_ENTRY_ID).where(
        photo.c.id == _as_uuid(photo_id),
        photo.c.specimen_id == _as_uuid(specimen_id),
    )


def log_entries_statement(specimen_id: Any, order: str) -> Select[Any]:
    """One specimen's log in ``?order=`` over ``occurred_at``."""
    stmt = select(log_entry).where(log_entry.c.specimen_id == _as_uuid(specimen_id))
    if order == "oldest":
        return stmt.order_by(log_entry.c.occurred_at.asc(), log_entry.c.id.asc())
    return stmt.order_by(log_entry.c.occurred_at.desc(), log_entry.c.id.desc())


def portraits_statement(specimen_ids: set[Any]) -> Select[Any]:
    """Each listed specimen's primary photograph, for ``primary_photo_url``."""
    return select(photo.c.specimen_id, photo.c.id).where(
        photo.c.specimen_id.in_(specimen_ids), photo.c.is_primary.is_(True)
    )


class DatabaseRepository:
    def __init__(
        self, engine: AsyncEngine, photo_images: PhotoImageStore | None = None
    ) -> None:
        self._engine = engine
        self.photo_images = photo_images

    # ---------------------------------------------------------------- reading

    async def _locations_by_id(
        self, conn: AsyncConnection, ids: set[Any]
    ) -> dict[Any, Record]:
        if not ids:
            return {}
        rows = await conn.execute(
            select(location, _SPECIMEN_COUNT).where(location.c.id.in_(ids))
        )
        return {r.id: dict(r._mapping) for r in rows}

    async def _species_by_id(
        self, conn: AsyncConnection, ids: set[Any]
    ) -> dict[Any, Record]:
        if not ids:
            return {}
        rows = await conn.execute(select(species).where(species.c.id.in_(ids)))
        return {r.id: dict(r._mapping) for r in rows}

    async def _portraits_by_specimen(
        self, conn: AsyncConnection, ids: set[Any]
    ) -> dict[Any, Any]:
        if not ids:
            return {}
        rows = await conn.execute(portraits_statement(ids))
        return {r.specimen_id: r.id for r in rows}

    async def _hydrate(self, conn: AsyncConnection, rows: list[Record]) -> list[Record]:
        locations = await self._locations_by_id(
            conn, {r["location_id"] for r in rows if r.get("location_id")}
        )
        taxa = await self._species_by_id(
            conn, {r["species_id"] for r in rows if r.get("species_id")}
        )
        portraits = await self._portraits_by_specimen(conn, {r["id"] for r in rows})
        return [
            {
                **row,
                "location": locations.get(row.get("location_id")),
                "species": taxa.get(row.get("species_id")),
                "primary_photo_url": (
                    photo_url(row["id"], portraits[row["id"]])
                    if row["id"] in portraits
                    else None
                ),
            }
            for row in rows
        ]

    def _filtered(self, query: SpecimenQuery) -> Select[Any]:
        stmt = select(specimen).select_from(
            specimen.outerjoin(species, specimen.c.species_id == species.c.id)
        )
        conditions: list[Any] = []
        # Archive, do not delete: archived plants leave the Register unless the
        # Register asks for them by status.
        if query.status != ARCHIVED_STATUS:
            conditions.append(specimen.c.archived_at.is_(None))
        if query.location_id:
            conditions.append(specimen.c.location_id == _as_uuid(query.location_id))
        if query.outdoor is not None:
            conditions.append(specimen.c.is_outdoor.is_(query.outdoor))
        if query.status:
            conditions.append(specimen.c.status == query.status)
        if query.toxic_to_pets is not None:
            # An unresolved species is not evidence of safety, but it is not a
            # toxicity claim either: it answers "no" and stays visible to "all".
            conditions.append(
                func.coalesce(species.c.toxic_to_pets, False).is_(query.toxic_to_pets)
            )
        if query.q:
            needle = f"%{query.q}%"
            conditions.append(
                or_(
                    specimen.c.nickname.ilike(needle),
                    species.c.accepted_name.ilike(needle),
                    func.array_to_string(species.c.common_names, " ").ilike(needle),
                )
            )
        return stmt.where(and_(*conditions)) if conditions else stmt

    async def list_specimens(self, query: SpecimenQuery) -> SpecimenPage:
        stmt = self._filtered(query)
        async with self._engine.connect() as conn:
            total = await conn.scalar(select(func.count()).select_from(stmt.subquery()))
            rows = await conn.execute(
                stmt.order_by(specimen.c.created_at, specimen.c.id)
                .offset(query.offset)
                .limit(query.limit)
            )
            items = await self._hydrate(conn, [dict(r._mapping) for r in rows])
        end = query.offset + len(items)
        return SpecimenPage(
            items=items,
            total=int(total or 0),
            next_cursor=str(end) if end < int(total or 0) else None,
        )

    async def get_specimen(self, specimen_id: str) -> Record | None:
        key = _as_uuid(specimen_id)
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(select(specimen).where(specimen.c.id == key))
            ).first()
            if row is None:
                return None
            return (await self._hydrate(conn, [dict(row._mapping)]))[0]

    # ---------------------------------------------------------------- writing

    async def _require_location(
        self, conn: AsyncConnection, location_id: Any
    ) -> Record:
        row = (
            await conn.execute(
                select(location, _SPECIMEN_COUNT).where(
                    location.c.id == _as_uuid(location_id)
                )
            )
        ).first()
        if row is None:
            raise UnknownLocationError(location_id)
        return dict(row._mapping)

    async def create_specimen(self, data: dict[str, Any]) -> Record:
        async with self._engine.begin() as conn:
            place = (
                await self._require_location(conn, data["location_id"])
                if data.get("location_id")
                else None
            )
            species_id = _as_uuid(data.get("species_id"))
            if species_id is not None:
                known = await conn.scalar(
                    select(species.c.id).where(species.c.id == species_id)
                )
                if known is None:
                    raise UnknownSpeciesError(species_id)

            count = int(data.get("count") or 1)
            values = {
                "id": uuid.uuid4(),
                "species_id": species_id,
                "nickname": data.get("nickname"),
                "cultivar": data.get("cultivar"),
                "is_group": is_group_for(count),
                "count": count,
                "location_id": place["id"] if place else None,
                "is_outdoor": is_outdoor_for(place),
                "in_container": bool(data.get("in_container", True)),
                "container_litres": data.get("container_litres"),
                "acquired_on": data.get("acquired_on"),
                "provenance": data.get("provenance"),
                "status": "thriving",
            }
            row = (
                await conn.execute(
                    specimen.insert().values(**values).returning(specimen)
                )
            ).one()
            return (await self._hydrate(conn, [dict(row._mapping)]))[0]

    async def update_specimen(
        self, specimen_id: str, changes: dict[str, Any]
    ) -> Record | None:
        key = _as_uuid(specimen_id)
        async with self._engine.begin() as conn:
            before = (
                await conn.execute(
                    select(specimen.c.id, specimen.c.location_id).where(
                        specimen.c.id == key
                    )
                )
            ).first()
            if before is None:
                return None

            values: dict[str, Any] = {
                k: v for k, v in changes.items() if k in SPECIMEN_WRITABLE
            }
            if "location_id" in changes:
                place = (
                    await self._require_location(conn, changes["location_id"])
                    if changes["location_id"]
                    else None
                )
                values["location_id"] = place["id"] if place else None
                # The denormalised flag follows the move, always.
                values["is_outdoor"] = is_outdoor_for(place)
                if values["location_id"] != before.location_id:
                    # The move is the Register's own log entry, in the
                    # same transaction, so nobody writes a second by hand.
                    await conn.execute(
                        log_entry.insert().values(
                            id=uuid.uuid4(),
                            specimen_id=key,
                            kind=RELOCATE_KIND,
                            data=relocation_data(
                                str(before.location_id) if before.location_id else None,
                                (
                                    str(values["location_id"])
                                    if values["location_id"]
                                    else None
                                ),
                            ),
                        )
                    )
            if values.get("status") == ARCHIVED_STATUS:
                values["archived_at"] = func.coalesce(
                    specimen.c.archived_at, func.now()
                )
            elif "status" in values:
                # Moving a plant off "archived" brings it back to the Register.
                values["archived_at"] = None
            values["updated_at"] = func.now()

            row = (
                await conn.execute(
                    specimen.update()
                    .where(specimen.c.id == key)
                    .values(**values)
                    .returning(specimen)
                )
            ).one()
            return (await self._hydrate(conn, [dict(row._mapping)]))[0]

    async def archive_specimen(self, specimen_id: str) -> bool:
        key = _as_uuid(specimen_id)
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    specimen.update()
                    .where(specimen.c.id == key)
                    .values(
                        # Idempotent: re-archiving does not rewrite the date it
                        # was lost on.
                        archived_at=func.coalesce(specimen.c.archived_at, func.now()),
                        status=ARCHIVED_STATUS,
                        updated_at=func.now(),
                    )
                    .returning(specimen.c.id)
                )
            ).first()
        return row is not None

    # -------------------------------------------------------------- locations

    async def list_locations(
        self, site_id: str | None = None, outdoor: bool | None = None
    ) -> list[Record]:
        stmt = select(location, _SPECIMEN_COUNT).where(location.c.archived_at.is_(None))
        if site_id:
            stmt = stmt.where(location.c.site_id == _as_uuid(site_id))
        if outdoor is not None:
            stmt = stmt.where(location.c.is_outdoor.is_(outdoor))
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                stmt.order_by(location.c.created_at, location.c.id)
            )
            return [dict(r._mapping) for r in rows]

    async def get_location(self, location_id: str) -> Record | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(location, _SPECIMEN_COUNT).where(
                        location.c.id == _as_uuid(location_id)
                    )
                )
            ).first()
            return dict(row._mapping) if row else None

    async def _resolve_site(self, conn: AsyncConnection, site_id: Any) -> uuid.UUID:
        if site_id:
            resolved = _as_uuid(site_id)
            if resolved is not None:
                return resolved
        # One household, one site (v1.0 is explicitly not multi-household).
        found = await conn.scalar(
            select(site.c.id).order_by(site.c.created_at, site.c.id).limit(1)
        )
        if found is None:
            raise NoSiteError()
        return uuid.UUID(str(found))

    async def create_location(self, data: dict[str, Any]) -> Record:
        async with self._engine.begin() as conn:
            if data.get("parent_id"):
                await self._require_location(conn, data["parent_id"])
            values = {
                "id": uuid.uuid4(),
                "site_id": await self._resolve_site(conn, data.get("site_id")),
                "parent_id": _as_uuid(data.get("parent_id")),
                "name": data["name"],
                "kind": data["kind"],
                "is_outdoor": bool(data["is_outdoor"]),
                "is_covered": bool(data.get("is_covered", False)),
                "sun_exposure": normalise_sun_exposure(data.get("sun_exposure")),
            }
            row = (
                await conn.execute(
                    location.insert().values(**values).returning(location)
                )
            ).one()
            return {**dict(row._mapping), "specimen_count": 0}

    async def update_location(
        self, location_id: str, data: dict[str, Any]
    ) -> Record | None:
        key = _as_uuid(location_id)
        async with self._engine.begin() as conn:
            exists = await conn.scalar(
                select(location.c.id).where(location.c.id == key)
            )
            if exists is None:
                return None
            if data.get("parent_id"):
                await self._require_location(conn, data["parent_id"])

            values: dict[str, Any] = {
                "name": data["name"],
                "kind": data["kind"],
                "is_outdoor": bool(data["is_outdoor"]),
                "is_covered": bool(data.get("is_covered", False)),
                "sun_exposure": normalise_sun_exposure(data.get("sun_exposure")),
            }
            if data.get("site_id"):
                values["site_id"] = _as_uuid(data["site_id"])
            if "parent_id" in data:
                values["parent_id"] = _as_uuid(data["parent_id"])

            await conn.execute(
                location.update().where(location.c.id == key).values(**values)
            )
            # Moving a porch indoors moves everything standing on it. Same
            # transaction, so the two flags are never seen disagreeing.
            await conn.execute(
                specimen.update()
                .where(specimen.c.location_id == key)
                .values(is_outdoor=values["is_outdoor"], updated_at=func.now())
            )
            row = (
                await conn.execute(
                    select(location, _SPECIMEN_COUNT).where(location.c.id == key)
                )
            ).one()
            return dict(row._mapping)

    # ---------------------------------------------------------------- members

    async def list_members(self) -> list[Record]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                select(member)
                .where(member.c.archived_at.is_(None))
                .order_by(member.c.created_at, member.c.id)
            )
            return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------ photographs

    async def _specimen_exists(self, conn: AsyncConnection, specimen_id: Any) -> bool:
        found = await conn.scalar(
            select(specimen.c.id).where(specimen.c.id == _as_uuid(specimen_id))
        )
        return found is not None

    async def _require_member(self, conn: AsyncConnection, member_id: Any) -> Any:
        if not member_id:
            return None
        key = _as_uuid(member_id)
        found = await conn.scalar(
            select(member.c.id).where(
                member.c.id == key, member.c.archived_at.is_(None)
            )
        )
        if found is None:
            raise UnknownMemberError(member_id)
        return key

    def _hydrate_photo(self, row: Record) -> Record:
        """``thumb_key`` is a question for the store: there is no column for it."""
        thumb = thumb_key_for(row["image_key"])
        store = self.photo_images
        return {
            **row,
            "thumb_key": thumb if store is not None and store.exists(thumb) else None,
        }

    async def list_photos(self, specimen_id: str, order: str) -> list[Record] | None:
        async with self._engine.connect() as conn:
            if not await self._specimen_exists(conn, specimen_id):
                return None
            rows = await conn.execute(photos_statement(specimen_id, order))
            return [self._hydrate_photo(dict(r._mapping)) for r in rows]

    async def get_photo(self, specimen_id: str, photo_id: str) -> Record | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(own_photo_statement(specimen_id, photo_id))
            ).first()
            return self._hydrate_photo(dict(row._mapping)) if row else None

    async def create_photo(self, specimen_id: str, data: dict[str, Any]) -> Record:
        key = _as_uuid(specimen_id)
        async with self._engine.begin() as conn:
            if not await self._specimen_exists(conn, key):
                raise UnknownSpecimenError(specimen_id)
            taken_by = await self._require_member(conn, data.get("member_id"))
            is_primary = bool(data.get("is_primary", False))
            if is_primary:
                # Exclusive per specimen, in the same transaction as the insert.
                await conn.execute(
                    photo.update()
                    .where(photo.c.specimen_id == key, photo.c.is_primary.is_(True))
                    .values(is_primary=False)
                )
            values: dict[str, Any] = {
                "id": _as_uuid(data["id"]),
                "specimen_id": key,
                "image_key": data["image_key"],
                "caption": data.get("caption"),
                "is_primary": is_primary,
                "taken_by": taken_by,
            }
            if data.get("taken_at"):
                values["taken_at"] = data["taken_at"]
            row = (
                await conn.execute(photo.insert().values(**values).returning(photo))
            ).one()
            return self._hydrate_photo({**dict(row._mapping), "log_entry_id": None})

    async def delete_photo(self, specimen_id: str, photo_id: str) -> bool:
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    photo.delete()
                    .where(
                        photo.c.id == _as_uuid(photo_id),
                        photo.c.specimen_id == _as_uuid(specimen_id),
                    )
                    .returning(photo.c.id)
                )
            ).first()
        return row is not None

    # ------------------------------------------------------------- growth log

    async def _hydrate_log_entries(
        self, conn: AsyncConnection, rows: list[Record]
    ) -> list[Record]:
        cited = {r["photo_id"] for r in rows if r.get("photo_id")}
        pictures: dict[Any, Record] = {}
        if cited:
            found = await conn.execute(
                select(photo, _LOG_ENTRY_ID).where(photo.c.id.in_(cited))
            )
            pictures = {r.id: self._hydrate_photo(dict(r._mapping)) for r in found}
        return [
            {
                **row,
                # Only a picture of the entry's own plant is attached: the
                # write refuses any other, and the read does not trust the write.
                "photo": next(
                    (
                        p
                        for p in [pictures.get(row.get("photo_id"))]
                        if p and p["specimen_id"] == row["specimen_id"]
                    ),
                    None,
                ),
            }
            for row in rows
        ]

    async def list_log_entries(
        self, specimen_id: str, order: str
    ) -> list[Record] | None:
        async with self._engine.connect() as conn:
            if not await self._specimen_exists(conn, specimen_id):
                return None
            rows = await conn.execute(log_entries_statement(specimen_id, order))
            return await self._hydrate_log_entries(
                conn, [dict(r._mapping) for r in rows]
            )

    async def create_log_entry(self, specimen_id: str, data: dict[str, Any]) -> Record:
        key = _as_uuid(specimen_id)
        async with self._engine.begin() as conn:
            if not await self._specimen_exists(conn, key):
                raise UnknownSpecimenError(specimen_id)
            photo_id = _as_uuid(data.get("photo_id"))
            if photo_id is not None:
                own = (await conn.execute(own_photo_statement(key, photo_id))).first()
                if own is None:
                    raise UnknownPhotoError(photo_id, specimen_id)
            values: dict[str, Any] = {
                "id": uuid.uuid4(),
                "specimen_id": key,
                "kind": data["kind"],
                "body": data.get("body"),
                "photo_id": photo_id,
                "data": dict(data.get("data") or {}),
                "logged_by": await self._require_member(conn, data.get("member_id")),
            }
            if data.get("occurred_at"):
                values["occurred_at"] = data["occurred_at"]
            row = (
                await conn.execute(
                    log_entry.insert().values(**values).returning(log_entry)
                )
            ).one()
            return (await self._hydrate_log_entries(conn, [dict(row._mapping)]))[0]

    # ------------------------------------------------------------- resolution

    async def resolve_species_by_name(self, name: str) -> str | None:
        needle = name.strip()
        async with self._engine.connect() as conn:
            found = await conn.scalar(
                select(species.c.id).where(
                    func.lower(species.c.accepted_name) == needle.lower()
                )
            )
            if found is None:
                found = await conn.scalar(
                    text(
                        "SELECT id FROM species WHERE EXISTS ("
                        " SELECT 1 FROM unnest(common_names) AS c"
                        " WHERE lower(c) = lower(:name)) LIMIT 1"
                    ),
                    {"name": needle},
                )
        return str(found) if found else None
