# Fixtures

Shared, deterministic sample data. Every mock is driven by these files, and the
weather scenarios are the acceptance tests for the water-balance and frost
engines.

| File | Contents |
| --- | --- |
| `site.json` | One site with coordinates, timezone and NWS zone |
| `locations/locations.json` | Indoor rooms and outdoor zones, with cover and sun exposure |
| `species/species.json` | Eight species with fully cited care profiles |
| `species/sources.json` | The source records those citations point at |
| `specimens/specimens.json` | Twelve specimens: indoor, outdoor, container, in-ground, a group |
| `members/members.json` | The household: one notified about everything, one about frost only, one not a recipient at all ([why](members/README.md)) |
| `weather/baseline_30d.json` | 30 days of ordinary observations, for history views. The shipped default: a deployment that selects no scenario sees this and nothing else |
| `scenarios/drought.json` | 21 rainless days; the deficit must cross threshold |
| `scenarios/storm.json` | Six rainless days of July heat, broken on day 7 by 38 mm, then three days rebuilding; due waterings become "satisfied by rain" |
| `scenarios/frost.json` | A 72h cooling trend into −2 °C with an NWS advisory |

## Scenario format

```json
{
  "name": "drought",
  "site_id": "...",
  "start": "2026-06-01",
  "days": [{ "date": "...", "tmin_c": 0, "tmax_c": 0, "precip_mm": 0, "et0_mm": 0 }],
  "advisories": [],
  "expect": { "…": "assertions the engines must satisfy" }
}
```

### Which day a scenario is read on

`BalanceSeries.status` is the status of the series' **newest** day. `storm.json`
runs three days past its downpour, so a balance replayed to the end honestly
reports `ok` — the deficit has begun to rebuild — and the `satisfied` state the
scenario exists to show is gone.

## Determinism

All ids are fixed UUIDs, all dates are absolute, and no fixture depends on the
current date. Tests freeze the clock to the scenario's `start`.
