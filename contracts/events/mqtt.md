# MQTT publish-back contract

The Ministry publishes back into Home Assistant over MQTT using HA's discovery
protocol, so plants and alerts show up as native HA entities. Discovery prefix is
`homeassistant/`; the app's own prefix is `herbology/`.

## Discovery

Published retained on first sight of an entity, at
`homeassistant/<component>/herbology/<object_id>/config`.

Device block, shared by every entity:

```json
{
  "identifiers": ["ministry_of_herbology"],
  "name": "The Ministry of Herbology",
  "manufacturer": "Ministry of Herbology",
  "model": "Greenhouse",
  "sw_version": "<app version>"
}
```

## Entities

| Entity | Component | State topic | Payload |
| --- | --- | --- | --- |
| Tasks due today | `sensor` | `herbology/rounds/due` | integer count, attrs list the tasks |
| Tasks overdue | `sensor` | `herbology/rounds/overdue` | integer count |
| Frost alert | `binary_sensor` | `herbology/frost/state` | `ON`/`OFF`, attrs carry night, low, specimens |
| Per-specimen water due | `binary_sensor` | `herbology/specimen/<id>/water_due` | `ON`/`OFF` |
| Per-specimen deficit | `sensor` | `herbology/specimen/<id>/deficit_mm` | float, `unit_of_measurement: mm` |
| Next frost date | `sensor` | `herbology/frost/next` | ISO date or `unknown`, `device_class: date` |

Attribute topics are the state topic plus `/attributes`, JSON, retained.

## Commands

The app subscribes to:

| Topic | Payload | Effect |
| --- | --- | --- |
| `herbology/cmd/task/<task_id>/complete` | `{"member_id": "<uuid>"}` | Completes the task, attributed to the member |
| `herbology/cmd/rounds/refresh` | empty | Re-evaluates rules and republishes state |

## Availability

`herbology/status` carries `online`/`offline`, retained, with `offline` set as the
MQTT last will. Every discovery config points `availability_topic` at it.

## Rules

- Everything published is retained, so HA restores state after a restart.
- Object ids are stable across restarts: `specimen_<uuid-without-dashes>`.
- Nothing secret goes in a payload — no feed tokens, no API keys.
