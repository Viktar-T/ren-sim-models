"""Gas engine (CHP): fuel energy in, electricity and heat out. Spec 0015.

I/O contract
  input : CHPInputs (TimeSeries, one shared index): fuel_kw, fuel energy flow (lower heating value),
          e.g. `DigesterOutput.fuel_kw` (spec 0005)
  output: CHPOutput, power_kw plus heat_kw and flared_kw on the input index.
Datasheet: YAML in kiozesim/datasheets/chp/, loaded via CHPDatasheet.bundled(name).
"""

from __future__ import annotations

from typing import Self

import pandas as pd
from pydantic import ConfigDict, Field, model_validator

from kiozesim.datasheet import Datasheet
from kiozesim.plants.base import Plant, PlantOutput, PlantParams, TimeSeries


class CHPDatasheet(Datasheet):
    shelf = "chp"

    model_config = ConfigDict(allow_inf_nan=False)

    rated_electrical_kw: float = Field(gt=0)  # maximum electric output
    electrical_efficiency: float = Field(gt=0, lt=1)  # fuel -> electricity, full load
    thermal_efficiency: float = Field(ge=0, lt=1)  # fuel -> useful heat, full load

    @model_validator(mode="after")
    def _energy_balance(self) -> Self:
        if self.electrical_efficiency + self.thermal_efficiency > 1:
            raise ValueError("electrical_efficiency + thermal_efficiency must not exceed 1")
        return self


class CHPParams(PlantParams):
    model_config = ConfigDict(allow_inf_nan=False)

    datasheet: CHPDatasheet
    availability: float = Field(default=0.92, ge=0, le=1)  # fraction of time the engine runs


class CHPInputs(TimeSeries):
    fuel_kw: pd.Series  # fuel energy flow, kW (lower heating value), period average

    @model_validator(mode="after")
    def _non_negative(self) -> Self:
        if (self.fuel_kw < 0).any():
            raise ValueError("fuel_kw: must be >= 0")
        return self


class CHPOutput(PlantOutput):
    heat_kw: pd.Series
    flared_kw: pd.Series


class CHPPlant(Plant[CHPParams, CHPInputs, CHPOutput]):
    params_model = CHPParams
    inputs_model = CHPInputs
    output_model = CHPOutput

    def _simulate(self, ts: CHPInputs) -> CHPOutput:
        ds = self.params.datasheet
        fuel = ts.fuel_kw.astype(float)
        fuel_max_kw = ds.rated_electrical_kw / ds.electrical_efficiency
        burned = self.params.availability * fuel.clip(upper=fuel_max_kw)
        return CHPOutput(
            power_kw=(burned * ds.electrical_efficiency).rename("power_kw"),
            heat_kw=(burned * ds.thermal_efficiency).rename("heat_kw"),
            flared_kw=(fuel - burned).clip(lower=0).rename("flared_kw"),
        )
