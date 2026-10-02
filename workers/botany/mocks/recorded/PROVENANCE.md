# Where these payloads came from

Recorded responses, replayed by `RecordedFetcher` through the same parsers the
live connectors use. Tests read them instead of the network, so the suite is
deterministic and offline — the build-against-mocks rule of the working agreement, and the only way
the misspelling and synonym cases stay reproducible.

**Nothing in this directory is invented.** Every name, author, family,
identifier and key below was returned by a live API call on the date given.

## `gbif/` — recorded live

Fetched from `https://api.gbif.org/v1` on **2026-09-20**, unmodified apart from
pretty-printing. GBIF's Backbone Taxonomy is CC BY 4.0.

| File | Request | What it exercises |
| --- | --- | --- |
| `match__monstera-deliciosa.json` | `/species/match?name=Monstera deliciosa&verbose=true` | the ordinary exact hit |
| `match__monstra-deliciosa.json` | `…?name=Monstra deliciosa` | a misspelling; GBIF answers `FUZZY` at 85 |
| `match__sansevieria-trifasciata.json` | `…?name=Sansevieria trifasciata` | a synonym resolved to `Dracaena trifasciata` |
| `match__lavandula-angustifolia.json` | `…?name=Lavandula angustifolia` | a hit with three `alternatives` |
| `match__citrus-limon.json` | `…?name=Citrus × limon` | a hybrid, and eleven alternatives |
| `match__hosta-sieboldiana.json` | `…?name=Hosta sieboldiana` | a second clean hit |
| `match__snake-plant.json` | `…?name=Snake plant` | a common name: `matchType: NONE` |
| `match__zzqqx-frobnicata.json` | `…?name=zzqqx frobnicata` | nonsense: `matchType: NONE` |
| `search__snake-plant.json` | `/species/search?q=snake plant&datasetKey=…` | the vernacular path |
| `search__mandrake.json` | `…?q=mandrake` | four species answer to one common name |
| `search__zzqqx-frobnicata.json` | `…?q=zzqqx frobnicata` | no results at all |
| `vernacular__2868241.json` | `/species/2868241/vernacularNames` | common names for *Monstera deliciosa* |
| `vernacular__11041822.json` | `/species/11041822/vernacularNames` | common names for *Dracaena trifasciata* |

## `powo/` — shape reconstructed, content recorded

`powo.science.kew.org` sits behind a bot challenge that answers non-browser
clients — including CI — with an HTML interstitial rather than JSON. These files
are therefore **stand-ins, and say so in a `_provenance` key**:

- the **envelope** follows POWO's documented `/api/2/search` response shape (the
  one `pykew` speaks): `totalResults`, `results[]`, and per result `accepted`,
  `author`, `family`, `genus`, `name`, `rank`, `url`, `fqId`, and `synonymOf`
  for a synonym;
- the **content** — every name, author, family and IPNI LSID — was read from
  live calls to `https://www.ipni.org/api/1/search` on **2026-09-20**. IPNI is
  Kew's own name index and the source of the LSIDs POWO uses as taxon ids.

| File | Query | IPNI record it was built from |
| --- | --- | --- |
| `search__monstera-deliciosa.json` | `Monstera deliciosa` | `87478-1`, Liebm., Araceae |
| `search__sansevieria-trifasciata.json` | `Sansevieria trifasciata` | `540541-1` → `77164235-1` *Dracaena trifasciata* |
| `search__lavandula-angustifolia.json` | `Lavandula angustifolia` | `449008-1`, Mill., Lamiaceae |
| `search__citrus-limon.json` | `Citrus × limon` | `60454758-2`, (L.) Osbeck, Rutaceae |
| `search__hosta-sieboldiana.json` | `Hosta sieboldiana` | `536637-1`, Engl., Hostaceae |
| `search__mandragora-officinarum.json` | `Mandragora officinarum` | `816733-1`, L., Solanaceae |
| `search__snake-plant.json` | `snake plant` | — empty result set |
| `search__mandrake.json` | `mandrake` | — empty result set |
| `search__monstra-deliciosa.json` | `Monstra deliciosa` | — empty result set |
| `search__zzqqx-frobnicata.json` | `zzqqx frobnicata` | — empty result set |

Where IPNI gave no answer for a query (`snake-plant`, `mandrake`,
`monstra-deliciosa`, `zzqqx-frobnicata`), the file is an **empty result set**.
That is also what POWO returns for a common name or a misspelling — its search
is not fuzzy and does not index vernaculars — so those cases test the path that
matters most here: GBIF answers alone, and the confidence drops accordingly.

Two consequences worth keeping in mind:

1. `HttpFetcher` treats a non-JSON 200 as **unreachable**, never as "no such
   plant" (`SourceUnavailable`). A challenged POWO lowers confidence; it cannot
   invent one.
2. When POWO becomes reachable from CI, these files should be re-recorded from
   the live endpoint and this section deleted. Nothing else has to change: the
   parsers already read the real shape.

## `usda/` — recorded live

Fetched from `https://plantsservices.sc.egov.usda.gov/api` on **2026-09-20** by
`python -m workers.botany.mocks.record`, unmodified. USDA PLANTS is public
domain.

`search__<name>.json` is `/api/PlantSearch?searchText=`; `characteristics__<id>.json`
is `/api/PlantCharacteristics/{id}` for the id that search returned.

**Read the characteristics files before assuming this source is rich.** Every
plant has a profile; only a minority have characteristics. Of the eight fixture
species, **all eight return `[]`** — including *Podophyllum peltatum*, a
well-known North American native. `characteristics__15309.json` (*Abies
balsamea*, balsam fir) is the exception and the reason that species is in the
recorder's list at all: it is the only recording here that exercises the parser
for a minimum temperature, a pH range, a shade tolerance and a toxicity rating.
Without it those code paths would be tested against nothing.

| File | Search result | First hit |
| --- | --- | --- |
| `search__abies-balsamea.json` | 5 hit(s) | Abies balsamea (L.) Mill. (ABBA) |
| `search__citrus-limon.json` | 2 hit(s) | Citrus limon (L.) Burm. f., database artifact (CILI) |
| `search__dracaena-trifasciata.json` | 0 hit(s) | — |
| `search__hosta-sieboldiana.json` | 0 hit(s) | — |
| `search__lavandula-angustifolia.json` | 1 hit(s) | Lavandula angustifolia Mill. (LAAN81) |
| `search__mandragora-officinarum.json` | 1 hit(s) | Mandragora officinarum L. (MAOF) |
| `search__monstera-deliciosa.json` | 1 hit(s) | Monstera deliciosa Liebm. (MODE) |
| `search__ocimum-basilicum.json` | 1 hit(s) | Ocimum basilicum L. (OCBA) |
| `search__rosa-gallica.json` | 4 hit(s) | Rosa gallica L. (ROGA) |

| File | Characteristics |
| --- | --- |
| `characteristics__15309.json` | **81** |
| `characteristics__16378.json` | none — USDA has measured nothing for this plant |
| `characteristics__45812.json` | none — USDA has measured nothing for this plant |
| `characteristics__46101.json` | none — USDA has measured nothing for this plant |
| `characteristics__55128.json` | none — USDA has measured nothing for this plant |
| `characteristics__90833.json` | none — USDA has measured nothing for this plant |

| File | Source |
| --- | --- |
| `summary__monstera-deliciosa.json` | `/api/rest_v1/page/summary/Monstera_deliciosa` |
| `entity__q161077.json` | `wbgetentities` for Q161077, `props=labels|claims` |

The empty files are not padding. "USDA has no measured characteristics for this
plant" is the normal case, and it is the case synthesis has to get right:
`confidence: unknown`, no invented number.

## `wikipedia/` and `wikidata/` — partially recorded

Fetched on **2026-09-20** from `en.wikipedia.org/api/rest_v1` and
`www.wikidata.org/w/api.php`, unmodified. Wikipedia text is CC BY-SA 4.0;
Wikidata is CC0.

Only **Monstera deliciosa** is recorded. Partway through recording, Wikimedia
began answering this session's egress IP with its robot policy:

```
403 Please respect our robot policy https://w.wiki/4wJS when crawling us.
```

That is a rate limit on a shared cloud IP, not a fault in the connectors — the
same requests succeeded minutes earlier. Rather than retry into a policy that
asks us not to, or write a stand-in, the recording stops there:

- `summary__monstera-deliciosa.json` and `entity__q161077.json` are real;
- every other species falls back to `fixtures/species/species.json` in mock
  mode, which is what the fallback is for;
- `HttpFetcher` treats the 403 as **unreachable**, so a throttled Wikipedia
  lowers confidence and never reads as "this plant has no care requirements".

Re-run the recorder when the throttle clears; nothing in the code changes.

## `perenual/` — deliberately absent

There is no recording of Perenual and there should not be. the design keeps it
behind an unset `MOH_PERENUAL_API_KEY`, its terms are not an open licence, and
a connector nobody may call is tested with a payload about a plant that does
not exist (`Testus exampleii`) — the shape is what those tests check.

## Re-recording

```
curl -sS -H 'User-Agent: MinistryOfHerbology/1.0 (+https://github.com/mtaylor45/Ministry-of-Herbology-V1.0.0)' \
  'https://api.gbif.org/v1/species/match?name=Monstera%20deliciosa&strict=false&verbose=true' \
  | python -m json.tool > gbif/match__monstera-deliciosa.json
```

The filename is `<endpoint>__<slug>.json`, where the slug is
`workers.botany.mocks.fetcher.slug()` of the query: casefolded, accents and the
hybrid `×` dropped, non-alphanumerics collapsed to `-`.
