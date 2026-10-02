"""What an operator must supply before a floor plan can be stored.

this project ships a deployment other people run. There is no object
store, no bucket and no credential, and an uploaded plan has to survive a
redeploy — which means a volume the operator mounts and names. So
``MOH_GROUNDS_IMAGE_DIR`` has **no default**: unset, uploads are refused with a
503 that names the variable, rather than writing into a container layer that
the next ``docker stack deploy`` throws away.

The two limits below are different in kind. They are not operator secrets and
not deployment-shaped; they are the bounds that stop an unauthenticated
multipart endpoint from being a way to fill somebody's disk. They carry
defaults on purpose, and an operator may lower them.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

#: 25 MiB. A scanned plat at 300dpi is a few megabytes; a phone photo of a
#: survey is under ten. Anything larger is a mistake or an attack, and either
#: way the operator would rather hear about it than store it.
DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024

#: Width × height. A 50-megapixel plan is already far past what a map needs,
#: and the product is what a decoder would have to allocate — this is the
#: decompression-bomb bound, checked from the header before anything decodes.
DEFAULT_MAX_IMAGE_PIXELS = 50_000_000


class GroundsSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOH_GROUNDS_", env_file=".env", extra="ignore"
    )

    #: Absolute path of the volume that holds uploaded plans and surveys.
    #: No default: the repository carries the name and the shape,
    #: never a value that works as-is.
    image_dir: Path | None = None

    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    max_image_pixels: int = DEFAULT_MAX_IMAGE_PIXELS


@lru_cache
def get_grounds_settings() -> GroundsSettings:
    return GroundsSettings()
