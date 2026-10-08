"""Producer datasheets: manufacturer data kept in YAML, validated by a pydantic model per plant.

Bundled datasheets live in `kiozesim/datasheets/<shelf>/<name>.yaml`, one shelf per plant type.
A subclass names its shelf (`shelf = "pv"`) and inherits `available()` and `bundled(name)`.
It may also name a `catalogue`: datasheets kept outside the package (e.g. windpowerlib's turbine
library), listed and loaded through the same two methods (spec 0007, DS-011).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, ClassVar, Self

import yaml
from pydantic import BaseModel, ConfigDict


class Catalogue(ABC):
    """Datasheets kept outside the package, usually inside an optional library."""

    install_hint: ClassVar[str]  # how to get the library, e.g. "pip install 'kiozesim[wind]'"

    @abstractmethod
    def installed(self) -> bool:
        """Whether the library holding the catalogue is available."""

    @abstractmethod
    def names(self) -> list[str]:
        """Entry names; empty when not installed."""

    @abstractmethod
    def load(self, name: str) -> dict[str, Any] | None:
        """The datasheet fields of an entry, or None if there is no such entry."""


class Datasheet(BaseModel):
    """Base for a plant's datasheet model. Subclass and add the technology's fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    shelf: ClassVar[str | None] = None  # sub-folder of kiozesim/datasheets/ with this type's files
    catalogue: ClassVar[Catalogue | None] = None  # optional outside collection (DS-011)

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
    def file_names(cls) -> list[str]:
        """Names of the YAML files on this type's shelf."""
        shelf = cls._shelf_dir()
        if not shelf.is_dir():
            return []
        return sorted(f.name[: -len(".yaml")] for f in shelf.iterdir() if f.name.endswith(".yaml"))

    @classmethod
    def available(cls) -> list[str]:
        """Names of the datasheets shipped for this plant type: files plus catalogue entries."""
        extra = cls.catalogue.names() if cls.catalogue is not None else []
        return sorted(set(cls.file_names()) | set(extra))

    @classmethod
    def bundled(cls, name: str) -> Self:
        """Load a shipped datasheet by name (see `available()`); a file wins over the catalogue."""
        f = cls._shelf_dir() / f"{name}.yaml"
        if f.is_file():
            return cls.model_validate(yaml.safe_load(f.read_text()))
        if cls.catalogue is not None:
            if not cls.catalogue.installed():
                raise ImportError(
                    f"no bundled {cls.__name__} file {name!r}, and its catalogue needs a library:"
                    f" {cls.catalogue.install_hint}"
                )
            data = cls.catalogue.load(name)
            if data is not None:
                return cls.model_validate(data)
        available = cls.available()
        raise FileNotFoundError(f"no bundled {cls.__name__} {name!r}; available: {available}")
