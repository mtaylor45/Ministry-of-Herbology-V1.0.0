"""The household's shared sign-in. The maintainers.

One passphrase, held by the operator as the swarm secret
``moh_household_passphrase``; a random session token per signed-in device,
stored only as a hash; every route the contract does not mark
``security: []`` refused without one.

Layout:

* :mod:`.secrets` — reads the three operator secrets from ``MOH_SECRETS_DIR``.
* :mod:`.tokens` — token generation and hashing, passphrase comparison, the
  rotation epoch, the coarse device label.
* :mod:`.store` — where sessions live: memory (the demo) or Postgres.
* :mod:`.ratelimit` — counting failed sign-ins: memory or Redis.
* :mod:`.policy` — which operations are open, read from the contract itself.
* :mod:`.service` — the pieces together, one per process.
* :mod:`.middleware` — enforcement, in one place.
* :mod:`.router` — the five ``/auth`` routes.
"""

from app.auth.middleware import AuthMiddleware
from app.auth.router import router

__all__ = ["AuthMiddleware", "router"]
