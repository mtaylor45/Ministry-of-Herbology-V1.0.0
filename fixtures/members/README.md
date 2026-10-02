# Members

The household `GET /api/v1/members` serves and `POST .../complete` attributes a
watering to. Three rows, and each is a case rather than padding.

| Member | Role | Notified? | Why it is here |
| --- | --- | --- | --- |
| Keeper | `keeper` | Everything, from 07:00 | The default recipient. Its id is the one `api/inventory` and `api/tending` have seeded in code — it is unchanged here so nothing that already references it moves. |
| Tender | `tender` | Frost only, from 09:00, imperial units | Per-kind opt-out, a different rounds hour, different quiet hours and a non-metric unit preference: all four of `Recipient.from_member_row`'s branches, exercised by data rather than by a unit test's literal. |
| Observer | `observer` | Not a recipient | **No `home_assistant.service`.** a member with no service is simply not a recipient, and a household where one person has the companion app and two do not is the normal case, not a fault. Anything that counts this as a misconfiguration is wrong. |

`notify_prefs` follows the convention the contract states under
`Member.notify_prefs`. It stays an open object: unknown keys are
preserved, and the block above is the part the Home Assistant adapter reads.

## `service` is not a credential

It is the name of a service on a hub the deployment is already authenticated
to. The credential is the token in the Authorization header and never comes
near a stored preference. Any domain is accepted, `script.*` included — how a
household routes its own notifications is not this app's decision.

These are notification *service names*, not phone numbers, addresses or device
identifiers, and nothing in this file is secret.

## Who reads this

Nobody yet, and that is the point of shipping it.

- `api/inventory/fixture_repository.py` seeds one Keeper in
  code with `notify_prefs: {}`, so `GET /members` can never show a member who
  is set up for notifications.
- `workers/hub/mocks/ministry.py` derives that Keeper and
  attaches synthetic preferences, correctly marked `_synthetic`, because there
  was no fixture to read. the design calls that a workaround a fixture
  replaces outright.

Both should read this file. `fixtures/` is the test suite's and those two modules
are not, so this ships the data and the request goes with it.
