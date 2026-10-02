# Grounds — the maps module

Map layers, calibration and specimen pins. The web half is `web/src/lib/map/`.

| Route | What it does |
| --- | --- |
| `GET /grounds/layers` | Floor plans and surveys, in stacking order |
| `POST /grounds/layers` | Multipart upload of a PNG or JPEG |
| `PUT /grounds/layers/{id}/calibration` | A plan's scale, or a survey's control points |
| `GET /grounds/pins` | Every pin, optionally one layer's |
| `PUT /grounds/pins` | Place, move or lift a pin |
| `GET /grounds/layers/{id}/image` | The stored bytes — **not in the contract; see below** |

Mock mode is writable: upload, calibration and pin placement all work with no
database and no volume attached, so the app's screens is never waiting on this one. It draws its own two layers rather than pointing `image_url` at a
static file, which is what the earlier mock did and which no build ever produced.

## Where an uploaded image goes — for the maintainers and the deployment

This is the first feature that keeps a file an operator supplied, and the design
decides the shape: no object store, no bucket, no credential. A floor plan has
to survive a redeploy, so it lives on **a volume the operator mounts and
names**.

What this parts of the project shipped:

- **`MOH_GROUNDS_IMAGE_DIR` has no default.** Unset, `POST /grounds/layers`
  answers **503** naming the variable, rather than writing into a container
  layer the next `docker stack deploy` discards. the repository
  carries names and shapes, never values.
- `MOH_GROUNDS_MAX_UPLOAD_BYTES` (25 MiB) and `MOH_GROUNDS_MAX_IMAGE_PIXELS`
  (50 Mpx) **do** have defaults, and deliberately: they are not operator
  secrets, they are the bounds that stop an unauthenticated multipart endpoint
  from being a way to fill somebody's disk.

**What is the deployment's, and is escalated rather than invented here:** the volume itself.
`infra/` needs a named volume mounted into the API service at whatever path the
operator chooses, `.env.example` needs `MOH_GROUNDS_IMAGE_DIR=` with no working
value, `docs/deploy/` needs the line saying that a backup which takes the
database and not this volume restores a Grounds full of 404s, and the Nginx
front end may want to serve the volume directly. **The maps module did not touch `infra/`.**

### What an unbounded multipart endpoint would have been

Four things stand between this one and a filled disk, and each is in the API
rather than in a proxy the operator may not run:

1. the body is read in 64 KiB chunks against the byte bound and abandoned the
   moment it is exceeded — **413**, at the bound, not at the file size;
2. the format is decided by the file's own magic bytes, never by the
   `Content-Type` the client wrote — **415**, with the reason;
3. header-declared dimensions are checked against the pixel bound *before*
   anything would decode them, so a decompression bomb is refused by its
   header — **413**;
4. a full volume answers **507**, leaves no half-written file, and removes the
   stored image if the row write then fails, so a failure never leaves an
   orphan on the operator's disk.

A PDF plat is refused with **415** and the reason: the design says a PDF is
rasterised on upload, and this deployment carries no rasteriser. Adding one is
a dependency decision, not a thing to slip into a map releases.

## The two contract questions the maintainers asked

### 1. Should `MapLayer.calibration` be nullable? — **No. Recommend leaving it.**

the design named it one of the two bare `$ref`s most likely to be wrong,
because an uncalibrated layer is the normal state before somebody calibrates
it. It is the normal state — the survey in mock mode starts in it — and the
contract can already express it: `Calibration` declares nothing required, so
**the empty object `{"scale_mm_per_px": null, "points": []}` is legal and is
what this API serves from upload until calibration.**

Adding `null` would give that one state a second spelling. Every consumer would
then handle `null`, `{}`, and `{scale_mm_per_px: null, points: []}`, and the
map component would be the consumer doing it. That is a cost with no benefit,
because **"is this calibrated?" is derivable and is not a nullability
question**: a plan is calibrated when it has a positive `scale_mm_per_px`, a
survey when it has two or more points, and the layer always carries its own
`kind`. `grounds.domain.is_calibrated` is that rule in one place; its truth
table is `test_grounds_calibration.py::test_uncalibrated_is_derivable_without_the_contract_saying_null`,
and `projection.ts::isCalibrated` is the same rule client-side.

Compare `CareValue.source`, which the design was right to widen: there, absence
was a state the no-invented-plant-facts rule *requires* be expressible and no other field could stand in
for it. Here another field already does.

**If the maintainers wants the state made explicit rather than derived**, the additive change
that would actually help is not `null` on the parent but one optional field on
the child: `Calibration.calibrated_at: [string, 'null'] format: date-time`.
Absent or null means nobody has ever set these numbers; present means somebody
did. That answers a question `null` on the parent only half-answers — a
*cleared* calibration and a never-set one look identical either way — and it is
additive, so no consumer changes. The maps module is content either way and has no need of it
today.

### 2. Is one `Calibration` schema doing two jobs? — **Yes, and it should keep doing them.**

`scale_mm_per_px` is not plan-only: a survey derives one from its control
points, and this API fills it in on `PUT`, so the field is meaningful on both.
`points` is meaningless on a plan. So the schema is a union in the shape of a
record — but splitting it would mean two schemas, two request bodies and, in
practice, two map components, which is exactly what the design said not to build.

The real defect is smaller and is not a schema defect: **nothing in the
contract says which half applies to which kind**, so the document permits
`PUT`ing survey points to a floor plan. That is a cross-field rule, the body
does not carry the layer's `kind`, and the API is therefore the only place it
can live. It lives in `grounds.domain.validate_calibration` and answers 422
with the reason. **For A, if you want it written down:** a sentence in
`Calibration`'s description saying `points` applies to surveys and
`scale_mm_per_px` is authoritative for plans and derived for surveys. Prose,
not structure.

## `GET /grounds/layers/{id}/image` — escalated

`MapLayer.image_url` is an unconstrained string and the contract declares no
route that serves one. Uploaded bytes have to come from somewhere, so this
router serves them, hidden from the OpenAPI document and listed in
`tests/contract/test_api_matches_spec.py`'s `UNDOCUMENTED_ON_PURPOSE`.

**That list is for operational endpoints with no client contract, and this is
not one** — the map component fetches it for every layer. It is there so the
exemption is reviewed rather than invisible, and it wants a contract line and
a recorded decision, not a quiet precedent. Three options for the maintainers:

1. declare `GET /grounds/layers/{layer_id}/image` in the contract (smallest);
2. have Nginx serve the volume at a path the API puts in `image_url` — which
   moves the decision into `infra/` and makes the mock stack harder to run
   without a front end;
3. leave `image_url` free and say in the contract that it is opaque to clients,
   which is nearly true today and is the honest description of what a
   self-hosted deployment can promise.

H recommends (1).

## Layout

| File | What it is |
| --- | --- |
| `router.py` | The five routes, thin |
| `repository.py` | The storage seam: protocol, errors, the mock/live switch |
| `fixture_repository.py` | The writable in-memory Grounds, seeded from `fixtures/` |
| `database_repository.py` | Postgres. A pin is two columns of the inventory API's `specimen` |
| `domain.py` | What a calibration must be, and the similarity fit |
| `images.py` | Magic-byte identification and header-only measurement |
| `storage.py` | The volume, atomic writes, and the three ordinary failures |
| `config.py` | `MOH_GROUNDS_*`, and why one of them has no default |
| `tables.py` | The narrow mirror of the frozen schema |
| `mocks/plan_image.py` | The drawn stand-in sheets for mock mode |
