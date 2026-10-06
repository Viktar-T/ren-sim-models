"""Producer datasheets: manufacturer data kept in YAML, validated by a pydantic model per plant.

Bundled datasheets live in `kiozesim/datasheets/<shelf>/<name>.yaml`, one shelf per plant type.
A subclass names its shelf (`shelf = "pv"`) and inherits `available()` and `bundled(name)`.
"""

from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import ClassVar, Self

import yaml
from pydantic import BaseModel, ConfigDict


class Datasheet(BaseModel):
    """Base for a plant's datasheet model. Subclass and add the technology's fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    shelf: ClassVar[str | None] = None  # sub-folder of kiozesim/datasheets/ with this type's files

    manufacturer: str
    model: str
    source: str | None = None  # where the numbers came from (URL, document)

    @classmethod
    def from_yaml(cls, path: str | Path) -> Self:
        data = yaml.safe_load(Path(path).read_text())
        return cls.model_validate(data)

    @classmethod
    def _shelf_dir(cls) -> Traversable:
        if not cls.shelf:
            raise TypeError(f"{cls.__name__} has no `shelf` (its kiozesim/datasheets/ sub-folder)")
        return files("kiozesim") / "datasheets" / cls.shelf

    @classmethod
    def available(cls) -> list[str]:
        """Names of the datasheets shipped for this plant type."""
        shelf = cls._shelf_dir()
        if not shelf.is_dir():
            return []
        return sorted(f.name[: -len(".yaml")] for f in shelf.iterdir() if f.name.endswith(".yaml"))

    @classmethod
    def bundled(cls, name: str) -> Self:
        """Load a shipped datasheet by name (see `available()`)."""
        f = cls._shelf_dir() / f"{name}.yaml"
        if not f.is_file():
            available = cls.available()
            raise FileNotFoundError(f"no bundled {cls.__name__} {name!r}; available: {available}")
        return cls.model_validate(yaml.safe_load(f.read_text()))
