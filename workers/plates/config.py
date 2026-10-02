"""What an operator must supply before a plate can be kept, or generated.

Two separate questions, and the design answers both the same way: *every operator
input is a parameter with no usable default, and nothing may depend on a service
the operator did not choose.*

**Where plates live.** The maps module settled this shape for map layers in #46 and
this module follows it rather than inventing a second one.
``MOH_PLATES_IMAGE_DIR`` has **no default**: unset, the journal answers 503
naming the variable, rather than writing into a container layer that the next
``docker stack deploy`` throws away. The size and pixel bounds *do* carry
defaults, because they are not operator secrets — they are the bounds that stop
a fetch from a remote catalogue from filling somebody's disk, and an operator may
lower them.

**Which catalogues this deployment may ask.** Wikimedia Commons needs no
credential. The Biodiversity Heritage Library's API v3 needs a key, so
``MOH_PLATES_BHL_API_KEY`` has no default either and BHL is simply not asked
without one. See `sources.py` for why that leaves the roster's *first* entry
unavailable on a fresh deployment.

**Whether plates can be generated at all.** The AI fallback needs a credential,
and this repository will never contain one. So the fallback is **off** unless an
operator configures both an endpoint and a key, and with it off the pipeline's
answer for a species it could not source is *"no plate for this one"* — never a
placeholder dressed as a plate. :func:`generation_is_configured` is the only
thing that decides, and `workers/plates/generation.py` asks it before doing
anything else.

Note what is *not* here: no default endpoint, no default model name, no
provider's hostname. A default endpoint would be a service the operator did not
choose, which is the half that is easiest to break by being helpful.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

#: 25 MiB, matching `api/grounds/config.py`. A scanned nineteenth-century plate
#: at a sane resolution is a few megabytes; the largest a public catalogue
#: usually serves is under ten. Anything past this is a mistake at the far end
#: and an operator would rather hear about it than store it.
DEFAULT_MAX_IMAGE_BYTES = 25 * 1024 * 1024

#: Width × height — the decompression-bomb bound, checked from the header
#: before anything decodes. A plate needs far less than this.
DEFAULT_MAX_IMAGE_PIXELS = 50_000_000

#: How many candidates one sourcing run will fetch before giving up on a
#: species. Each source may offer several; fetching all of them to pick one is
#: somebody else's bandwidth.
DEFAULT_MAX_CANDIDATES = 6

#: Seconds. A public catalogue that has not answered in this long is treated as
#: having nothing, which is the honest reading — not as a reason to generate.
DEFAULT_SOURCE_TIMEOUT_SECONDS = 20.0


class PlateSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOH_PLATES_", env_file=".env", extra="ignore"
    )

    #: Absolute path of the volume that holds plate images and thumbnails.
    #: No default: the repository carries the name and the shape,
    #: never a value that works as-is.
    image_dir: Path | None = None

    #: The Biodiversity Heritage Library's API v3 needs a key. It is first on
    #: the roster in `sources.py` and, with no key, the first source a fresh
    #: deployment tries is unavailable — which is honest, not broken. No
    #: default, same reason as everything else here.
    bhl_api_key: str | None = None

    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES
    max_image_pixels: int = DEFAULT_MAX_IMAGE_PIXELS
    max_candidates: int = DEFAULT_MAX_CANDIDATES
    source_timeout_seconds: float = DEFAULT_SOURCE_TIMEOUT_SECONDS

    #: The AI fallback, off unless an operator turns it on. Both halves are
    #: required: an endpoint with no key cannot authenticate, and a key with no
    #: endpoint has nowhere to go. Neither has a default, and this repository
    #: carries no value for either.
    generator_endpoint: str | None = None
    generator_api_key: str | None = None

    #: Which model, if the operator's endpoint needs telling. No default for the
    #: same reason: naming one here would name a provider nobody chose.
    generator_model: str | None = None

    #: An operator who has configured a generator may still want it off — for a
    #: month, or for a species they would rather leave blank. Flipping this to
    #: false is not the same as having no credential, and both end at the same
    #: honest answer.
    generation_enabled: bool = True


@lru_cache
def get_plate_settings() -> PlateSettings:
    return PlateSettings()


def generation_is_configured(settings: PlateSettings | None = None) -> bool:
    """May this deployment generate a plate at all?

    The one question `generation.py` asks. False is the default state of a
    fresh deployment and is not a failure: it is an operator who has not chosen
    a model provider, which the design says is their call and not ours.
    """
    settings = settings or get_plate_settings()
    return bool(
        settings.generation_enabled
        and settings.generator_endpoint
        and settings.generator_api_key
    )


def generation_unavailable_reason(settings: PlateSettings | None = None) -> str | None:
    """Why generation is off, in a sentence a reader can act on, or ``None``.

    This reaches an operator's screen and a worker's log, so it names the
    variables rather than saying "not configured". It deliberately does not
    recommend a provider.
    """
    settings = settings or get_plate_settings()
    if not settings.generation_enabled:
        return (
            "Plate generation is switched off in this deployment "
            "(MOH_PLATES_GENERATION_ENABLED=false)."
        )
    missing = [
        name
        for name, value in (
            ("MOH_PLATES_GENERATOR_ENDPOINT", settings.generator_endpoint),
            ("MOH_PLATES_GENERATOR_API_KEY", settings.generator_api_key),
        )
        if not value
    ]
    if missing:
        return (
            "This deployment has no image generator configured, so a species "
            "with no public-domain plate has no plate at all. Set "
            f"{' and '.join(missing)} to a provider you choose (the design — the "
            "repository carries the names, never values)."
        )
    return None
