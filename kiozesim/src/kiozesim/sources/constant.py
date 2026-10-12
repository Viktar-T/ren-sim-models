"""A fixed value on every step: for testing a plant without a real source (spec 0016, SRC-005)."""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from kiozesim.sources.base import Source


class ConstantParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    name: str = Field(min_length=1)
    # output column -> value
    values: dict[str, float] = Field(min_length=1, examples=[{"fuel_kw": 1500}])


class ConstantSource(Source[ConstantParams]):
    params_model = ConstantParams

    def _simulate(self, index: pd.DatetimeIndex, inputs: pd.DataFrame | None) -> pd.DataFrame:
        return pd.DataFrame(dict(self.params.values), index=index, dtype=float)
