"""Runtime configuration for the hub worker — the hub.

Mirrors ``api/app/settings.py`` and ``workers/weather/settings.py`` so one
``.env`` configures the whole stack: the same ``MOH_`` prefix, the same
``mock_mode`` default. The variable *names* are already documented in
``.env.example``; no value for any of them belongs in this repository.

Two of the keys here decide how honest the adapter can be, and are worth
reading rather than skimming.

``entity_max_age_s``
    How old Home Assistant's own ``last_updated`` may be before its answer
    stops counting as a measurement. HA keeps serving the last value it saw
    forever, so a battery that died in March still reads 19.4 °C in July. Past
    this age the value is dropped rather than stored: there is
    no second route to indoor conditions, so a stale number is not a
    conservative choice, it is the only number anyone will see.

``source_stale_after_s``
    How long a configured sensor source may go without producing a reading
    before the Ministry Office calls it *no recent reading* rather than
    healthy. This is the number that turns a silent adapter — the hub's own worst
    failure mode — into something on a screen.

The token and the MQTT password are :class:`~pydantic.SecretStr`, so neither
survives a ``repr()``, a log line or a traceback. :mod:`workers.hub.health`
redacts them out of error text as well, because ``integration.last_error`` is
rendered in the UI.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Sent on every outbound request. Home Assistant does not require it; an
#: administrator reading their own access log deserves to know who is calling.
DEFAULT_USER_AGENT = (
    "MinistryOfHerbology/1.0 (self-hosted plant care; "
    "+https://github.com/mtaylor45/Ministry-of-Herbology-V1.0.0)"
)


class HubSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOH_", env_file=".env", extra="ignore"
    )

    #: With no Home Assistant (and no database) the worker answers from the
    #: synthesised payloads and the frozen fixtures, so the whole stack runs
    #: offline.
    mock_mode: bool = True
    fixtures_dir: Path = REPO_ROOT / "fixtures"

    #: ``MOH_HA_BASE_URL`` / ``MOH_HA_TOKEN``. Empty by default and empty in
    #: ``.env.example``: a long-lived access token comes from the environment
    #: or a swarm secret, never from a checked-in file.
    ha_base_url: str = ""
    ha_token: SecretStr = SecretStr("")

    user_agent: str = DEFAULT_USER_AGENT
    http_timeout_s: float = 15.0
    #: Minimum gap between two calls to the same host. Home Assistant is
    #: usually a Raspberry Pi on the same LAN, and polite is cheap.
    min_request_interval_s: float = 0.1

    #: Fallback for a source whose row does not set ``poll_seconds``. The
    #: column's own default is the same five minutes.
    default_poll_seconds: int = 300

    entity_max_age_s: float = 3600.0
    source_stale_after_s: float = 1800.0

    #: ``MOH_API_URL`` — this deployment's own API, on its internal network.
    #: The notification jobs ask it what is due and whether a frost is coming,
    #: over the frozen contract rather than by reaching into another
    #: parts of the project's package. ``infra/`` already sets this for the web service.
    #: **No credential is ever sent on this call** — see
    #: :mod:`workers.hub.notify.state`.
    api_url: str = "http://api:8000"

    #: ``MOH_HA_NOTIFY_SERVICE`` — a deployment-wide Home Assistant notify
    #: service, used for members whose own ``notify_prefs`` name none. Empty by
    #: default, which means *nobody is set up for notifications*: a perfectly
    #: good answer for a fresh install, and one the Ministry Office reports as
    #: a setup step rather than as a fault. Defaulting it to HA's ``notify.notify``
    #: would be this app deciding to message every device in somebody's house.
    ha_notify_service: str = ""

    #: How long an integration must stay broken before it is worth interrupting
    #: somebody. See :data:`workers.hub.notify.policy.HEALTH_GRACE_S`.
    notify_health_grace_s: float = 1800.0

    #: ``MOH_MQTT_HOST``. Empty by default. The
    #: stack and ``.env.example`` name the bundled broker explicitly; a bare
    #: checkout names none, and the Ministry Office then says *unconfigured*
    #: rather than inventing a broker called ``mosquitto`` and calling it down.
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: SecretStr = SecretStr("")
    #: Stable across restarts, so the broker's session and the retained
    #: discovery configs belong to one publisher rather than to each process.
    mqtt_client_id: str = "ministry-of-herbology"

    #: ``MOH_SECRETS_DIR`` — where swarm mounts secrets as files. The default is
    #: Docker's own convention, a path inside this container rather than a
    #: host on anybody's network, so it is not a default host.
    #: CalDAV push reads ``moh_caldav_<feed_id>`` from here at push time and
    #: keeps nothing.
    secrets_dir: Path = Path("/run/secrets")

    #: ``MOH_TZ`` — the site's zone, already set by the stack for every
    #: service. The Lunette prints a clock time, and a panel on a kitchen wall
    #: that says "updated 06:05" when the household's clock says 07:05 reads
    #: as an hour stale.
    tz: str = "UTC"

    @property
    def ha_api_url(self) -> str:
        """The REST root, with exactly one trailing slash and no double ones."""
        return self.ha_base_url.rstrip("/") + "/api"

    @property
    def ha_websocket_url(self) -> str:
        """The WebSocket endpoint, derived rather than configured separately.

        Two base URLs for one Home Assistant is two things to get wrong. The
        scheme swap is the whole difference.
        """
        base = self.ha_base_url.rstrip("/")
        if base.startswith("https://"):
            return "wss://" + base[len("https://") :] + "/api/websocket"
        if base.startswith("http://"):
            return "ws://" + base[len("http://") :] + "/api/websocket"
        return base + "/api/websocket"

    @property
    def can_notify(self) -> bool:
        """Is there a Home Assistant *and* somewhere to send a notification?

        Both halves, because they fail differently: no hub is an integration
        that is down, and a hub with no notify target anywhere is a household
        that has not finished setting up. Neither is an error and the Ministry
        Office says different things about them.
        """
        return self.is_configured or self.mock_mode

    @property
    def is_configured(self) -> bool:
        """Has someone actually pointed this at a Home Assistant?

        Kept apart from "is it reachable". An unconfigured integration is a
        setup step; an unreachable one is a fault, and the Ministry Office
        says different things about them.
        """
        return bool(self.ha_base_url and self.ha_token.get_secret_value())


@lru_cache
def get_settings() -> HubSettings:
    return HubSettings()
