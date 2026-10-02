# The Specimen page — the app's screens

One page per plant, at `/specimen/:id/<facet>`, with four linked facets.

| Facet                | Route        | What is on it                                                     | Owner               |
| -------------------- | ------------ | ----------------------------------------------------------------- | ------------------- |
| Register Entry       | `register`   | Location, provenance, container and soil, photographs, growth log | J                   |
| Tending              | `tending`    | Care values with sources, schedule, tasks, water balance, frost   | J                   |
| Compendium           | `compendium` | Summary, taxonomy, native range, toxicity, sources                | J                   |
| Naturalist's Journal | `journal`    | Plate with its provenance, field notes, photo growth log          | J, with the journal |

`/specimen/:id` on its own redirects to `register`.

**Every facet links to the other three.** That is `SeeAlso.svelte`, which reads
the link set from `facets.ts` so no facet can grow a different one. A facet
listed before it is built says so in its own row rather than being hidden: a
missing facet the reader can see is better than one they cannot. The journal was
that row to an earlier release; all four are built now.

## The journal facet

`journal/` renders the journal's components rather than linking to the journal's page:
`PlatePage` (which carries the `ProvenanceNote` beside every plate, the journal's
`altTextFor()` alt text and the journal's `absenceSentence()` for a plant with no plate)
and `FieldNotes`. Nothing under `web/src/routes/journal/` is edited from here; `journalFacet.ts` hands the layout's own specimen record to the journal's
`buildPages()` so the facet and the book cannot disagree about which plate is
this plant's.

The photo growth log is this parts of the project's: `GrowthLog.svelte` lists
`GET /specimens/{id}/photos` **oldest first** (the contract serves newest
first; a log is read forward) with real alt text and a `<time>` per entry. There
is no upload control, because `POST /specimens/{id}/photos` is the inventory API's
and is not served — the empty state says so in plain words rather than offering
a button that fails, and the list fills in with no change here when C lands it.

## How it loads

`+layout.ts` fetches the plant, its species and its cited care values once, so
moving between facets re-runs only the facet's own reads. Each facet's
`+page.ts` settles its endpoints separately (`settle()` in `api.ts`) — a frost
lookahead that times out costs the reader the frost panel and nothing else.

Both loads call `depends('moh:specimen')`. While the enrichment queue is still
working, `+layout.svelte` re-reads on that key every four seconds and gives up
after about ninety — the exit criterion is sixty, so a job still running past
that is stuck, and a page that polls forever is a page that never admits it.

## The rules this page is built to

- **The design system's components only.** Nothing here is a button, pill, card or
  field of its own. `FactList` is a `<dl>` and `SeeAlso` is a list of
  `ListRow`s; both compose the design system's library rather than replacing any of it.
- **No themed string alone**. Every status, facet name and progress
  state in `labels.ts` and `facets.ts` is a `{ themed, plain }` pair, and the
  suite asserts it.
- **Sources and confidence next to every care value, and every one editable**. `CareValueList.svelte` shows the source, the licence and the
  retrieval date under each value and a confidence pill beside it. A value with
  no citation reads as _unknown_ and is called out above the list as well as in
  it, because the design left the water balance as the only authority on outdoor
  watering and several `water_k_c` values are uncited.
- **Mobile-first.** Built at 375px; `FactList` goes two-column at 40rem and the
  photograph grid fills as it is given room.

## Where an edit goes

The contract has two override routes and they mean different things, so
`editTarget()` in `care.ts` picks between them:

- `water_k_c`, `water_interval_days` and `min_temp_c` have `*_override` fields
  on `SpecimenUpdate`, so they are corrected for **this plant** with
  `PATCH /specimens/{id}`.
- Everything else is recorded on the species, so it is corrected for **every
  plant of that species** with `PUT /species/{id}/care-values`.

The dialog names the scope before you save.
