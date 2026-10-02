"""The fallback that draws a plate, when an operator has chosen a model to draw it.

Off by default, and the default is not a degraded mode — it is the shape the design asks for:
*nothing may depend on a service the operator did not choose.*
This repository contains no credential and no endpoint, so a fresh deployment
cannot generate, and the pipeline's answer for a species the catalogues missed
is "no plate for this one". There is no placeholder branch. A grey rectangle
with a plant name under it in a book of plates is a plate as far as any reader
is concerned, and this module would rather return nothing.

What it guarantees when it *is* configured:

* the plate is ``origin: generated``, with no licence, no attribution and no
  ``source_id`` — `domain.py` refuses to build it otherwise;
* the prompt comes from `style.py` and nowhere else, so the forbidden marks
  (plate numbers, signatures, stamps — the things that make an image claim a
  provenance) are on every request;
* ``style`` is recorded on the row, which is what the frozen schema's ``style``
  column is for: a reader who asks "what made this" gets the actual string.

It does **not** approve anything, and it does not know how to. See
`domain.Plate.approve`.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol, runtime_checkable

from . import storage
from .config import (
    PlateSettings,
    generation_is_configured,
    generation_unavailable_reason,
    get_plate_settings,
)
from .domain import Plate
from .style import HOUSE_STYLE, prompt_for


class GenerationUnavailable(RuntimeError):
    """No generator is configured, or the one configured would not answer.

    Carries a sentence an operator can act on. The pipeline turns it into an
    outcome with a reason rather than into a placeholder.
    """


@runtime_checkable
class PlateGenerator(Protocol):
    """Whatever an operator pointed this deployment at."""

    async def generate(
        self,
        run: Any,
        store: storage.PlateImageStore,
        settings: PlateSettings | None = None,
    ) -> Plate: ...


class HttpPlateGenerator:
    """The real one: an OpenAI-shaped images endpoint the operator names.

    "OpenAI-shaped" is a description of a request body, not an endorsement of a
    provider: the operator supplies the URL, so this works against anything
    that accepts ``{"prompt": ..., "model": ...}`` and answers with image
    bytes or a base64 payload. The repository names no host.

    The API key goes in a header and never into a URL, a log line or an
    exception message — :meth:`_post` is the only place it is read, and the
    error paths below quote the status code and not the request.
    """

    def __init__(self, fetcher: Any) -> None:
        self._fetcher = fetcher

    async def generate(
        self,
        run: Any,
        store: storage.PlateImageStore,
        settings: PlateSettings | None = None,
    ) -> Plate:
        settings = settings or get_plate_settings()
        if not generation_is_configured(settings):
            raise GenerationUnavailable(
                generation_unavailable_reason(settings)
                or "No image generator is configured in this deployment."
            )

        prompt = prompt_for(run.name)
        try:
            data = await self._fetcher.generate_image(
                endpoint=str(settings.generator_endpoint),
                api_key=str(settings.generator_api_key),
                model=settings.generator_model,
                prompt=prompt,
            )
        except Exception as exc:
            raise GenerationUnavailable(
                "The image generator this deployment is configured with did "
                f"not produce a plate for {run.name} ({type(exc).__name__}), so "
                "it has none. Nothing was stored."
            ) from exc

        if not data:
            raise GenerationUnavailable(
                f"The image generator returned no image for {run.name}, so it "
                "has no plate. An empty response is not a plate."
            )

        try:
            extension = storage.sniff_extension(data)
        except storage.UnsupportedImageFormat as exc:
            raise GenerationUnavailable(
                f"The image generator returned something that is not a PNG or "
                f"a JPEG for {run.name}, so it has no plate: {exc}"
            ) from exc

        plate_id = str(uuid.uuid4())
        key = storage.key_for(plate_id, extension)
        store.put(key, data)

        # No licence, no attribution, no source_id. `domain.Plate` enforces it;
        # this call simply has nothing to pass, which is the point.
        return Plate(
            id=plate_id,
            origin="generated",
            image_key=key,
            species_id=run.species_id,
            specimen_id=run.specimen_id,
            style=HOUSE_STYLE,
        )
