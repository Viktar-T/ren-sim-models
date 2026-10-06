"""Boiler with heat store (oemof.thermal; optional FMU adapter).

I/O contract
  input : BoilerInputs (TimeSeries, one shared index): heat_demand_kw
  output: PlantOutput, power_kw (kW) on the input index.
Datasheet: YAML in kiozesim/datasheets/boiler/, loaded via BoilerDatasheet.bundled(name).
"""

from __future__ import annotations

import pandas as pd

from kiozesim.datasheet import Datasheet
from kiozesim.plants.base import Plant, PlantOutput, PlantParams, TimeSeries


class BoilerDatasheet(Datasheet):
    shelf = "boiler"
    rated_thermal_kw: float
    efficiency: float


class BoilerParams(PlantParams):
    datasheet: BoilerDatasheet
    tank_volume_m3: float
    tank_u_value_w_m2k: float


class BoilerInputs(TimeSeries):
    heat_demand_kw: pd.Series  # kW


class BoilerPlant(Plant[BoilerParams, BoilerInputs, PlantOutput]):
    params_model = BoilerParams
    inputs_model = BoilerInputs

    def _simulate(self, ts: BoilerInputs) -> PlantOutput:
        raise NotImplementedError("spec 0006 is still a draft")
