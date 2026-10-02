"""Getting a notification out of the house — the hub.

the design settles the route: **Home Assistant is the only one**. There is no
push service of this application's own, no Firebase key, no APNs certificate
and no third party holding a device token — which is the whole reason a
self-hosted plant tracker can send a phone notification at all without becoming
something that needs a privacy policy. Whatever a household has set up in Home
Assistant — the companion app, a Telegram bot, a smart speaker, a wall panel —
is reachable, and how they did it is Home Assistant's problem.

## The service call

``POST /api/services/notify/<service>`` with ``{"title", "message", "data"}``.
That is the whole protocol. ``<service>`` comes from the member's
``notify_prefs`` and is the name of a service on a hub we are already
authenticated to, so it is a *setting*, not a credential.

## What goes in ``data``

Two platform hints on an urgent message, and nothing else:

* ``push.interruption-level: time-sensitive`` — iOS, which otherwise holds a
  notification until the next scheduled summary. A freeze warning held until
  9 AM is a freeze warning that did not happen.
* ``ttl: 0`` and ``priority: high`` — Android, which otherwise lets a doze-mode
  phone sit on it.

Both are sent on the same message. The platform that does not understand a key
ignores it, and the alternative is this worker knowing what kind of phone
somebody has, which it has no way to learn and no business storing.

## What never goes in a payload

Everything. :func:`~workers.hub.credentials.assert_clean` runs over the
rendered body before it is handed to the transport — the same check the MQTT
publisher runs, from the same module, because a notification body is *more*
likely to carry a credential than an MQTT payload is: it is assembled from a
task's ``detail`` and an integration's ``last_error``, which are both free text
somebody else wrote.

The check runs at the boundary rather than at the point each string is built,
because the boundary is the thing that cannot be forgotten when a fourth
notification kind is added.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from ..credentials import assert_clean
from ..settings import HubSettings, get_settings
from ..sources.base import HubUnavailable, Poster
from .model import Notification, Recipient

#: Home Assistant's service-call path. ``notify.mobile_app_x`` is addressed as
#: ``services/notify/mobile_app_x``.
SERVICE_PATH = "services/{domain}/{service}"

#: The default domain when a member's ``notify_prefs`` names a bare service.
DEFAULT_DOMAIN = "notify"


@dataclass(frozen=True, slots=True)
class Delivery:
    """What happened to one notification, for the job's report.

    A failure is a value rather than an exception for the same reason a failed
    poll is: one unreachable phone must not stop the other two members being
    told about the frost.
    """

    kind: str
    service: str
    member_id: str
    ok: bool
    reason: str = ""
    dedupe_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "service": self.service,
            "member_id": self.member_id,
            "ok": self.ok,
            "reason": self.reason,
        }


def split_service(service: str) -> tuple[str, str]:
    """``"notify.mobile_app_x"`` into ``("notify", "mobile_app_x")``.

    A bare name is assumed to be in the ``notify`` domain, which is what
    somebody typing one into a settings box means. Any other domain is passed
    through unchanged — ``script.tell_everyone`` is a perfectly good way for a
    household to route this, and refusing it would be this app deciding how
    somebody's hub is organised.
    """
    domain, _, name = service.strip().partition(".")
    if not name:
        return DEFAULT_DOMAIN, domain
    return domain, name


def render(notification: Notification, recipient: Recipient) -> dict[str, Any]:
    """The service-call body, checked before anybody can send it.

    ``title`` is the plain title, never the themed one. The themed phrase is
    offered in ``data`` for a surface that wants the Ministry's voice — a wall
    panel, the Lunette — and a phone's lock screen gets the instruction (Rule
    7, and the brief: the themed half alone is exactly wrong at 7 AM).
    """
    data: dict[str, Any] = dict(notification.data)
    if notification.themed_title:
        data["themed_title"] = notification.themed_title
    if notification.deep_link:
        # A path, never a URL: a URL would need a host, a host would need the
        # public base URL, and a public base URL is one refactor away from
        # carrying a feed token into a payload.
        data["url"] = notification.deep_link
        data["clickAction"] = notification.deep_link
    if notification.urgent:
        data["ttl"] = 0
        data["priority"] = "high"
        data["push"] = {"interruption-level": "time-sensitive"}
    data["confidence"] = notification.certainty.confidence
    data["degraded"] = notification.certainty.degraded

    body = {
        "title": notification.title,
        "message": notification.body,
        "data": data,
    }
    label = f"notify {recipient.service}"
    assert_clean(label, notification.title)
    assert_clean(label, notification.body)
    assert_clean(label, _dump(data), data)
    return body


class NotifyChannel(Protocol):
    """Somewhere a notification can go. The only thing that opens a socket."""

    async def send(
        self, notification: Notification, recipient: Recipient
    ) -> Delivery: ...


@dataclass(slots=True)
class HomeAssistantChannel:
    """The real one: a Home Assistant service call per notification."""

    poster: Poster
    settings: HubSettings = field(default_factory=get_settings)

    async def send(self, notification: Notification, recipient: Recipient) -> Delivery:
        body = render(notification, recipient)
        domain, service = split_service(recipient.service)
        path = SERVICE_PATH.format(domain=domain, service=service)
        try:
            await self.poster.post_json("home_assistant", path, body)
        except HubUnavailable as exc:
            from ..health import redact

            reason = redact(str(exc), _secret_values(self.settings)) or str(exc)
            return Delivery(
                kind=notification.kind,
                service=recipient.service,
                member_id=recipient.member_id,
                ok=False,
                reason=reason,
                dedupe_key=notification.dedupe_key,
            )
        return Delivery(
            kind=notification.kind,
            service=recipient.service,
            member_id=recipient.member_id,
            ok=True,
            reason="sent",
            dedupe_key=notification.dedupe_key,
        )


@dataclass(slots=True)
class MemoryChannel:
    """Records what would have gone out. What the tests assert against.

    The same shape as :class:`~workers.hub.mqtt.MemoryPublisher` and for the
    same reason: what is worth testing is the words on the wire, not the
    library that carried them.
    """

    sent: list[tuple[Notification, Recipient, dict[str, Any]]] = field(
        default_factory=list
    )

    async def send(self, notification: Notification, recipient: Recipient) -> Delivery:
        body = render(notification, recipient)
        self.sent.append((notification, recipient, body))
        return Delivery(
            kind=notification.kind,
            service=recipient.service,
            member_id=recipient.member_id,
            ok=True,
            reason="sent (memory channel)",
            dedupe_key=notification.dedupe_key,
        )

    def messages(self) -> list[str]:
        return [body["message"] for _, _, body in self.sent]

    def titles(self) -> list[str]:
        return [body["title"] for _, _, body in self.sent]


def build_channel(
    settings: HubSettings | None = None, poster: Poster | None = None
) -> NotifyChannel:
    """Which channel this process sends through.

    The same decision :mod:`workers.hub.factory` makes for reads, in the same
    shape: mock mode, or a deployment that has not been pointed at a Home
    Assistant, records rather than dials. Both leave the Ministry Office
    reporting the integration as *unconfigured* — a setup step — rather than as
    *ok*, so the fallback never makes an unfinished setup look finished.
    """
    config = settings or get_settings()
    if poster is not None:
        return HomeAssistantChannel(poster, config)
    if config.mock_mode or not config.is_configured:
        return MemoryChannel()
    from ..sources.http import HomeAssistantFetcher

    return HomeAssistantChannel(HomeAssistantFetcher(config), config)


def _secret_values(settings: HubSettings) -> tuple[str, ...]:
    return tuple(
        value
        for value in (
            settings.ha_token.get_secret_value(),
            settings.mqtt_password.get_secret_value(),
        )
        if value
    )


def _dump(payload: Mapping[str, Any]) -> str:
    import json

    return json.dumps(payload, sort_keys=True, default=str)


def utcnow() -> datetime:
    return datetime.now(UTC)
