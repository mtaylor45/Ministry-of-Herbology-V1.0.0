"""Inventory invariants, in one place and independent of storage.

Both the fixture store and the database repository route their writes through
these helpers, so the rules hold whichever one is answering. The two that carry
weight downstream:

* ``specimen.is_outdoor`` is denormalised from its location. The frost guard
  reads it to decide whose night is dangerous, so it may never drift from the
  location's own flag — ``tests/contract/test_fixtures.py`` asserts exactly that
  on fixture data, and it has to hold for rows the API creates too.
* A group is *one* specimen with a ``count``. A lavender hedge is tended once,
  so ``count`` above one sets ``is_group`` rather than multiplying rows.
"""

from __future__ import annotations

from typing import Any

#: The contract's SunExposure enum. Locations that do not say get "unknown"
#: rather than null: The no-invented-plant-facts rule habit, applied to places instead of plants.
SUN_EXPOSURES = ("full_sun", "part_sun", "part_shade", "full_shade", "unknown")

#: The contract's Location.kind enum.
LOCATION_KINDS = ("area", "zone", "bed", "room", "shelf")

#: The contract's SpecimenStatus enum.
SPECIMEN_STATUSES = (
    "thriving",
    "struggling",
    "dormant",
    "overwintering",
    "lost",
    "given_away",
    "archived",
)

#: Set on a specimen when it is archived. Archive, do not delete — a lost plant
#: is part of the record, and the Register can still be asked for it by status.
ARCHIVED_STATUS = "archived"


def is_outdoor_for(location: dict[str, Any] | None) -> bool:
    """A specimen is outdoors exactly when its location is.

    A specimen with no location yet is treated as indoors: the frost guard must
    never act on a plant whose exposure nobody has stated.
    """
    if location is None:
        return False
    return bool(location.get("is_outdoor", False))


def is_group_for(count: int) -> bool:
    """A bed, hedge or clump counted as one specimen."""
    return count > 1


def normalise_sun_exposure(value: str | None) -> str:
    return value if value in SUN_EXPOSURES else "unknown"


def display_name(
    nickname: str | None,
    species: dict[str, Any] | None,
) -> str:
    """Nickname, else the species' first common name, else the accepted name.

    Same order the Register, the task titles and the search index all use, so
    they cannot disagree about what a plant is called.
    """
    if nickname:
        return str(nickname)
    if species:
        common = species.get("common_names") or []
        if common:
            return str(common[0]).capitalize()
        if species.get("common_name"):
            return str(species["common_name"]).capitalize()
        if species.get("accepted_name"):
            return str(species["accepted_name"])
    return "Unnamed specimen"


def search_haystack(name: str, species: dict[str, Any] | None) -> str:
    """Display name plus species names — what ``?q=`` matches against."""
    parts = [name]
    if species:
        if species.get("accepted_name"):
            parts.append(str(species["accepted_name"]))
        parts.extend(str(c) for c in species.get("common_names") or [])
        if species.get("common_name"):
            parts.append(str(species["common_name"]))
    return " ".join(parts).casefold()


#: The contract's LogEntry.kind enum, and the CHECK on ``log_entry.kind``.
LOG_KINDS = ("growth", "pest", "disease", "repot", "prune", "relocate", "note")

#: ``?order=`` on the two lists (contract 1.7.0, the design): ``newest`` is the
#: timestamp descending and the default; ``oldest`` is ascending, which is how
#: a growth log is read.
LIST_ORDERS = ("newest", "oldest")

#: The log kind the Register writes for itself when a plant is moved, and the
#: two keys its ``data`` carries. Written once, by the move, never by hand as
#: well: a second entry for the same move is a second fact about one event.
RELOCATE_KIND = "relocate"


def relocation_data(
    from_location_id: str | None, to_location_id: str | None
) -> dict[str, Any]:
    """The ``data`` of a ``relocate`` entry. Either side may be null: a plant
    can arrive from nowhere recorded, or be lifted off the map."""
    return {"from_location_id": from_location_id, "to_location_id": to_location_id}
