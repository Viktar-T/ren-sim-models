"""The `--config` YAML file: sources, plants, sinks and speed (specs 0011 SINK-021/022, 0016)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kiozesim import Plant
from kiozesim_tool.boxes import build_plant, build_source
from kiozesim_tool.sink import SINKS, Sink
from kiozesim_tool.sources import Source
from kiozesim_tool.wiring import Wires


class Config(BaseModel):
    speed: float = Field(default=1.0, ge=0)
    sources: list[dict[str, Any]] = Field(min_length=1)  # SRC-030
    plants: list[dict[str, Any]] = Field(min_length=1)
    sinks: list[dict[str, Any]] = Field(min_length=1)
    start: pd.Timestamp | None = None  # SINK-024; no time zone means UTC
    end: pd.Timestamp | None = None

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    @model_validator(mode="before")
    @classmethod
    def _no_weather_key(cls, data: Any) -> Any:
        if isinstance(data, dict) and "weather" in data:
            raise ValueError(
                "`weather:` is gone: list the weather under `sources:` as {type: weather_file, "
                "name: weather, path: ...} and wire plants with `from: weather`"
            )
        return data

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


def _settings(entry: dict[str, Any]) -> dict[str, Any]:
    """A box's own settings: the entry without `type` and the wiring `from` (read by wires_of)."""
    return {k: v for k, v in entry.items() if k not in ("type", "from")}


def build_plants(entries: list[dict[str, Any]]) -> list[Plant]:  # type: ignore[type-arg]
    """`{type, name, from, <params>}`; a datasheet given by name is a bundled one."""
    return [build_plant(str(e.get("type")), _settings(e)) for e in entries]


def build_sinks(entries: list[dict[str, Any]]) -> list[Sink]:
    sinks: list[Sink] = []
    for entry in entries:
        settings = dict(entry)
        name = settings.pop("type", None)
        if name not in SINKS:
            raise ValueError(f"unknown sink {name!r}; known: {sorted(SINKS)}")
        sinks.append(SINKS[name].from_settings(settings))
    return sinks


def build_sources(entries: list[dict[str, Any]], base: Path) -> list[Source]:  # type: ignore[type-arg]
    """`{type, name, [from], <settings>}`; relative paths resolve to the config's folder."""
    return [build_source(str(e.get("type")), _settings(e), base) for e in entries]


def wires_of(entries: list[dict[str, Any]]) -> Wires:
    """Box name -> what it takes input from; `from` is one name or a list of names (SRC-030)."""
    wires: dict[str, list[str]] = {}
    for entry in entries:
        froms = entry.get("from", [])
        froms = [froms] if isinstance(froms, str) else froms
        if not isinstance(froms, list) or not all(isinstance(f, str) for f in froms):
            raise ValueError(
                f"{entry.get('name')}: `from` must be a source or plant name, or a list of names"
            )
        wires[str(entry.get("name"))] = froms
    return wires
