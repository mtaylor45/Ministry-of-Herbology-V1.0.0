"""The Register, in memory, seeded from ``fixtures/``.

This is what ``MOH_MOCK_MODE=true`` serves, and the build-against-mocks rule makes it load-bearing:
J, the maps module and the scheduler build against it, and the scenario suite reads the same fixture
data, so the mocks and the tests cannot drift apart.

It is writable. A mock that can only be read stops being useful the moment the
feature under test is "add a plant", so creates, edits and archives all work
here — they just live for as long as the process does.

It also keeps photographs and the growth log. Three fixture specimens
start with a few drawn stand-ins (``mocks/photo_image.py``) so the app's screens' growth log
has something to show, and their captions say what they are: no fixture
photograph names a real picture or a real plant. Uploads go to a memory store
and are gone on restart, like every other mock-mode write.
"""

from __future__ import annotations

import copy
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app import fixtures
from inventory.domain import (
    ARCHIVED_STATUS,
    RELOCATE_KIND,
    display_name,
    is_group_for,
    is_outdoor_for,
    normalise_sun_exposure,
    relocation_data,
    search_haystack,
)
from inventory.mocks.photo_image import photo_png, seed_for, thumb_png
from inventory.photos import MemoryPhotoStore, PhotoImageStore, key_for
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

#: Which fixture specimens start with photographs, by position in the fixture
#: file rather than by id.
#: Three, so the growth log has a plant with several, a plant with one, and
#: plants with none.
_SEEDED_POSITIONS = ((0, 3), (1, 1), (3, 2))

#: The caption every drawn stand-in carries. It says what the picture is and
#: names nothing real.
MOCK_CAPTION = (
    "Drawn stand-in for mock mode: a schematic pot and stem, not a photograph "
    "of this plant."
)

_LOCK = threading.Lock()
_INSTANCE: FixtureRepository | None = None


def fixture_repository() -> FixtureRepository:
    """The process-wide mock store, so writes outlive the request that made them."""
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:
            _INSTANCE = FixtureRepository()
        return _INSTANCE


def reset_fixture_repository() -> FixtureRepository:
    """Reload from ``fixtures/``. For tests, and for a demo that wants a clean slate."""
    global _INSTANCE
    with _LOCK:
        _INSTANCE = FixtureRepository()
        return _INSTANCE


class FixtureRepository:
    """An in-memory inventory. Ordering is fixture order, then order of arrival."""

    def __init__(self) -> None:
        # Deep copies: ``app.fixtures`` caches the parsed JSON, and a mock that
        # mutated it would rewrite the fixture data for every other reader.
        self._locations: list[Record] = copy.deepcopy(fixtures.locations())
        self._specimens: list[Record] = copy.deepcopy(fixtures.specimens())
        self._species: list[Record] = copy.deepcopy(fixtures.species())
        self._members: list[Record] = [
            {
                "id": "01890050-0000-7000-8000-000000000001",
                "name": "Keeper",
                "role": "keeper",
                "notify_prefs": {},
            },
        ]
        self._photos: list[Record] = []
        self._log_entries: list[Record] = []
        self.photo_images: PhotoImageStore | None = MemoryPhotoStore()
        self._seed_photos()

    # ---------------------------------------------------------------- helpers

    def _species_by_id(self, species_id: str | None) -> Record | None:
        if not species_id:
            return None
        return next((s for s in self._species if s["id"] == str(species_id)), None)

    def _location_by_id(self, location_id: str | None) -> Record | None:
        if not location_id:
            return None
        return next((r for r in self._locations if r["id"] == str(location_id)), None)

    def _specimen_count(self, location_id: str) -> int:
        return sum(
            1
            for s in self._specimens
            if s.get("location_id") == location_id and not s.get("archived_at")
        )

    def _hydrate_location(self, row: Record) -> Record:
        return {**row, "specimen_count": self._specimen_count(row["id"])}

    def _hydrate(self, row: Record) -> Record:
        location = self._location_by_id(row.get("location_id"))
        portrait = next(
            (
                p
                for p in self._photos
                if p["specimen_id"] == row["id"] and p.get("is_primary")
            ),
            None,
        )
        return {
            **row,
            "location": self._hydrate_location(location) if location else None,
            "species": self._species_by_id(row.get("species_id")),
            "primary_photo_url": (
                photo_url(row["id"], portrait["id"]) if portrait else None
            ),
        }

    def _member_by_id(self, member_id: str | None) -> Record | None:
        if not member_id:
            return None
        return next((m for m in self._members if m["id"] == str(member_id)), None)

    def _require_member(self, member_id: Any) -> str | None:
        if not member_id:
            return None
        if self._member_by_id(str(member_id)) is None:
            raise UnknownMemberError(member_id)
        return str(member_id)

    def _specimen_row(self, specimen_id: str) -> Record | None:
        return next((r for r in self._specimens if r["id"] == str(specimen_id)), None)

    def _require_location(self, location_id: Any) -> Record:
        location = self._location_by_id(location_id)
        if location is None:
            raise UnknownLocationError(location_id)
        return location

    # -------------------------------------------------------------- specimens

    async def list_specimens(self, query: SpecimenQuery) -> SpecimenPage:
        rows = self._specimens
        # Archive, do not delete: archived plants stay in the record but leave
        # the Register, unless the Register is explicitly asked for them.
        if query.status != ARCHIVED_STATUS:
            rows = [r for r in rows if not r.get("archived_at")]
        if query.location_id:
            rows = [r for r in rows if r.get("location_id") == query.location_id]
        if query.outdoor is not None:
            rows = [r for r in rows if bool(r.get("is_outdoor")) is query.outdoor]
        if query.status:
            rows = [r for r in rows if r.get("status") == query.status]
        if query.toxic_to_pets is not None:
            rows = [
                r
                for r in rows
                if bool(
                    (self._species_by_id(r.get("species_id")) or {}).get(
                        "toxic_to_pets"
                    )
                )
                is query.toxic_to_pets
            ]
        if query.q:
            needle = query.q.casefold()
            rows = [r for r in rows if needle in self._haystack(r)]

        total = len(rows)
        window = rows[query.offset : query.offset + query.limit]
        end = query.offset + len(window)
        return SpecimenPage(
            items=[self._hydrate(r) for r in window],
            total=total,
            next_cursor=str(end) if end < total else None,
        )

    def _haystack(self, row: Record) -> str:
        species = self._species_by_id(row.get("species_id"))
        return search_haystack(display_name(row.get("nickname"), species), species)

    async def get_specimen(self, specimen_id: str) -> Record | None:
        row = next((r for r in self._specimens if r["id"] == specimen_id), None)
        return self._hydrate(row) if row else None

    async def create_specimen(self, data: dict[str, Any]) -> Record:
        location = (
            self._require_location(data["location_id"])
            if data.get("location_id")
            else None
        )
        species_id = data.get("species_id")
        if species_id and self._species_by_id(str(species_id)) is None:
            raise UnknownSpeciesError(species_id)

        count = int(data.get("count") or 1)
        row: Record = {
            "id": str(uuid.uuid4()),
            "species_id": str(species_id) if species_id else None,
            "nickname": data.get("nickname"),
            "cultivar": data.get("cultivar"),
            "is_group": is_group_for(count),
            "count": count,
            "location_id": location["id"] if location else None,
            "map_layer_id": None,
            "pin_px": None,
            "is_outdoor": is_outdoor_for(location),
            "in_container": bool(data.get("in_container", True)),
            "container_litres": data.get("container_litres"),
            "soil_note": None,
            "acquired_on": data.get("acquired_on"),
            "provenance": data.get("provenance"),
            "status": "thriving",
            "notes": None,
            "created_at": datetime.now(UTC),
            "archived_at": None,
        }
        self._specimens.append(row)
        return self._hydrate(row)

    async def update_specimen(
        self, specimen_id: str, changes: dict[str, Any]
    ) -> Record | None:
        row = next((r for r in self._specimens if r["id"] == specimen_id), None)
        if row is None:
            return None
        if "location_id" in changes:
            location = (
                self._require_location(changes["location_id"])
                if changes["location_id"]
                else None
            )
            previous = row.get("location_id")
            row["location_id"] = location["id"] if location else None
            # The denormalised flag follows the move, always.
            row["is_outdoor"] = is_outdoor_for(location)
            if row["location_id"] != previous:
                # The move is the Register's own log entry: one per move,
                # written here so nobody writes a second by hand.
                self._log_entries.append(
                    self._log_row(
                        row["id"],
                        kind=RELOCATE_KIND,
                        data=relocation_data(previous, row["location_id"]),
                    )
                )
        for key, value in changes.items():
            if key == "location_id":
                continue
            row[key] = str(value) if isinstance(value, uuid.UUID) else value
        if "status" in changes:
            # Status and the archive date stay in step, in both directions:
            # archiving records the day, un-archiving returns it to the Register.
            if changes["status"] == ARCHIVED_STATUS:
                row["archived_at"] = row.get("archived_at") or datetime.now(UTC)
            else:
                row["archived_at"] = None
        return self._hydrate(row)

    async def archive_specimen(self, specimen_id: str) -> bool:
        row = next((r for r in self._specimens if r["id"] == specimen_id), None)
        if row is None:
            return False
        row.setdefault("archived_at", None)
        if not row["archived_at"]:
            row["archived_at"] = datetime.now(UTC)
        row["status"] = ARCHIVED_STATUS
        return True

    # -------------------------------------------------------------- locations

    async def list_locations(
        self, site_id: str | None = None, outdoor: bool | None = None
    ) -> list[Record]:
        rows = [r for r in self._locations if not r.get("archived_at")]
        if site_id:
            rows = [r for r in rows if r.get("site_id") == site_id]
        if outdoor is not None:
            rows = [r for r in rows if bool(r.get("is_outdoor")) is outdoor]
        return [self._hydrate_location(r) for r in rows]

    async def get_location(self, location_id: str) -> Record | None:
        row = self._location_by_id(location_id)
        return self._hydrate_location(row) if row else None

    async def create_location(self, data: dict[str, Any]) -> Record:
        if data.get("parent_id"):
            self._require_location(data["parent_id"])
        site_id = data.get("site_id") or fixtures.site()["id"]
        row: Record = {
            "id": str(uuid.uuid4()),
            "site_id": str(site_id),
            "parent_id": str(data["parent_id"]) if data.get("parent_id") else None,
            "name": data["name"],
            "kind": data["kind"],
            "is_outdoor": bool(data["is_outdoor"]),
            "is_covered": bool(data.get("is_covered", False)),
            "sun_exposure": normalise_sun_exposure(data.get("sun_exposure")),
            "map_layer_id": None,
            "boundary_px": None,
            "created_at": datetime.now(UTC),
            "archived_at": None,
        }
        self._locations.append(row)
        return self._hydrate_location(row)

    async def update_location(
        self, location_id: str, data: dict[str, Any]
    ) -> Record | None:
        row = self._location_by_id(location_id)
        if row is None:
            return None
        if data.get("parent_id"):
            self._require_location(data["parent_id"])
        row.update(
            {
                "name": data["name"],
                "kind": data["kind"],
                "is_outdoor": bool(data["is_outdoor"]),
                "is_covered": bool(data.get("is_covered", False)),
                "sun_exposure": normalise_sun_exposure(data.get("sun_exposure")),
            }
        )
        if data.get("site_id"):
            row["site_id"] = str(data["site_id"])
        if "parent_id" in data:
            row["parent_id"] = str(data["parent_id"]) if data["parent_id"] else None
        # Moving a porch indoors moves everything standing on it: the specimens'
        # denormalised flag is not allowed to lag behind their location's.
        for specimen in self._specimens:
            if specimen.get("location_id") == row["id"]:
                specimen["is_outdoor"] = row["is_outdoor"]
        return self._hydrate_location(row)

    # ---------------------------------------------------------------- members

    async def list_members(self) -> list[Record]:
        return [dict(m) for m in self._members]

    # ------------------------------------------------------------ photographs

    def _seed_photos(self) -> None:
        """A few drawn stand-ins on a few fixture plants, through the real store.

        Spread over the weeks before the process started so the log has an
        order to show; the newest is each plant's portrait; one growth entry
        cites each plant's newest picture so ``Photo.log_entry_id`` is reachable
        in mock mode too.
        """
        keeper = self._members[0]["id"] if self._members else None
        started = datetime.now(UTC).replace(microsecond=0)
        store = self.photo_images
        assert store is not None  # freshly built two lines up
        for position, count in _SEEDED_POSITIONS:
            if position >= len(self._specimens):
                continue
            specimen = self._specimens[position]
            newest: Record | None = None
            for index in range(count):
                photo_id = str(uuid.uuid4())
                seed = seed_for(f"{specimen['id']}:{index}")
                image_key = key_for(photo_id, ".png")
                thumb_key = key_for(photo_id, ".png", thumb=True)
                store.put(image_key, photo_png(seed))
                store.put(thumb_key, thumb_png(seed))
                newest = {
                    "id": photo_id,
                    "specimen_id": specimen["id"],
                    "image_key": image_key,
                    "taken_at": started - timedelta(days=7 * (count - index), hours=1),
                    "caption": MOCK_CAPTION,
                    "is_primary": index == count - 1,
                    "taken_by": keeper,
                }
                self._photos.append(newest)
            if newest is not None:
                self._log_entries.append(
                    self._log_row(
                        specimen["id"],
                        kind="growth",
                        body="Mock entry: a growth note citing the drawn stand-in above.",
                        occurred_at=newest["taken_at"],
                        photo_id=newest["id"],
                        logged_by=keeper,
                    )
                )
                self._log_entries.append(
                    self._log_row(
                        specimen["id"],
                        kind="note",
                        body="Mock entry: a note with no photograph.",
                        occurred_at=started - timedelta(days=1),
                        logged_by=keeper,
                    )
                )

    def _thumb_key(self, row: Record) -> str | None:
        store = self.photo_images
        if store is None:
            return None
        key = key_for(row["id"], row["image_key"][-4:], thumb=True)
        return key if store.exists(key) else None

    def _hydrate_photo(self, row: Record) -> Record:
        # ``log_entry.photo_id`` read backwards: the earliest
        # entry citing this picture, which is deterministic if two ever do.
        citing = sorted(
            (e for e in self._log_entries if e.get("photo_id") == row["id"]),
            key=lambda e: (e["occurred_at"], e["id"]),
        )
        return {
            **row,
            "thumb_key": self._thumb_key(row),
            "log_entry_id": citing[0]["id"] if citing else None,
        }

    @staticmethod
    def _ordered(rows: list[Record], order: str, key: str) -> list[Record]:
        return sorted(
            rows, key=lambda r: (r[key], r["id"]), reverse=(order != "oldest")
        )

    async def list_photos(self, specimen_id: str, order: str) -> list[Record] | None:
        if self._specimen_row(specimen_id) is None:
            return None
        mine = [p for p in self._photos if p["specimen_id"] == str(specimen_id)]
        return [self._hydrate_photo(p) for p in self._ordered(mine, order, "taken_at")]

    async def get_photo(self, specimen_id: str, photo_id: str) -> Record | None:
        row = next(
            (
                p
                for p in self._photos
                if p["id"] == str(photo_id) and p["specimen_id"] == str(specimen_id)
            ),
            None,
        )
        return self._hydrate_photo(row) if row else None

    async def create_photo(self, specimen_id: str, data: dict[str, Any]) -> Record:
        if self._specimen_row(specimen_id) is None:
            raise UnknownSpecimenError(specimen_id)
        taken_by = self._require_member(data.get("member_id"))
        is_primary = bool(data.get("is_primary", False))
        if is_primary:
            # Exclusive per specimen: the Register has one portrait.
            for other in self._photos:
                if other["specimen_id"] == str(specimen_id):
                    other["is_primary"] = False
        row: Record = {
            "id": str(data["id"]),
            "specimen_id": str(specimen_id),
            "image_key": data["image_key"],
            "taken_at": data.get("taken_at") or datetime.now(UTC),
            "caption": data.get("caption"),
            "is_primary": is_primary,
            "taken_by": taken_by,
        }
        self._photos.append(row)
        return self._hydrate_photo(row)

    async def delete_photo(self, specimen_id: str, photo_id: str) -> bool:
        before = len(self._photos)
        self._photos = [
            p
            for p in self._photos
            if not (p["id"] == str(photo_id) and p["specimen_id"] == str(specimen_id))
        ]
        return len(self._photos) < before

    # ------------------------------------------------------------- growth log

    def _log_row(
        self,
        specimen_id: str,
        *,
        kind: str,
        body: str | None = None,
        occurred_at: datetime | None = None,
        photo_id: str | None = None,
        data: dict[str, Any] | None = None,
        logged_by: str | None = None,
    ) -> Record:
        return {
            "id": str(uuid.uuid4()),
            "specimen_id": str(specimen_id),
            "kind": kind,
            "occurred_at": occurred_at or datetime.now(UTC),
            "body": body,
            "photo_id": photo_id,
            "data": dict(data or {}),
            "logged_by": logged_by,
        }

    def _hydrate_log_entry(self, row: Record) -> Record:
        photo = (
            next(
                (
                    p
                    for p in self._photos
                    if p["id"] == row["photo_id"]
                    and p["specimen_id"] == row["specimen_id"]
                ),
                None,
            )
            if row.get("photo_id")
            else None
        )
        return {**row, "photo": self._hydrate_photo(photo) if photo else None}

    async def list_log_entries(
        self, specimen_id: str, order: str
    ) -> list[Record] | None:
        if self._specimen_row(specimen_id) is None:
            return None
        mine = [e for e in self._log_entries if e["specimen_id"] == str(specimen_id)]
        return [
            self._hydrate_log_entry(e)
            for e in self._ordered(mine, order, "occurred_at")
        ]

    async def create_log_entry(self, specimen_id: str, data: dict[str, Any]) -> Record:
        if self._specimen_row(specimen_id) is None:
            raise UnknownSpecimenError(specimen_id)
        photo_id = str(data["photo_id"]) if data.get("photo_id") else None
        if photo_id and await self.get_photo(specimen_id, photo_id) is None:
            raise UnknownPhotoError(photo_id, specimen_id)
        row = self._log_row(
            specimen_id,
            kind=data["kind"],
            body=data.get("body"),
            occurred_at=data.get("occurred_at"),
            photo_id=photo_id,
            data=data.get("data"),
            logged_by=self._require_member(data.get("member_id")),
        )
        self._log_entries.append(row)
        return self._hydrate_log_entry(row)

    # ------------------------------------------------------------- resolution

    async def resolve_species_by_name(self, name: str) -> str | None:
        needle = name.casefold().strip()
        for row in self._species:
            if str(row.get("accepted_name", "")).casefold() == needle:
                return str(row["id"])
        for row in self._species:
            if any(str(c).casefold() == needle for c in row.get("common_names") or []):
                return str(row["id"])
        return None
