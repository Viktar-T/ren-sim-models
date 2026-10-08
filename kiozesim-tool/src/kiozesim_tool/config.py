"""The `--config` YAML file: plants, weather source, sinks and speed (spec 0011, SINK-021/022)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kiozesim import Plant
from kiozesim.datasheet import Datasheet
from kiozesim.plants import REGISTRY
from kiozesim_tool.sink import SINKS, Sink
from kiozesim_tool.weather import FileWeatherSource, WeatherSource


class FileWeather(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["file"]
    path: Path


class Config(BaseModel):
    speed: float = Field(default=1.0, ge=0)
    plants: list[dict[str, Any]] = Field(min_length=1)
    weather: FileWeather
    sinks: list[dict[str, Any]] = Field(min_length=1)
    start: pd.Timestamp | None = None  # SINK-024; no time zone means UTC
    end: pd.Timestamp | None = None

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    @field_validator("start", "end", mode="before")
    @classmethod
    def _utc(cls, v: object) -> pd.Timestamp | None:
        if v is None:
            return None
        ts = pd.Timestamp(v)  # type: ignore[arg-type]
        return ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")

    @model_validator(mode="after")
    def _range(self) -> Config:
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("end must be later than start")
        if self.speed == 0 and self.end is None:
            raise ValueError("speed 0 needs an end, otherwise it floods the sinks without end")
        return self


def load(path: str | Path) -> tuple[Config, Path]:
    """The parsed config and the folder relative paths in it are resolved against."""
    path = Path(path)
    data = yaml.safe_load(path.read_text())
    return Config.model_validate(data), path.resolve().parent


def build_plants(entries: list[dict[str, Any]]) -> list[Plant]:  # type: ignore[type-arg]
    """`{type, name, <params>}`; a datasheet given by name is loaded from the bundled ones."""
    plants: list[Plant] = []  # type: ignore[type-arg]
    for entry in entries:
        data = dict(entry)
        plant_type = data.pop("type", None)
        if plant_type not in REGISTRY:
            raise ValueError(f"unknown plant type {plant_type!r}; known: {sorted(REGISTRY)}")
        cls = REGISTRY[plant_type]
        for key, info in cls.params_model.model_fields.items():
            ann = info.annotation
            is_sheet = isinstance(ann, type) and issubclass(ann, Datasheet)
            if is_sheet and isinstance(data.get(key), str):
                data[key] = ann.bundled(data[key])  # type: ignore[union-attr]
        plants.append(cls(cls.params_model.model_validate(data)))
    return plants


def build_sinks(entries: list[dict[str, Any]]) -> list[Sink]:
    sinks: list[Sink] = []
    for entry in entries:
        settings = dict(entry)
        name = settings.pop("type", None)
        if name not in SINKS:
            raise ValueError(f"unknown sink {name!r}; known: {sorted(SINKS)}")
        sinks.append(SINKS[name].from_settings(settings))
    return sinks


def build_weather(cfg: FileWeather, base: Path) -> WeatherSource:
    path = cfg.path if cfg.path.is_absolute() else base / cfg.path
    return FileWeatherSource(path)
