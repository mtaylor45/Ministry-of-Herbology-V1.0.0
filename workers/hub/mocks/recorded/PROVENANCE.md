# Recorded payloads — the hub

**This directory is empty, and that is the honest state of it.**

The weather engine could record NWS and Open-Meteo because both answer an anonymous
request from any host, so `workers/weather/mocks/recorded/` holds real
payloads and the weather tests replay them. Home Assistant is not like that. It
is somebody's house: reached over their network, behind a long-lived access
token, with no public instance anywhere to record from.

This branch therefore has no Home Assistant payload to put here, and did not go
looking for one. Finding an exposed hub on the internet and recording its
`/api/states` would have produced a file with somebody's room names in it, and
a mock built from a stranger's house is worse than no mock at all.

## What the tests replay instead

`workers/hub/mocks/fetcher.py` **synthesises** responses in Home Assistant's
documented `GET /api/states` shape from `fixtures/locations/locations.json`,
and stamps every one with `_synthetic` so it cannot be mistaken for a fetch —
the same thing the botany worker's mock does for a source with no recording, and
what the weather engine's does for Open-Meteo, whose success payloads are missing for a
different reason.

The shapes are taken from Home Assistant's REST and WebSocket API
documentation:

| What | Shape |
| --- | --- |
| `GET /api/` | `{"message": "API running."}` |
| `GET /api/states` | a list of `{entity_id, state, attributes, last_changed, last_updated}` |
| `GET /api/states/<entity_id>` | one such object |
| WebSocket handshake | `auth_required` → `auth` → `auth_ok` \| `auth_invalid` |
| WebSocket events | `{"type": "event", "event": {"event_type": "state_changed", "data": {"new_state": …}}}` |

## Filling this directory

    python -m workers.hub.mocks.record --live

Run against your own Home Assistant, with `MOH_HA_BASE_URL` and `MOH_HA_TOKEN`
in the environment. It writes each payload to the path `recording_name()` looks
for, so the recordings and the routing cannot drift apart, and
`RecordedFetcher` prefers a real recording the moment one exists.

Two things it will not do:

- **Write a file that was not fetched.** Without `--live` it reports what is on
  disk and what is missing and touches nothing. A dry run is the safe default
  for a script whose whole job is to overwrite evidence.
- **Record a token.** Entity ids and room names are personal enough on their
  own; `--live` prints a reminder to read what it wrote before committing it,
  because these files would be a map of somebody's house.
