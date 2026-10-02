"""The storage seam.

Two implementations answer the same protocol: ``FixtureRepository`` keeps the
whole Register in memory seeded from ``fixtures/`` (``MOH_MOCK_MODE=true``, how
every other parts of the project runs the stack), and ``DatabaseRepository`` talks to
Postgres. The router knows only this interface, so neither path can quietly
grow behaviour the other lacks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.settings import get_settings
from inventory.config import get_photo_settings
from inventory.photos import FilesystemPhotoStore, PhotoImageStore

#: A stored row, hydrated with its joined records. Specimens carry ``location``
#: and ``species``; locations carry ``specimen_count``.
Record = dict[str, Any]


class UnknownLocationError(LookupError):
    """A write referenced a location that does not exist. The router answers 422."""

    def __init__(self, location_id: Any) -> None:
        super().__init__(f"No such location: {location_id}")
        self.location_id = str(location_id)


class UnknownSpeciesError(LookupError):
    """A create named a ``species_id`` nothing matches. The router answers 422."""

    def __init__(self, species_id: Any) -> None:
        super().__init__(f"No such species: {species_id}")
        self.species_id = str(species_id)


class UnknownSpecimenError(LookupError):
    """A photo or log write named a specimen that does not exist. The router answers 404."""

    def __init__(self, specimen_id: Any) -> None:
        super().__init__(f"No such specimen: {specimen_id}")
        self.specimen_id = str(specimen_id)


class UnknownPhotoError(LookupError):
    """A log entry cited a photograph that is not this specimen's. The router answers 422.

    Deliberately the same answer whether the photo belongs to another plant or
    to nobody: a log entry may cite a picture of its own plant or none,
    and which other plant a stray id belongs to is not this specimen's business.
    """

    def __init__(self, photo_id: Any, specimen_id: Any) -> None:
        super().__init__(
            f"No photograph {photo_id} belongs to specimen {specimen_id}. A log "
            "entry may cite one of its own plant's photographs, or none."
        )
        self.photo_id = str(photo_id)


class UnknownMemberError(LookupError):
    """``member_id`` named nobody in the household. The router answers 422."""

    def __init__(self, member_id: Any) -> None:
        super().__init__(f"No such member: {member_id}")
        self.member_id = str(member_id)


@dataclass(frozen=True, slots=True)
class SpecimenQuery:
    """The Register's filters, as the contract declares them on ``GET /specimens``."""

    q: str | None = None
    location_id: str | None = None
    outdoor: bool | None = None
    status: str | None = None
    toxic_to_pets: bool | None = None
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, slots=True)
class SpecimenPage:
    items: list[Record] = field(default_factory=list)
    total: int = 0
    next_cursor: str | None = None


class InventoryRepository(Protocol):
    """Everything the inventory router needs from storage."""

    async def list_specimens(self, query: SpecimenQuery) -> SpecimenPage: ...

    async def get_specimen(self, specimen_id: str) -> Record | None: ...

    async def create_specimen(self, data: dict[str, Any]) -> Record: ...

    async def update_specimen(
        self, specimen_id: str, changes: dict[str, Any]
    ) -> Record | None: ...

    async def archive_specimen(self, specimen_id: str) -> bool: ...

    async def list_locations(
        self, site_id: str | None = None, outdoor: bool | None = None
    ) -> list[Record]: ...

    async def get_location(self, location_id: str) -> Record | None: ...

    async def create_location(self, data: dict[str, Any]) -> Record: ...

    async def update_location(
        self, location_id: str, data: dict[str, Any]
    ) -> Record | None: ...

    async def list_members(self) -> list[Record]: ...

    async def resolve_species_by_name(self, name: str) -> str | None: ...

    # Photographs and the growth log. ``photo_images`` is where the bytes
    # are: a memory store in mock mode, the operator's volume in live mode, or
    # None when no volume is configured — in which case the lists still answer
    # and only the upload and the image route refuse.

    @property
    def photo_images(self) -> PhotoImageStore | None: ...

    async def list_photos(
        self, specimen_id: str, order: str
    ) -> list[Record] | None: ...

    async def get_photo(self, specimen_id: str, photo_id: str) -> Record | None: ...

    async def create_photo(self, specimen_id: str, data: dict[str, Any]) -> Record: ...

    async def delete_photo(self, specimen_id: str, photo_id: str) -> bool: ...

    async def list_log_entries(
        self, specimen_id: str, order: str
    ) -> list[Record] | None: ...

    async def create_log_entry(
        self, specimen_id: str, data: dict[str, Any]
    ) -> Record: ...


def photo_store_from_settings() -> PhotoImageStore | None:
    """The operator's volume, or None when ``MOH_PHOTOS_IMAGE_DIR`` is unset."""
    directory = get_photo_settings().image_dir
    return FilesystemPhotoStore(directory) if directory is not None else None


async def get_repository() -> InventoryRepository:
    """FastAPI dependency: fixtures when mocking, Postgres when not.

    Mock mode is the default and stays a complete, writable API —
    ``POST /specimens`` works there too, so the Register can be demonstrated
    end to end without a database attached.
    """
    if get_settings().mock_mode:
        from inventory.fixture_repository import fixture_repository

        return fixture_repository()

    from inventory.database_repository import DatabaseRepository
    from inventory.db import get_engine

    return DatabaseRepository(get_engine(), photo_images=photo_store_from_settings())
