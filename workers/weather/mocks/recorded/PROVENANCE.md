# Recorded payloads — the weather engine

Everything in this directory was fetched from the live service on the date
below and written to disk unedited, except where a file says otherwise. The
weather tests replay these instead of opening a socket, which is what
keeps a parser bug reproducible a year from now.

- **Recorded on:** 2026-09-23 (UTC). `RECORDED_ON` in `../fetcher.py` carries
  this date, and citations use it rather than the clock — a git checkout's file
  timestamps say nothing about when a payload was fetched.
- **Site:** The Grounds, 39.7684, -86.1581 (`fixtures/site.json`).
- **Re-record with:** `python -m workers.weather.mocks.record --live`

## `nws/`

| File | Request |
| --- | --- |
| `points__the-grounds.json` | `GET /points/39.7684,-86.1581` |
| `forecast__the-grounds.json` | `GET /gridpoints/IND/58,69/forecast` |
| `forecast-hourly__the-grounds.json` | `GET /gridpoints/IND/58,69/forecast/hourly` |
| `observation__kind-latest.json` | `GET /stations/KIND/observations/latest` |
| `alerts__inz050.json` | `GET /alerts/active?zone=INZ050` (the zone `site.json` names) |
| `alerts__inz047.json` | `GET /alerts/active?zone=INZ047` (the zone the coordinates resolve to) |
| `alerts__frost-advisory-active.json` | `GET /alerts/active?event=Frost%20Advisory` |

Two notes on these, both deliberate:

- `alerts__inz050.json` is **empty**, and that is the recording. "No advisory
  is in force" is the answer the frost guard sees on almost every day of the
  year, and it has to be as well tested as the alarming one.
- `alerts__frost-advisory-active.json` was therefore recorded from the
  nationwide `event=` query, which had four live Frost Advisories in Maine and
  New Hampshire that afternoon. It is a real NWS advisory payload; it simply
  does not cover our site. The parser tests use it for shape and the ingest
  tests re-point its zone, which is stated where that happens.
- `forecast-hourly__the-grounds.json` is trimmed to its first 48 hourly periods
  (the live response carried 156) and carries a `_trimmed` key saying so.
  Nothing else in it was touched.

### A fixture mismatch worth someone's attention

`fixtures/site.json` gives `nws_zone: INZ050`. NWS titles that zone's alert
feed *"Current watches, warnings, and advisories for **Wayne** (INZ050) IN"*,
while the same call for the zone the site's own coordinates resolve to is
titled *"… for **Marion** (INZ047) IN"*. `points__the-grounds.json` gives
`INZ047` in `properties.forecastZone`.

Both payloads are recorded, so the discrepancy is evidence rather than an
assertion. One of the two is wrong, and an advisory fetched for the wrong
county is an advisory for somebody else's frost. Fixtures belong to the test suite and the maintainers, so
this is flagged rather than fixed: see the pull request (E).

## `open_meteo/`

Only the two **error** payloads are recorded here, and both are real:

| File | Why it exists |
| --- | --- |
| `error__unknown-variable.json` | HTTP 400. What a bad request looks like. |
| `error__rate-limited.json` | HTTP 429, `"Daily API request limit exceeded"`. |

The success payloads are **not** recorded, because on the day this branch was
written Open-Meteo answered every request from this host with that 429: the
free tier's daily quota for the egress address was already spent. Rather than
hand-write a file into `recorded/` and let it pass for a recording, the mock
fetcher **synthesises** Open-Meteo-shaped responses from
`fixtures/weather/baseline_30d.json` and the scenario files at request time,
and stamps every one with `_synthetic` so it cannot be mistaken for a fetch
(the same thing the botany worker's mock does for a source with no recording).

Running `python -m workers.weather.mocks.record --live` from a host with quota
writes the real payloads here, and the fetcher prefers them the moment they
exist. The 429 recording is not a placeholder for them — it is the response the
ingest has to survive, and `test_openmeteo.py` asserts it does.
