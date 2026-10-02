# Inventory & Core API — the inventory API

Specimens, locations, zones, groups, household members, and the
photographs and the growth log. Implements the `inventory` paths of
`contracts/openapi/openapi.yaml`; the contract is frozen, so nothing here
changes a response shape.

## Layout

| Module | What it does |
| --- | --- |
| `router.py` | HTTP only. Validates, delegates, serialises. |
| `schemas.py` | The contract's request bodies, and the one place a row becomes a response. |
| `domain.py` | The invariants, independent of storage. |
| `repository.py` | The storage protocol, and which implementation answers. |
| `fixture_repository.py` | In-memory Register seeded from `fixtures/` — mock mode. |
| `database_repository.py` | SQLAlchemy Core on Postgres — live mode. |
| `tables.py` | Core table metadata mirroring `contracts/schema/001_init.sql`. |
| `db.py` | The lazily created async engine. |
| `enrichment.py` | Hands a new plant to the botany worker's queue without blocking on it. |
| `config.py` | `MOH_PHOTOS_IMAGE_DIR` (no default, the design) and the two upload bounds. |
| `photos.py` | The photograph key pattern on the shared store in `api/app/images/`. |
| `mocks/photo_image.py` | Drawn stand-in photographs for mock mode, captioned as such. |

## Two modes, one protocol

`MOH_MOCK_MODE=true` (the default, the design) serves the whole API from
`fixtures/`, including writes — every other parts of the project runs the stack this way
and a create must work there too, or "add a plant" cannot be demonstrated
without a database. Set it false and `MOH_DATABASE_URL` and the same router
talks to Postgres. Both paths serialise through `schemas.py`, so they cannot
answer in different shapes.

Mock-mode writes live in the process. Restart the API and the Register is back
to the fixtures.

## The rules this code exists to keep

- **`specimen.is_outdoor` is derived, never supplied.** It comes from the
  specimen's location on create, is re-derived on a move, and is carried along
  when a location's own flag changes — in one transaction, so the two are never
  seen disagreeing. The frost guard reads it; a stale flag moves the wrong
  plants. `tests/contract/test_fixtures.py` asserts the same invariant on
  fixture data.
- **`is_covered` and `sun_exposure` are recorded, not inferred.** A covered
  outdoor zone collects no rain. A location that does not say gets
  `sun_exposure: unknown` rather than null.
- **A group is one specimen with a `count`.** A lavender hedge is tended once.
- **Archive, do not delete.** `DELETE /specimens/{id}` sets `archived_at` and
  `status: archived`. The row keeps its history; it leaves the Register unless
  asked for with `?status=archived`, and a PATCH back to another status
  restores it. `lost` and `given_away` are *not* archived — they stay listed.
- **Never block on enrichment.** A typed name is matched against the species
  already known and the rest is queued for the botany worker.
- **A photograph belongs to one plant**. It is listed and served only
  under its own specimen's path; the same id under another plant is a 404. A
  log entry may cite one of its own plant's photographs or none — another
  plant's is a 422 whether or not it exists, because which other plant a stray
  id belongs to is not this specimen's business.
- **The move writes the `relocate` entry.** `PATCH /specimens/{id}` with a
  changed `location_id` records one `relocate` log entry with
  `data: {from_location_id, to_location_id}`, in the same transaction, so
  nobody writes a second by hand.
- **`is_primary` is exclusive per specimen**, and the primary photograph is
  what `Specimen.primary_photo_url` points at.
- **`?order=newest|oldest`** on the two lists is a guarantee (contract 1.7.0,
  the design): `newest` is the timestamp descending and the default.
  `Photo.log_entry_id` is `log_entry.photo_id` read backwards; null is normal.

## Photographs on the operator's volume

The bytes go through the shared image store under `MOH_PHOTOS_IMAGE_DIR`,
which has **no default**: unset, `POST /specimens/{id}/photos` and
the image route answer 503 naming the variable, and the lists still work. A
full volume is a 507 with a sentence; a file missing from the volume is a 404
and never a stand-in. The upload is bounded by `MOH_PHOTOS_MAX_UPLOAD_BYTES`
(25 MiB) and `MOH_PHOTOS_MAX_IMAGE_PIXELS` (50 million, read from the header
before anything would decode); the format is judged from the file's magic
bytes and never from its `Content-Type` or name.

`GET /specimens/{id}/photos/{photo_id}/image` (`?variant=thumb`) is what
`Photo.url` and `thumb_url` point at. It is not in the contract yet: it is
served, hidden from the document, and listed in `UNDOCUMENTED_ON_PURPOSE` for
A to declare, exactly as the maps module's map-layer image and the journal's plate image were.

**No thumbnails are made for uploads.** Reducing a JPEG needs a decoder and
the deployment pins none; `thumb_url` is null for an upload (the journal's precedent for
a plate without one) and `?variant=thumb` falls back to the original. Mock
mode draws its thumbnails.

## Tests

They live in `tests/` inside this package, because the ownership rule puts the repository's
top-level `tests/` in the test suite's hands.

```
.venv/bin/python -m pytest api/inventory -q          # no database needed
```

The live-Postgres suite skips unless it is given a database it may create
tables in:

```
MOH_TEST_DATABASE_URL=postgresql+asyncpg://herbology@127.0.0.1:5432/herbology_test \
  .venv/bin/python -m pytest api/inventory -q
```

It cuts its tables out of `contracts/schema/001_init.sql` rather than retyping
them, so a column that moves in the frozen schema breaks the tests instead of
quietly passing them.
