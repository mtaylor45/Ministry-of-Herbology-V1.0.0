"""Moving a plant, through the inventory API's own write path.

The frost guard's whole point is that a plant ends up somewhere else, so
completing a ``bring_indoors`` task has to actually move it. The specimen and its
location are the inventory API's (``api/inventory/``), and the ownership rule says this package
writes nothing there — so this module writes nothing there. It *calls* The inventory API's
published seam, ``InventoryRepository.update_specimen``, the same way
``tending.environment`` calls the weather engine's Almanac: one import of somebody
else's module, in a file that does nothing else, so there is exactly one thing to
review.

That seam does the part this package must not do. ``is_outdoor`` is a
denormalised flag on the specimen and the inventory API's store keeps it in step with the
location on every move; deriving it here from a location row would be a second
copy of the inventory API's rule, and the first time the two disagreed the frost guard would go
on alerting a plant that is standing in the kitchen.

The inventory API is not running this release. Nothing here needed C to write new code, so nothing
was escalated — but the two things an earlier release *did* want from the inventory API and did not
get are named
in the pull request rather than worked around: a specimen has nowhere to record
that it is sheltered (``status: overwintering`` exists and is the inventory API's to set), and
nothing on the specimen carries the frost threshold that put it indoors, which is
why a return date cannot be judged once the plant leaves the weather engine's guard.
"""

from __future__ import annotations

from typing import Any


class UnknownLocationError(LookupError):
    """A completion named a location nothing matches. The router answers 422."""

    def __init__(self, location_id: Any) -> None:
        super().__init__(
            f"No such location: {location_id}. The plant was not moved and "
            "nothing was completed."
        )
        self.location_id = str(location_id)


class UnknownSpecimenError(LookupError):
    """A completion's task named a specimen the Register does not have."""

    def __init__(self, specimen_id: Any) -> None:
        super().__init__(f"No such specimen: {specimen_id}")
        self.specimen_id = str(specimen_id)


async def relocate(specimen_id: str, location_id: str) -> dict[str, Any]:
    """Move one plant to one location, and hand back the row the inventory API wrote.

    Raises rather than returning a quiet ``None``: a completion that reported
    success while leaving the plant outdoors in a freeze is the exact failure
    this release exists to close.
    """
    from inventory.repository import UnknownLocationError as InventoryLocationError
    from inventory.repository import get_repository

    repo = await get_repository()
    try:
        row = await repo.update_specimen(specimen_id, {"location_id": location_id})
    except InventoryLocationError as error:
        raise UnknownLocationError(location_id) from error
    if row is None:
        raise UnknownSpecimenError(specimen_id)
    return dict(row)
