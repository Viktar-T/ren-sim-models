"""Sources: boxes that feed time series into plant chains (specs 0016, 0019).

"Source" is the tool's word: the library holds plants only. A source makes time series from its
settings and an optional input table; it does not wire itself: the app hands each one its input
table. Weather sources are in `kiozesim_tool.weather`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import ClassVar, Generic, TypeVar

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from kiozesim.errors import MissingInputError
from kiozesim.timegrid import TimeGridError, validate_time_index

P = TypeVar("P", bound=BaseModel)


class Source(ABC, Generic[P]):
    """A pure function of (params, time axis, optional input table) -> output table."""

    params_model: ClassVar[type[BaseModel]]

    def __init__(self, params: P) -> None:
        self.params = params

    @property
    def name(self) -> str:
        return str(getattr(self.params, "name"))  # noqa: B009

    def simulate(self, index: pd.DatetimeIndex, inputs: pd.DataFrame | None = None) -> pd.DataFrame:
        """Output columns on `index`; `inputs`, when given, must be on the same `index`."""
        validate_time_index(index)
        if inputs is not None and not inputs.index.equals(index):
            raise TimeGridError(f"{self.name}: inputs are not on the requested time axis")
        out = self._simulate(index, inputs)
        if not isinstance(out, pd.DataFrame) or not out.index.equals(index):
            raise ValueError(f"{self.name}: output must be a DataFrame on the requested time axis")
        return out

    def _require(self, inputs: pd.DataFrame | None, columns: Iterable[str]) -> pd.DataFrame:
        """The input table, after checking it holds `columns` (SRC-002)."""
        have = set() if inputs is None else {str(c) for c in inputs.columns}
        missing = [c for c in columns if c not in have]
        if missing or inputs is None:
            raise MissingInputError(self.name, missing)
        return inputs

    @abstractmethod
    def _simulate(self, index: pd.DatetimeIndex, inputs: pd.DataFrame | None) -> pd.DataFrame:
        """Implement the model."""


class ConstantParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    name: str = Field(min_length=1)
    # output column -> value
    values: dict[str, float] = Field(min_length=1, examples=[{"fuel_kw": 1500}])


class ConstantSource(Source[ConstantParams]):
    """A fixed value on every step: for testing a plant without a real source (SRC-005)."""

    params_model = ConstantParams

    def _simulate(self, index: pd.DatetimeIndex, inputs: pd.DataFrame | None) -> pd.DataFrame:
        return pd.DataFrame(dict(self.params.values), index=index, dtype=float)
