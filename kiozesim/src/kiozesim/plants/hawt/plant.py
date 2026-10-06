"""Horizontal-axis wind turbine (adapter around windpowerlib, extra 'wind').

I/O contract
  input : HAWTInputs (TimeSeries, one shared index): wind_speed, temp_air, pressure
  output: PlantOutput, power_kw (kW) on the input index.
Datasheet: YAML in kiozesim/datasheets/hawt/, loaded via HAWTDatasheet.bundled(name).
"""

from __future__ import annotations

import pandas as pd

from kiozesim.datasheet import Datasheet
from kiozesim.plants.base import Plant, PlantOutput, PlantParams, TimeSeries


class HAWTDatasheet(Datasheet):
    shelf = "hawt"
    rated_power_kw: float
    rotor_diameter_m: float
    wind_speed_ms: list[float]  # power curve x
    power_kw: list[float]  # power curve y


class HAWTParams(PlantParams):
    datasheet: HAWTDatasheet
    hub_height_m: float
    n_turbines: int = 1


class HAWTInputs(TimeSeries):
    wind_speed: pd.Series  # m/s
    temp_air: pd.Series  # degC
    pressure: pd.Series  # Pa


class HAWTPlant(Plant[HAWTParams, HAWTInputs, PlantOutput]):
    params_model = HAWTParams
    inputs_model = HAWTInputs

    def _simulate(self, ts: HAWTInputs) -> PlantOutput:
        raise NotImplementedError("spec 0003 is still a draft")
