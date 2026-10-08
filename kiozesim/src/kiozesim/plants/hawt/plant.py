"""Horizontal-axis wind turbine: power curve via windpowerlib (extra 'wind'). Spec 0003.

I/O contract
  input : HAWTInputs (TimeSeries, one shared index, period averages labelled at period start):
          wind_speed_m_s, optionally temp_air_c + pressure_hpa (needed for density correction)
  output: HAWTOutput, power_kw (all turbines, after losses) plus wind_speed_hub_m_s and
          air_density_kg_m3 on the input index.
Datasheet: YAML in kiozesim/datasheets/hawt/ or a turbine from windpowerlib's library (its
catalogue), both loaded via HAWTDatasheet.bundled(name).
"""

from __future__ import annotations

from typing import Self

import numpy as np
import pandas as pd
from pydantic import ConfigDict, Field, model_validator

from kiozesim.datasheet import Datasheet
from kiozesim.plants.base import Plant, PlantOutput, PlantParams, TimeSeries
from kiozesim.plants.hawt._library import WIND_HINT, TurbineLibrary
from kiozesim.timegrid import TimeGridError

MAX_STEP = pd.Timedelta(hours=1)
CURVE_MARGIN = 1.05  # published curves peak up to 2.5 % above nameplate


class HAWTDatasheet(Datasheet):
    shelf = "hawt"
    catalogue = TurbineLibrary()  # windpowerlib's turbine library, by type code (e.g. "E-82/2300")

    model_config = ConfigDict(allow_inf_nan=False)

    rated_power_kw: float = Field(gt=0)
    rotor_diameter_m: float = Field(gt=0)
    wind_speed_m_s: list[float]  # power curve x, at hub height
    power_kw: list[float]  # power curve y

    @model_validator(mode="after")
    def _check_curve(self) -> Self:
        v, p = np.asarray(self.wind_speed_m_s), np.asarray(self.power_kw)
        if len(v) != len(p):
            raise ValueError("wind_speed_m_s and power_kw must have the same length")
        if len(v) < 2:
            raise ValueError("the power curve needs at least 2 points")
        if (v < 0).any() or (np.diff(v) <= 0).any():
            raise ValueError("wind_speed_m_s must be >= 0 and strictly increasing")
        if (p < 0).any() or (p > CURVE_MARGIN * self.rated_power_kw).any():
            raise ValueError(f"power_kw must lie within 0 ... {CURVE_MARGIN} x rated_power_kw")
        return self


class HAWTParams(PlantParams):
    model_config = ConfigDict(allow_inf_nan=False)

    datasheet: HAWTDatasheet
    hub_height_m: float = Field(gt=0)
    n_turbines: int = Field(default=1, ge=1)
    wind_height_m: float = Field(default=10.0, gt=0)  # where the input wind was measured
    roughness_length_m: float = Field(default=0.1, gt=0)
    temp_height_m: float = Field(default=2.0, gt=0)  # where the input temperature was measured
    density_correction: bool = True
    losses_pct: float = Field(default=10.0, ge=0, lt=100)

    @model_validator(mode="after")
    def _check_heights(self) -> Self:
        if self.roughness_length_m >= self.wind_height_m:
            raise ValueError("wind_height_m must be above roughness_length_m")
        if self.roughness_length_m >= self.hub_height_m:
            raise ValueError("hub_height_m must be above roughness_length_m")
        return self


class HAWTInputs(TimeSeries):
    wind_speed_m_s: pd.Series  # at wind_height_m
    temp_air_c: pd.Series | None = None  # at temp_height_m; needed for density correction
    pressure_hpa: pd.Series | None = None  # surface pressure at ground level; same

    @model_validator(mode="after")
    def _check_values(self) -> Self:
        for name, s in self:
            if not isinstance(s, pd.Series):
                continue
            values = s.to_numpy(dtype=float)
            if not np.isfinite(values).all():
                raise ValueError(f"{name}: contains non-finite values")
            if name == "wind_speed_m_s" and (values < 0).any():
                raise ValueError(f"{name}: contains negative values")
            if name == "pressure_hpa" and (values <= 0).any():
                raise ValueError(f"{name}: must be positive")
        return self


class HAWTOutput(PlantOutput):
    wind_speed_hub_m_s: pd.Series  # before density correction
    air_density_kg_m3: pd.Series | None = None  # at hub height; None without density correction


class HAWTPlant(Plant[HAWTParams, HAWTInputs, HAWTOutput]):
    params_model = HAWTParams
    inputs_model = HAWTInputs
    output_model = HAWTOutput

    def _simulate(self, ts: HAWTInputs) -> HAWTOutput:
        p = self.params
        step = ts.index[1] - ts.index[0]
        if step > MAX_STEP:
            raise TimeGridError(f"{self.name}: HAWT needs a time step of at most 1 h, got {step}")
        if p.density_correction:
            for field in ("temp_air_c", "pressure_hpa"):
                if getattr(ts, field) is None:
                    raise ValueError(
                        f"{self.name}: density correction needs {field}"
                        " (or set density_correction: false)"
                    )
        try:
            from kiozesim.plants.hawt._engine import run
        except ImportError as e:
            if (e.name or "").split(".")[0] == "windpowerlib":
                raise ImportError(f"HAWT simulation needs windpowerlib: {WIND_HINT}") from e
            raise
        res = run(p, ts)
        power_kw = p.n_turbines * res["power_w"] / 1000 * (1 - p.losses_pct / 100)
        return HAWTOutput(
            power_kw=power_kw,
            wind_speed_hub_m_s=res["wind_speed_hub_m_s"],
            air_density_kg_m3=res["air_density_kg_m3"] if p.density_correction else None,
        )
