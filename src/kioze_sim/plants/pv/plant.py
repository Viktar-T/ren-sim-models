"""PV system: PVWatts model via pvlib's ModelChain (optional extra 'pv'). Spec 0002.

I/O contract
  input : PVInputs (TimeSeries, one shared index, period averages labelled at period start):
          ghi_w_m2, temp_air_c, wind_speed_m_s, optionally dni_w_m2 + dhi_w_m2
  output: PVOutput, power_kw (AC kW) plus dc_kw, poa_w_m2, temp_cell_c on the input index.
Datasheet: producer data in YAML (see datasheets/), loaded via PVDatasheet.from_yaml.
"""

from __future__ import annotations

from typing import Literal, Self

import numpy as np
import pandas as pd
from pydantic import ConfigDict, Field, model_validator

from kioze_sim.datasheet import Datasheet
from kioze_sim.plants.base import Plant, PlantOutput, PlantParams, TimeSeries
from kioze_sim.timegrid import TimeGridError

MAX_STEP = pd.Timedelta(hours=1)

# SAPM cell-temperature presets (pvlib.temperature.TEMPERATURE_MODEL_PARAMETERS["sapm"])
Mounting = Literal[
    "open_rack_glass_polymer",
    "open_rack_glass_glass",
    "close_mount_glass_glass",
    "insulated_back_glass_polymer",
]


class PVDatasheet(Datasheet):
    model_config = ConfigDict(allow_inf_nan=False)

    pdc0_w: float = Field(gt=0)  # rated module power at STC
    gamma_pdc_per_k: float = Field(ge=-0.01, le=0)  # e.g. -0.35 %/degC -> -0.0035


class PVParams(PlantParams):
    model_config = ConfigDict(allow_inf_nan=False)

    datasheet: PVDatasheet
    latitude_deg: float = Field(ge=-90, le=90)
    longitude_deg: float = Field(ge=-180, le=180)
    altitude_m: float = Field(default=0.0, ge=-500, le=9000)
    tilt_deg: float = Field(ge=0, le=90)
    azimuth_deg: float = Field(ge=0, lt=360)  # clockwise from north, 180 = south
    n_modules: int = Field(ge=1)
    inverter_ac_kw: float = Field(gt=0)
    inverter_efficiency: float = Field(default=0.96, gt=0, le=1)
    losses_pct: float = Field(default=14.0, ge=0, lt=100)
    albedo: float = Field(default=0.2, ge=0, le=1)
    mounting: Mounting = "open_rack_glass_polymer"


class PVInputs(TimeSeries):
    ghi_w_m2: pd.Series
    temp_air_c: pd.Series
    wind_speed_m_s: pd.Series  # at 10 m height
    dni_w_m2: pd.Series | None = None  # with dhi_w_m2, or both omitted (estimated from GHI)
    dhi_w_m2: pd.Series | None = None

    @model_validator(mode="after")
    def _check_values(self) -> Self:
        if (self.dni_w_m2 is None) != (self.dhi_w_m2 is None):
            raise ValueError("dni_w_m2 and dhi_w_m2 must be given together or not at all")
        for name, s in self:
            if not isinstance(s, pd.Series):
                continue
            values = s.to_numpy(dtype=float)
            if not np.isfinite(values).all():
                raise ValueError(f"{name}: contains non-finite values")
            if name != "temp_air_c" and (values < 0).any():
                raise ValueError(f"{name}: contains negative values")
        return self


class PVOutput(PlantOutput):
    dc_kw: pd.Series  # DC into the inverter, after system losses
    poa_w_m2: pd.Series  # sunlight on the panel surface
    temp_cell_c: pd.Series


class PVPlant(Plant[PVParams, PVInputs, PVOutput]):
    params_model = PVParams
    inputs_model = PVInputs
    output_model = PVOutput

    def _simulate(self, ts: PVInputs) -> PVOutput:
        step = ts.index[1] - ts.index[0]
        if step > MAX_STEP:
            raise TimeGridError(f"{self.name}: PV needs a time step of at most 1 h, got {step}")
        try:
            from kioze_sim.plants.pv._engine import run
        except ImportError as e:
            if (e.name or "").split(".")[0] == "pvlib":
                raise ImportError("PV simulation needs pvlib: pip install 'kioze-sim[pv]'") from e
            raise
        res = run(self.params, ts)
        return PVOutput(
            power_kw=res["ac_w"] / 1000,
            dc_kw=(res["dc_w"] / 1000).rename("dc_kw"),
            poa_w_m2=res["poa_w_m2"],
            temp_cell_c=res["temp_cell_c"],
        )
