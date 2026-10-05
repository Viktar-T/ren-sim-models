"""Biogas plant: Buswell-Boyle yield + CHP (oemof.solph optional).

I/O contract
  input : BiogasInputs (TimeSeries, one shared index): feedstock_t_per_day
  output: PlantOutput, power_kw (kW) on the input index.
Datasheet: producer data in YAML (see datasheets/), loaded via BiogasDatasheet.from_yaml.
"""

from __future__ import annotations

import pandas as pd

from kioze_sim.datasheet import Datasheet
from kioze_sim.plants.base import Plant, PlantOutput, PlantParams, TimeSeries


class BiogasDatasheet(Datasheet):
    rated_electrical_kw: float
    electrical_efficiency: float
    thermal_efficiency: float
    min_load_fraction: float


class BiogasParams(PlantParams):
    datasheet: BiogasDatasheet
    substrate_formula: str  # e.g. "C6H10O5"
    biodegradability: float
    availability: float = 0.92


class BiogasInputs(TimeSeries):
    feedstock_t_per_day: pd.Series  # t/day


class BiogasPlant(Plant[BiogasParams, BiogasInputs, PlantOutput]):
    params_model = BiogasParams
    inputs_model = BiogasInputs

    def _simulate(self, ts: BiogasInputs) -> PlantOutput:
        raise NotImplementedError("spec 0005 is still a draft")
