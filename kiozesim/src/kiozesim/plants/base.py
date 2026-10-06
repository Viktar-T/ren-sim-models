"""The Plant contract: params at construction, at most one TimeSeries struct at simulate()."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Generic, Self, TypeVar, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from kiozesim.timegrid import TimeGridError, validate_time_index


class PlantParams(BaseModel):
    """Base for plant parameter models: immutable, strict, no unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str


class TimeSeries(BaseModel):
    """Base for a plant's time-varying input: a struct of pd.Series sharing ONE index.

    Subclass per plant and declare one `pd.Series` field per quantity (units in the name or
    description). Different time steps are rejected here; resample before constructing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    @model_validator(mode="after")
    def _share_one_index(self) -> Self:
        series = {k: v for k, v in self if isinstance(v, pd.Series)}
        if not series:
            raise ValueError("a TimeSeries struct needs at least one pd.Series field")
        first = next(iter(series.values())).index
        validate_time_index(first)
        for k, s in series.items():
            if not s.index.equals(first):
                raise TimeGridError(f"{k}: index differs from the other series")
            if s.isna().any():
                raise ValueError(f"{k}: contains NaN")
        return self

    @property
    def index(self) -> pd.DatetimeIndex:
        for _, v in self:
            if isinstance(v, pd.Series):
                return cast(pd.DatetimeIndex, v.index)
        raise AssertionError("unreachable: validated in __init__")

    @classmethod
    def from_frame(cls, df: pd.DataFrame, **extra: object) -> Self:
        """Build from a DataFrame, taking the columns this struct declares."""
        cols = {c: df[c] for c in df.columns if c in cls.model_fields}
        return cls(**cols, **extra)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame({k: v for k, v in self if isinstance(v, pd.Series)})


class PlantOutput(BaseModel):
    """Minimum output of every plant. Plants may subclass to add more (e.g. heat_kw).

    `power_kw` is a Series (average kW per period) for time-series plants, or a float
    (steady-state kW) for plants that take no input.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    power_kw: pd.Series | float

    @field_validator("power_kw")
    @classmethod
    def _check_power(cls, v: pd.Series | float) -> pd.Series | float:
        arr = np.asarray(v, dtype=float)
        if not np.isfinite(arr).all() or (arr < 0).any():
            raise ValueError("power_kw must be finite and non-negative")
        return v.rename("power_kw") if isinstance(v, pd.Series) else float(v)


P = TypeVar("P", bound=PlantParams)
I = TypeVar("I", bound="TimeSeries | None")  # noqa: E741
O = TypeVar("O", bound=PlantOutput)  # noqa: E741


class Plant(ABC, Generic[P, I, O]):
    """A pure function of (params, optional TimeSeries) -> output."""

    params_model: ClassVar[type[PlantParams]]
    inputs_model: ClassVar[type[TimeSeries] | None] = None  # None: plant takes no input
    output_model: ClassVar[type[PlantOutput]] = PlantOutput

    def __init__(self, params: P) -> None:
        self.params = params

    @property
    def name(self) -> str:
        return self.params.name

    def simulate(self, ts: I | None = None) -> O:
        """One TimeSeries struct, or nothing for plants without time-varying input."""
        model = self.inputs_model
        if model is None:
            if ts is not None:
                raise TypeError(f"{self.name}: takes no time series")
        elif not isinstance(ts, model):
            raise TypeError(f"{self.name}: expected a {model.__name__}")
        out = self._simulate(cast(I, ts))
        if ts is not None:
            if not isinstance(out.power_kw, pd.Series) or not out.power_kw.index.equals(ts.index):
                raise ValueError(f"{self.name}: power_kw must be a Series on the input's index")
        elif isinstance(out.power_kw, pd.Series):
            raise ValueError(f"{self.name}: a plant without input must return a scalar")
        return out

    @abstractmethod
    def _simulate(self, ts: I) -> O:
        """Implement the model."""
