"""The feed token — the only credential this application issues.

the design says the project ships a deployment other people run, with no
credential in the repository. The calendar token is the single exception the
product needs: an ICS URL is fetched by Google's and Apple's servers, which
carry no session, so the secret has to be in the URL. That makes these rules
non-negotiable, and this module is the one place they live.

* **Minted from ``secrets``**, never from a uuid, a hash of the member's name,
  or anything else a reader could guess or reconstruct from the database.
* **Never reused across feeds.** One feed, one token, so revoking a phone's
  subscription cannot disturb a spouse's.
* **Never logged, never measured, never put in an error message.** There is no
  logging call in this package that takes a token, and :func:`redact` exists so
  that a debug line about a feed is possible without one.
* **Compared in constant time.** The lookup path is a database index in live
  mode, but the in-memory store would otherwise leak the token's prefix through
  comparison timing, and the two paths should not differ on a security property.
"""

from __future__ import annotations

import secrets

#: 32 bytes, URL-safe. Long enough that guessing is not a strategy, short
#: enough that the resulting `webcal://` URL still fits on a QR code.
TOKEN_BYTES = 32

#: How much of a token may appear anywhere a human can read: enough to tell two
#: feeds apart in a support conversation, not enough to fetch either.
VISIBLE_PREFIX = 4


def mint() -> str:
    """A fresh token. Called once per feed and once per revocation."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def matches(candidate: str, stored: str) -> bool:
    """Constant-time comparison, so a scan cannot be turned into a guess."""
    return secrets.compare_digest(candidate, stored)


def redact(token: str) -> str:
    """``"h7Qk…"`` — safe to print. Nothing else in this package ever prints one."""
    return f"{token[:VISIBLE_PREFIX]}…" if token else "…"


def webcal_url(base_url: str, token: str) -> str:
    """The subscribe URL. ``webcal://`` is what Apple and Google act on."""
    return f"{https_url(base_url, token)}".replace("https://", "webcal://", 1).replace(
        "http://", "webcal://", 1
    )


def https_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/api/v1/calendar/{token}.ics"
