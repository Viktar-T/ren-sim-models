"""Source types the apps offer, by name, and building one from settings (spec 0016)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from kiozesim import Source
from kiozesim.sources import ConstantSource
from kiozesim.sources.digester import Digester
from kiozesim_utils.weather import FileWeatherSource

SOURCES: dict[str, type[Source]] = {  # type: ignore[type-arg]
    "weather_file": FileWeatherSource,
    "constant": ConstantSource,
    "digester": Digester,
}


def build_source(
    source_type: str,
    settings: Mapping[str, Any],
    base: Path | None = None,
    types: Mapping[str, type[Source]] | None = None,  # type: ignore[type-arg]
) -> Source:  # type: ignore[type-arg]
    """A source of `source_type` from its settings; relative `Path` settings resolve to `base`."""
    types = SOURCES if types is None else types
    if source_type not in types:
        raise ValueError(f"unknown source type {source_type!r}; known: {sorted(types)}")
    cls = types[source_type]
    data = dict(settings)
    for key, info in cls.params_model.model_fields.items():
        if info.annotation is Path and key in data and base is not None:
            path = Path(data[key])
            data[key] = path if path.is_absolute() else base / path
    return cls(cls.params_model.model_validate(data))
