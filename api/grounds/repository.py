"""The storage seam for map layers and pins.

Two implementations answer the same protocol, as everywhere else in this API:
``FixtureRepository`` keeps the Grounds in memory seeded from ``fixtures/``
(``MOH_MOCK_MODE=true``, how every other parts of the project runs the stack), and
``DatabaseRepository`` talks to Postgres. The router knows only this interface.

A pin is not a row of its own. ``specimen.map_layer_id`` and
``specimen.pin_px`` are where the schema puts it, so placing a pin is an update
to two columns of a specimen — which is why moving a plant indoors and moving
its pin are the same kind of act, and why a deleted layer takes its pins with
it via ``ON DELETE SET NULL``.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.settings import get_settings

Record = dict[str, Any]


class UnknownLayerError(LookupError):
    """A write named a layer that does not exist. The router answers 404 or 422."""

    def __init__(self, layer_id: Any) -> None:
        super().__init__(f"No such map layer: {layer_id}")
        self.layer_id = str(layer_id)


class UnknownSpecimenError(LookupError):
    """A pin named a specimen nothing matches. The router answers 422."""

    def __init__(self, specimen_id: Any) -> None:
        super().__init__(f"No such specimen: {specimen_id}")
        self.specimen_id = str(specimen_id)


class PinOutsideLayerError(ValueError):
    """A pin landed off the sheet. The router answers 422."""

    def __init__(self, x: float, y: float, width_px: int, height_px: int) -> None:
        super().__init__(
            f"A pin at ({x:g}, {y:g}) is outside the layer, which is "
            f"{width_px}×{height_px} pixels."
        )
        self.x, self.y = x, y


class GroundsRepository(Protocol):
    """Everything the grounds router needs from storage."""

    async def list_layers(self, site_id: str | None = None) -> list[Record]: ...

    async def get_layer(self, layer_id: str) -> Record | None: ...

    async def create_layer(self, data: dict[str, Any]) -> Record: ...

    async def set_calibration(
        self, layer_id: str, calibration: dict[str, Any]
    ) -> Record | None: ...

    async def list_pins(self, layer_id: str | None = None) -> list[Record]: ...

    async def set_pin(
        self, specimen_id: str, layer_id: str, px: dict[str, float] | None
    ) -> Record: ...

    async def default_site_id(self) -> str | None: ...


async def get_repository() -> GroundsRepository:
    """FastAPI dependency: fixtures when mocking, Postgres when not.

    Mock mode stays a *writable* Grounds — upload, calibration and pin
    placement all work there — so the app's screens can build the Specimen cross-links and the
    demo can be driven end to end before anyone attaches a database.
    """
    if get_settings().mock_mode:
        from grounds.fixture_repository import fixture_repository

        return fixture_repository()

    from grounds.database_repository import DatabaseRepository
    from grounds.db import get_engine

    return DatabaseRepository(get_engine())
