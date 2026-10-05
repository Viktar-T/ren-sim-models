"""PV system (adapter around pvlib, optional extra 'pv').

I/O contract
  input : PVInputs (TimeSeries, one shared index): ghi, dni, dhi, temp_air, wind_speed
  output: PlantOutput, power_kw (kW) on the input index.
Datasheet: producer data in YAML (see datasheets/), loaded via PVDatasheet.from_yaml.
"""

from __future__ import annotations

import pandas as pd

from kioze_sim.datasheet import Datasheet
from kioze_sim.plants.base import Plant, PlantOutput, PlantParams, TimeSeries


class PVDatasheet(Datasheet):
    pdc0_w: float
    gamma_pdc_per_k: float
    area_m2: float


class PVParams(PlantParams):
    datasheet: PVDatasheet
    latitude: float
    longitude: float
    altitude_m: float = 0.0
    tilt_deg: float
    azimuth_deg: float
    n_modules: int
    inverter_pdc0_w: float


class PVInputs(TimeSeries):
    ghi: pd.Series  # W/m2
    dni: pd.Series  # W/m2
    dhi: pd.Series  # W/m2
    temp_air: pd.Series  # degC
    wind_speed: pd.Series  # m/s


class PVPlant(Plant[PVParams, PVInputs, PlantOutput]):
    params_model = PVParams
    inputs_model = PVInputs

    def _simulate(self, ts: PVInputs) -> PlantOutput:
        raise NotImplementedError("spec 0002 is still a draft")
