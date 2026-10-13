"""The plant and source types the apps offer, and building one from its settings (spec 0017).

The only type lists: the YAML config and the web form both build their boxes here (APP-005).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from kiozesim import Plant, Source
from kiozesim.datasheet import Datasheet
from kiozesim.plants import REGISTRY
from kiozesim.sources import ConstantSource
from kiozesim.sources.digester import Digester
from kiozesim_tool.weather import FileWeatherSource, OpenMeteoSource

# Plant types whose spec is implemented (UI-005, SINK-026), in the order the page lists them.
PLANTS: dict[str, type[Plant]] = {  # type: ignore[type-arg]
    t: REGISTRY[t] for t in ("pv", "hawt", "vawt", "chp")
}

SOURCES: dict[str, type[Source]] = {  # type: ignore[type-arg]
    "weather_file": FileWeatherSource,
    "open_meteo": OpenMeteoSource,  # WX-030
    "constant": ConstantSource,
    "digester": Digester,
}


def plant_class(plant_type: str) -> type[Plant]:  # type: ignore[type-arg]
    if plant_type not in PLANTS:
        raise ValueError(f"unknown plant type {plant_type!r}; known: {sorted(PLANTS)}")
    return PLANTS[plant_type]


def source_class(source_type: str) -> type[Source]:  # type: ignore[type-arg]
    if source_type not in SOURCES:
        raise ValueError(f"unknown source type {source_type!r}; known: {sorted(SOURCES)}")
    return SOURCES[source_type]


def sheet_model(model: type[BaseModel]) -> type[Datasheet] | None:
    """The datasheet model a params model takes, if any."""
    for info in model.model_fields.values():
        ann = info.annotation
        if isinstance(ann, type) and issubclass(ann, Datasheet):
            return ann
    return None


def resolve(
    model: type[BaseModel], settings: Mapping[str, Any], base: Path | None = None
) -> tuple[dict[str, Any], dict[str, str]]:
    """Settings ready for `model`, and an error per field that could not be resolved.

    A datasheet given by name is loaded from the bundled ones; a relative `Path` setting resolves
    to `base`. A field with an error is left out of the settings.
    """
    data = dict(settings)
    errors: dict[str, str] = {}
    for key, info in model.model_fields.items():
        ann = info.annotation
        if key not in data:
            continue
        if isinstance(ann, type) and issubclass(ann, Datasheet) and isinstance(data[key], str):
            try:
                data[key] = ann.bundled(data[key])
            except FileNotFoundError:
                errors[key] = f"no bundled datasheet {data.pop(key)!r}"
        elif ann is Path and base is not None:
            path = Path(data[key])
            data[key] = path if path.is_absolute() else base / path
    return data, errors


def _validated(model: type[BaseModel], settings: Mapping[str, Any], base: Path | None) -> Any:
    data, errors = resolve(model, settings, base)
    if errors:
        raise ValueError("; ".join(f"{k}: {v}" for k, v in errors.items()))
    return model.model_validate(data)


def build_plant(
    plant_type: str, settings: Mapping[str, Any], base: Path | None = None
) -> Plant:  # type: ignore[type-arg]
    """A plant of `plant_type` from its settings (`name` and its params)."""
    cls = plant_class(plant_type)
    return cls(_validated(cls.params_model, settings, base))


def build_source(
    source_type: str, settings: Mapping[str, Any], base: Path | None = None
) -> Source:  # type: ignore[type-arg]
    """A source of `source_type` from its settings; relative `Path` settings resolve to `base`."""
    cls = source_class(source_type)
    return cls(_validated(cls.params_model, settings, base))
