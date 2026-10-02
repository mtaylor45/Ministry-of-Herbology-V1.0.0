"""Tokens, hashes, the passphrase comparison and the rotation epoch."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

#: The cookie the contract has declared.
COOKIE_NAME = "moh_session"

_EPOCH_MESSAGE = b"moh-session-epoch"


def new_token() -> str:
    """32 random bytes, URL-safe. The only copy leaves in the Set-Cookie."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    """What the database keeps. A copy of the table signs nobody in."""
    return hashlib.sha256(token.encode("utf-8")).digest()


def matches(submitted: str, expected: str) -> bool:
    """Constant-time comparison of two secrets of any length.

    Comparing the digests rather than the strings means the time taken does
    not depend on how much of the secret was right, nor on its length.
    """
    return hmac.compare_digest(
        hashlib.sha256(submitted.encode("utf-8")).digest(),
        hashlib.sha256(expected.encode("utf-8")).digest(),
    )


def epoch_of(passphrase: str) -> str:
    """16 hex characters that change when the passphrase changes and say nothing
    about it. A session issued under another epoch is invalid."""
    return hmac.new(
        passphrase.encode("utf-8"), _EPOCH_MESSAGE, hashlib.sha256
    ).hexdigest()[:16]


_BROWSERS = (
    ("Edge", re.compile(r"Edg(e|A|iOS)?/")),
    ("Firefox", re.compile(r"(Firefox|FxiOS)/")),
    ("Chrome", re.compile(r"(Chrome|CriOS)/")),
    ("Safari", re.compile(r"Safari/")),
)
_SYSTEMS = (
    ("iPhone", re.compile(r"iPhone")),
    ("iPad", re.compile(r"iPad")),
    ("Android", re.compile(r"Android")),
    ("Mac", re.compile(r"Macintosh|Mac OS X")),
    ("Windows", re.compile(r"Windows")),
    ("Linux", re.compile(r"Linux")),
)


def device_label(user_agent: str | None) -> str:
    """A coarse, human description of a device — "Safari on iPhone" — so the
    Office can list signed-in devices without storing a User-Agent string."""
    if not user_agent:
        return "A device"
    browser = next(
        (name for name, pattern in _BROWSERS if pattern.search(user_agent)), None
    )
    system = next(
        (name for name, pattern in _SYSTEMS if pattern.search(user_agent)), None
    )
    if browser and system:
        return f"{browser} on {system}"[:60]
    return (browser or system or "A device")[:60]
