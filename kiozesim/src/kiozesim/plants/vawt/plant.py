"""Vertical-axis wind turbine (custom DMST / Cp(TSR) model).

I/O contract
  input : VAWTInputs (TimeSeries, one shared index): wind_speed, temp_air, pressure
  output: PlantOutput, power_kw (kW) on the input index.
Datasheet: YAML in kiozesim/datasheets/vawt/, loaded via VAWTDatasheet.bundled(name).
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

from kiozesim.datasheet import Datasheet
from kiozesim.plants.base import Plant, PlantOutput, PlantParams, TimeSeries


class VAWTDatasheet(Datasheet):
    shelf = "vawt"
    rotor_type: Literal["darrieus", "savonius"]
    rated_power_kw: float
    swept_area_m2: float
    tsr: list[float] = []  # optional measured Cp(TSR) curve
    cp: list[float] = []


class VAWTParams(PlantParams):
    datasheet: VAWTDatasheet
    hub_height_m: float
    n_turbines: int = 1


class VAWTInputs(TimeSeries):
    wind_speed: pd.Series  # m/s
    temp_air: pd.Series  # degC
    pressure: pd.Series  # Pa


class VAWTPlant(Plant[VAWTParams, VAWTInputs, PlantOutput]):
    params_model = VAWTParams
    inputs_model = VAWTInputs

    def _simulate(self, ts: VAWTInputs) -> PlantOutput:
        raise NotImplementedError("spec 0004 is still a draft")
