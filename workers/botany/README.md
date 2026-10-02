# The botany worker — Botanical Knowledge

What the Ministry knows about plants, and where it learned it.

**The rule:** this worker may rank and select among sourced values, and may write
prose for the Compendium. It may never originate a number. No source means
`confidence: unknown`, stored and shown as such — "we don't know" is a correct
answer, and a plausible guess is a dead plant.

## an earlier release — taxon resolution

A typed name goes in; a ranked list of accepted scientific names comes out, each
with a source and a confidence. Handled: common names, misspellings, synonyms
resolved to the accepted name, hybrids, and cultivars split from the species.

```
POST /api/v1/taxon/resolve  {"name": "Sansevieria trifasciata"}

[{"accepted_name": "Dracaena trifasciata", "common_name": "Snake plant",
  "family": "Dracaenaceae", "rank": "species", "gbif_key": "11041822",
  "powo_id": "urn:lsid:ipni.org:names:77164235-1", "score": 1.0,
  "confidence": "high", "cultivar": null,
  "source": {"kind": "powo", "title": "Plants of the World Online — …",
             "url": "…", "license": "CC BY 4.0", "retrieved_at": "…"}}]
```

## an earlier release — enrichment

A resolved species in, a cited care profile out: Compendium prose, common
names, the care columns, and toxicity. Every published value carries a
`care_value` row naming its source and its confidence; every value without a
source is published as `confidence: unknown` with no value at all.

```
enrich_species(ctx, species_id, "Abies balsamea")

{"enrichment_state": "complete",
 "columns": {"min_temp_c": -41.7, "soil_ph_min": 4.0, "light_label": "full_sun", …},
 "care_values": [{"field": "min_temp_c", "value": -41.7, "unit": "C",
                  "confidence": "high", "is_user_override": false,
                  "note": "USDA 'Temperature, Minimum (°F)' = -43°F, converted to °C.",
                  "source": {"kind": "usda", "url": "…", "license": "Public domain", …}},
                 {"field": "water_k_c", "value": null, "confidence": "unknown",
                  "source": null}, …],
 "sources": [{"kind": "usda", "payload": {…}, …}]}
```

### What each source actually gives us

| Source | Gives | Does not give |
| --- | --- | --- |
| USDA PLANTS | `min_temp_c` (°F→°C), `soil_ph_min/max`, `light_label`, toxicity | hardiness zones — the API has none; and characteristics exist for very few plants |
| Wikidata | common names (English), native range, GBIF and POWO ids | care values |
| Wikipedia | the Compendium summary, quoted | anything numeric |
| Perenual | light, toxicity, description — **only with a key** | anything, by default |

**The honest headline: for all eight fixture species USDA returns no measured
characteristics at all.** So `water_k_c`, `min_temp_c`, `water_interval_days`
and `light_label` come back `unknown` for them. That is the the design coverage
gap, and — no soil probe, the water balance alone deciding when
to water — it is exactly the gap that must stay visible. The user edits it; the
engines keep their own documented fallbacks; this worker publishes no number
nobody gave it.

### Toxicity

One documented exception to plain source precedence: **a source claiming
toxicity outranks a source denying it**, whatever the table says, and the
citation then points at the source that made the claim. Under-reporting is the
dangerous direction for a safety flag. The confidence drops one step to record
that the sources disagreed. USDA's single rating does not separate pets from
children, so it sets both flags and the note says so.

## How it fits together

| Module | Does |
| --- | --- |
| `names.py` | Reads the typed name: cultivar, hybrid marker, authorship, fuzzy comparison. Pure. |
| `connectors/base.py` | The shape every source has: a fetcher, pure parsers, a connector that cites its calls. |
| `connectors/http.py` | The only code that touches the network. User-Agent, rate limit, one retry, payload cache. |
| `connectors/powo.py` | Kew — the nomenclatural authority. |
| `connectors/gbif.py` | GBIF — fuzzy matching and vernacular names. |
| `resolve.py` | Ranks and merges what the sources said, and decides how much to trust it. |
| `sources.py` | `source` rows: citation plus the raw payload, kept so a synthesis can be redone. |
| `connectors/wikipedia.py` | The Compendium summary, quoted. Prose only. |
| `connectors/wikidata.py` | Common names, native range, and the ids that let Kew check the encyclopaedia. |
| `connectors/usda.py` | Minimum temperature, soil pH, light, toxicity — where USDA has measured them. |
| `connectors/perenual.py` | Written, never constructed without a key. |
| `enricher.py` | Asks every source about one species; gathers, does not decide. |
| `enrichment.py` | Cited care synthesis: the value, the citation and the confidence. |
| `mocks/record.py` | Re-records every payload from the live services in one command. |
| `tasks.py` | Source precedence, confidence arithmetic, the Arq jobs. |
| `router.py` | `POST /taxon/resolve`, in the contract's shape. |
| `mocks/` | Recorded payloads and the frozen fixtures, so everything above runs offline. |

Ranking is deliberately the *only* place a decision is made. A connector reports
what its source said; it never decides what to publish.

### Adding a source

1. Write `connectors/<kind>.py` with pure `parse_*(payload, parsed)` functions
   returning `TaxonRecord`s, and a connector class that calls them through a
   `Fetcher` and wraps each call in `build_source(...)`.
2. `register("<kind>", <Connector>)` at the bottom of the module, and add the
   kind to `SOURCE_RANK` in `tasks.py` if it is not there already.
3. Add it to `build_connectors()` in `factory.py`.
4. Record payloads into `mocks/recorded/<kind>/` and note where they came from
   in `mocks/recorded/PROVENANCE.md`.

Nothing else changes: ranking, confidence, citation and caching are shared.

## Confidence

Base confidence comes from the source precedence table (`SOURCE_RANK` and
`choose()` in `tasks.py`): user override, POWO, GBIF, USDA, Perenual, Wikidata,
Wikipedia. It is then **lowered** — never raised — for anything that weakens the
answer:

| Situation | Effect |
| --- | --- |
| Two trusted sources name different taxa | one step down, for every candidate (never averaged) |
| Fuzzy, partial or genus-only match | one step down |
| Matched on a common name | one step down — a nickname is not a citation |
| …and another candidate is within 0.1 of it | one more |
| Not the top candidate | one step down |
| Score below 0.5 | no better than `low` |
| No source at all | `unknown`, and the candidate list is simply empty |

A source that is unreachable is recorded as unreachable. It never reads as "no
such plant": `POST /taxon/resolve` answers **503** when nothing could be asked,
and an empty list only when the sources answered and had nothing.

## Sources

POWO and GBIF; Wikipedia, Wikidata and USDA. Free and openly
licensed only — the design. Perenual and Pl@ntNet stay behind
`MOH_PERENUAL_API_KEY` / `MOH_PLANTNET_API_KEY`, unset, and the free path is
complete without them: typed-name resolution does not degrade when they are off.
The coverage gap that leaves — mostly common houseplants — surfaces honestly as
`confidence: unknown`, and is never papered over.

POWO's host answers some non-browser clients with a bot challenge instead of
JSON. That is treated as unreachable, and GBIF carries the answer at a lower
confidence. See `mocks/recorded/PROVENANCE.md`.

## Running it

```
.venv/bin/python -m pytest workers/botany -q     # 175 tests, no network
.venv/bin/ruff check workers/botany
.venv/bin/black --check workers/botany
```

Configuration is `MOH_`-prefixed, shared with the API (`api/app/settings.py`):
`MOH_MOCK_MODE` (default on) replays `mocks/recorded/` instead of calling out.

## Mounting the route

`POST /taxon/resolve` is built and tested but not yet served. The API image now
carries `workers/` on its path, so what remains is one line in
`api/app/main.py` mounting `botany.router`, and striking the route's entry from
`NOT_YET_IMPLEMENTED` in `tests/contract/test_api_matches_spec.py`. Both land
together — either alone turns the contract job red — and the maintainers is doing
them in one commit.
