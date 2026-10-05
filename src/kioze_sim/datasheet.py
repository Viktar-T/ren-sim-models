"""Producer datasheets: manufacturer data kept in YAML, validated by a pydantic model per plant."""

from __future__ import annotations

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict


class Datasheet(BaseModel):
    """Base for a plant's datasheet model. Subclass and add the technology's fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manufacturer: str
    model: str
    source: str | None = None  # where the numbers came from (URL, document, "placeholder")

    @classmethod
    def from_yaml(cls, path: str | Path) -> Self:
        data = yaml.safe_load(Path(path).read_text())
        return cls.model_validate(data)
