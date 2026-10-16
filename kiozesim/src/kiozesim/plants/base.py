"""The Plant contract: params at construction, at most one TimeSeries struct at simulate().

Plants also run one step at a time, so a chain can pass values between them (spec 0019): the
plant's memory (`State`) is handed in and handed back, never kept in the plant.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, Self, TypeVar, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from kiozesim.errors import CannotBeAsked, MissingInputError
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
        given = cols.keys() | extra.keys()
        missing = [n for n, f in cls.model_fields.items() if f.is_required() and n not in given]
        if missing:
            raise MissingInputError(cls.__name__, missing)  # SRC-003
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

    def to_frame(self, index: pd.DatetimeIndex | None = None) -> pd.DataFrame:
        """One column per field (CHAIN-004); single values are spread over `index`.

        Optional fields left empty (None) are left out.
        """
        values = {k: v for k, v in self if v is not None}
        if index is None:
            series = [v for v in values.values() if isinstance(v, pd.Series)]
            if not series:
                raise ValueError("an output of single values needs an index to spread them over")
            index = cast(pd.DatetimeIndex, series[0].index)
        return pd.DataFrame(
            {k: (v if isinstance(v, pd.Series) else float(v)) for k, v in values.items()},
            index=index,
        )


State = Any  # a plant's memory between steps: an immutable value, or None for no memory


@dataclass(frozen=True)
class Sizing:
    """What a plant needs, on average, to give an average output (spec 0019, `Plant.needs`)."""

    inputs: dict[str, float]  # average input needed per input name, kW
    given: dict[str, float]  # what the plant can give per wanted output, <= wanted
    feed_t_per_day: dict[str, float] = field(default_factory=dict)  # digester: feed per substrate


P = TypeVar("P", bound=PlantParams)
I = TypeVar("I", bound="TimeSeries | None")  # noqa: E741
O = TypeVar("O", bound=PlantOutput)  # noqa: E741


class Plant(ABC, Generic[P, I, O]):
    """A pure function of (params, optional TimeSeries) -> output."""

    params_model: ClassVar[type[PlantParams]]
    inputs_model: ClassVar[type[TimeSeries] | None] = None  # None: plant takes no input
    output_model: ClassVar[type[PlantOutput]] = PlantOutput
    follows_requests: ClassVar[bool] = False  # step makes no more than is wanted (CHAIN-003)
    askable: ClassVar[tuple[str, ...]] = ()  # outputs sizing can ask for, average kW (`needs`)

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

    # --- one step at a time (spec 0019). Defaults suit plants without memory. ---

    def initial_state(self) -> State:
        """The plant's memory at the start of a run; None for a plant without memory."""
        return None

    def want(
        self,
        state: State,
        t: pd.Timestamp,
        inputs: Mapping[str, float],
        wanted: Mapping[str, float],
        dt_h: float,
    ) -> dict[str, float]:
        """Backward pass: input wanted per flow name; a name left out means no limit.

        `inputs` holds this step's values from sources only (flows from the plant in front are not
        known yet); `wanted` the outputs the plant behind asked for.
        """
        return {}

    def step(
        self,
        state: State,
        t: pd.Timestamp,
        inputs: Mapping[str, float],
        wanted: Mapping[str, float],
        dt_h: float,
    ) -> tuple[State, dict[str, float]]:
        """Forward pass: one step of `dt_h` hours starting at `t`; the new state and the outputs.

        Default: `simulate` on this one step, so a plant without memory steps exactly as it
        simulates (CHAIN-002).
        """
        if self.inputs_model is None:
            out = self.simulate()
        else:
            index = pd.date_range(t, periods=2, freq=pd.Timedelta(hours=dt_h))
            fields = self.inputs_model.model_fields
            series = {k: pd.Series(float(v), index=index) for k, v in inputs.items() if k in fields}
            out = self.simulate(cast(I, self.inputs_model(**series)))
        return state, {
            k: float(v.iloc[0]) if isinstance(v, pd.Series) else float(v)
            for k, v in out
            if v is not None
        }

    def needs(self, wanted: Mapping[str, float]) -> Sizing:
        """Sizing: average inputs for an average output. Default: cannot be asked (CHAIN-024)."""
        raise CannotBeAsked(self.name)

    def check_asked(self, wanted: Mapping[str, float]) -> None:
        """Reject output names sizing cannot ask this plant for, listing the ones it can."""
        unknown = sorted(set(wanted) - set(self.askable))
        if unknown:
            options = ", ".join(self.askable)
            raise ValueError(
                f"{self.name} cannot be asked for {', '.join(unknown)}; "
                f"ask for {options} (average kW, e.g. {self.askable[0]}=100)"
            )

    @classmethod
    def input_names(cls) -> tuple[str, ...]:
        return tuple(cls.inputs_model.model_fields) if cls.inputs_model is not None else ()

    @classmethod
    def required_inputs(cls) -> tuple[str, ...]:
        if cls.inputs_model is None:
            return ()
        return tuple(n for n, f in cls.inputs_model.model_fields.items() if f.is_required())

    @classmethod
    def output_names(cls) -> tuple[str, ...]:
        return tuple(cls.output_model.model_fields)
