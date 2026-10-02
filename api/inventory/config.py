"""What an operator must supply before a photograph can be kept.

this project ships a deployment other people run. A photograph of a
plant has to survive a redeploy, which means a volume the operator mounts and
names, so ``MOH_PHOTOS_IMAGE_DIR`` has **no default**. Unset, an upload is
refused with a 503 that names the variable, and the photo list still answers:
a deployment with nowhere to put a picture can still show the ones it has.

The two bounds below are a different kind of setting. They are not secrets
and not deployment-shaped; they are what stops an unauthenticated multipart
endpoint from being a way to fill somebody's disk.
They carry defaults on purpose, and an operator may lower them.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

#: 25 MiB. A phone photograph is a few megabytes, a camera's JPEG under
#: fifteen. Anything larger is a mistake or an attack, and the operator would
#: rather hear about it than store it.
DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024

#: Width × height. Fifty megapixels covers every phone and most cameras, and
#: the product is what a decoder would have to allocate: this is the
#: decompression-bomb bound, read from the header before anything decodes.
DEFAULT_MAX_IMAGE_PIXELS = 50_000_000


class PhotoSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOH_PHOTOS_", env_file=".env", extra="ignore"
    )

    #: Absolute path of the volume that holds specimen photographs. No default
    #:: the repository carries the name and the shape, never a
    #: value that works as-is.
    image_dir: Path | None = None

    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    max_image_pixels: int = DEFAULT_MAX_IMAGE_PIXELS


@lru_cache
def get_photo_settings() -> PhotoSettings:
    return PhotoSettings()
