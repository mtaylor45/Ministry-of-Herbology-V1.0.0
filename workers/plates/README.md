# Plate sourcing and the generated fallback — the journal

Owned by the journal. Landed. The earlier skeleton named the shape and its docstring made
the promise this release had to keep:

> A generated plate is always labelled as such and never carries a
> botanical attribution it did not earn.

`domain.py` is where that is now enforced rather than hoped for, and it is the
file to read first.

| Module | What it decides |
| ------------------------- | -------------------------------------------------------------- |
| `domain.py` | What a plate may claim about itself. The invariants. |
| `style.py` | The house style, and the marks a generated plate must not wear |
| `sources.py` | What a catalogue is allowed to tell us |
| `coverage.py` | Why a leaf is blank, for every plant in the register |
| `pipeline.py` | What becomes a plate, and what becomes a named absence |
| `generation.py` | The fallback, off unless an operator chose a provider |
| `storage.py`, `config.py` | Where the bytes go (#46's pattern) |
| `router.py` | The journal's HTTP surface |
| `repository.py` | The storage seam, and the only write to `approved` |

## Three refusals

**1. A generated plate carries no licence and no attribution.** Those fields
record provenance that was _earned_. Filling one with the house style, a model
name or the string "AI generated" puts a credit-shaped value where readers look
for a credit. `Plate.__post_init__` refuses to construct one.

**2. A `public_domain` plate with no licence is not storable at all.** The maintainers' brief
guessed that such a plate should be un-approvable. The frozen schema is already
stricter — `CHECK (origin <> 'public_domain' OR license IS NOT NULL)` — and I
think the schema is right: the claim is not _unverified_, it is _unsupported_,
and the honest thing is not to record it. A candidate with no usable licence is
**discarded**, never downgraded to `generated`; relabelling a found image would
be a second lie about the same picture.

**4. Nothing in this package can set `approved`.** See below.

## What `approved` means, and who does it

**A plate is approved when a named member has looked at it and accepted it as
this plant's portrait.**

A pipeline can establish that an image is licensed and that its record names the
right species. It cannot establish that it is a good picture of _your_ plant,
that it is the right cultivar, or that it is not a photograph of a different
plant somebody mislabelled in 1890. Those are the questions approval answers. If
the pipeline set the flag, the column would mean "a program fetched this", which
`origin` and `license` already say, better.

So:

- `Plate.approve()` takes a member id and there is no other way to set the flag.
  A worker has nobody to pass, which is the mechanism rather than a convention.
- `Plate` refuses to exist with `approved` true and `approved_by` empty, and
  refuses the reverse — a half-recorded decision is not a decision.
- `repository.approve_plate(plate_id, member_id)` is the only write, and the
  database version does both columns in one statement so there is no moment
  where the row says approved with nobody attached.

The frozen schema made this argument first: `approved_by uuid REFERENCES
member(id)` was in `001_init.sql` a releases before anybody implemented it.

**What this means exit criterion.** _"Each specimen has an approved
plate"_ is therefore partly a human task by construction. The releases delivers
_approvable_ plates and the approvals a person has actually made. A run that
ends with every species holding an unapproved plate is a complete, successful
run of this pipeline.

## Answered 

an earlier release raised eight escalations. the design answers all of them, contract **1.6.0**,
and the close-out built the journal's half. The design decision is the record; this is the index.

| #   | What it was | Answer |
| --- | ----------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| 1 | Nothing could approve a plate | `POST /journal/plates/{plate_id}/approve` declared as served; `Plate.approved_by` added (§1) |
| 2 | The image route was undocumented | Declared on the design reasoning; A struck both exemptions (§2) |
| 3 | `/journal/plates` could not say _why_ a leaf is blank | `GET /journal/coverage` declared (§3), **built here** — see `coverage.py` |
| 4 | A field note could not record its author | `member_id` is an optional property of the request body (§4) |
| 5 | `MOH_PLATES_IMAGE_DIR` needed an `infra/` half | the deployment's, beside the maps module's volume, one mechanism (§5) |
| 6 | The roster's first source needed a key nobody has | Roster ordered by what a deployment can use: Commons first (§6) |
| 7 | plantillustrations.org could state no licence | Off the roster until it does (§7) |
| 8 | Two near-identical image stores | A extracts one; the read-only reuse of `grounds.images.probe` stands (§8) |

**One thing the close-out could not finish, and it is a real gap.** `/journal/coverage`
must say _why_ a plant has no plate, and in a live deployment it mostly cannot:
the frozen schema has **no column for a sourcing outcome**. `plate` records
plates that exist and nothing about attempts that produced none, so a live
deployment cannot tell _"every catalogue was asked and none had it"_ from
_"the worker has never run"_.

So live mode reports `not_run` with a sentence saying exactly that, which is
the kind the design put in the closed set for this case, and it establishes
`store_unavailable` where that is true because it is a fact about the
configuration now rather than about a past run. The other four kinds —
`no_candidate`, `unlicensed_candidate`, `generation_unavailable`,
`unusable_image` — are reachable only in mock mode today. Closing that needs a
place to keep each run's outcome per plant, which is a schema change and so the maintainers'.
Raised in the close-out pull request rather than guessed at: inventing a cause
is exactly what the enum exists to prevent.

## The AI fallback is off, and that is the shipped state

every operator input is a parameter with no usable default, and
nothing may depend on a service the operator did not choose. This repository
contains no credential, no endpoint and no provider's hostname — a _default
endpoint_ would be a service nobody chose, which is the half easiest
to break by being helpful.

So `generation_is_configured()` is false on a fresh deployment, and the
pipeline's answer for a species the catalogues missed is **"no plate for this
one"**. There is no placeholder branch to fall into. A grey rectangle with a
plant name under it, in a book of plates, is a plate as far as any reader is
concerned.

## Why the forbidden-marks list exists

Aged paper is an aesthetic. A plate number, an engraver's signature, a
copperplate binomial and a herbarium accession stamp are **claims**. A reader who
sees "Pl. XIV" in the corner has been told this came out of a book, and no
caption undoes that — the caption says "generated", the picture says "volume
two", and the picture wins.

`style.py`'s `FORBIDDEN_MARKS` is therefore not a quality preference. It is the
same rule as the licence refusal, enforced one step earlier, at the prompt. Every
prompt is built from `HOUSE_STYLE` and those constants and nothing else, which
gives the original-theme rule one structural place to be checked instead of a word blacklist.

## Running it

```
pytest workers/plates -q          # 175, all offline — nothing here opens a socket
pytest tests/contract -q          # 99
```

Mock mode needs no volume and no credential: `fixture_repository.py` draws its
own plates and holds them in memory. See its docstring for how it decides which
species get one, and why its coverage is partial on purpose.
