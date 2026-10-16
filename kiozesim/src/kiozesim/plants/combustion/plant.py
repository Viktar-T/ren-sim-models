"""Combustion plant: fuel in; electricity, heat and the fuel it did not burn out. Specs 0015, 0019.

One model for gas engines (CHP: electricity and heat) and boilers (heat only, electrical efficiency
0); they differ only in their datasheets.

I/O contract
  input : CombustionInputs (TimeSeries): fuel_kw, fuel energy flow (lower heating value), e.g. a
          digester's `fuel_kw` (spec 0005) or what an engine in front left (spec 0019)
  output: CombustionOutput: power_kw, heat_kw and fuel_kw (the fuel left, passed on) on the input
          index.
Follows requests (heat-led): asked for heat or power, it burns no more than they need.
Datasheet: YAML in kiozesim/datasheets/combustion/, loaded via CombustionDatasheet.bundled(name).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Self

import pandas as pd
from pydantic import ConfigDict, Field, model_validator

from kiozesim.datasheet import Datasheet
from kiozesim.plants.base import Plant, PlantOutput, PlantParams, Sizing, State, TimeSeries

MAKES = ("power_kw", "heat_kw")  # what it makes, each by its own efficiency


class CombustionDatasheet(Datasheet):
    shelf = "combustion"

    model_config = ConfigDict(allow_inf_nan=False)

    # exactly one: engines are rated by electricity, boilers by heat, as their documents give it
    rated_electrical_kw: float | None = Field(default=None, gt=0)
    rated_thermal_kw: float | None = Field(default=None, gt=0)
    electrical_efficiency: float = Field(ge=0, lt=1)  # fuel -> electricity, full load
    thermal_efficiency: float = Field(ge=0, lt=1)  # fuel -> useful heat, full load

    @model_validator(mode="after")
    def _check(self) -> Self:
        if (self.rated_electrical_kw is None) == (self.rated_thermal_kw is None):
            raise ValueError("give exactly one of rated_electrical_kw and rated_thermal_kw")
        if self.electrical_efficiency + self.thermal_efficiency > 1:
            raise ValueError("electrical_efficiency + thermal_efficiency must not exceed 1")
        if self.rated_electrical_kw is not None and self.electrical_efficiency == 0:
            raise ValueError("rated by electricity needs electrical_efficiency > 0")
        if self.rated_thermal_kw is not None and self.thermal_efficiency == 0:
            raise ValueError("rated by heat needs thermal_efficiency > 0")
        return self

    @property
    def fuel_max_kw(self) -> float:
        """The most fuel it can burn: its size over the matching efficiency."""
        if self.rated_electrical_kw is not None:
            return self.rated_electrical_kw / self.electrical_efficiency
        assert self.rated_thermal_kw is not None
        return self.rated_thermal_kw / self.thermal_efficiency

    def efficiency(self, output: str) -> float:
        return self.electrical_efficiency if output == "power_kw" else self.thermal_efficiency


class CombustionParams(PlantParams):
    model_config = ConfigDict(allow_inf_nan=False)

    datasheet: CombustionDatasheet
    availability: float = Field(default=1.0, ge=0, le=1)  # share of time it is not down


class CombustionInputs(TimeSeries):
    fuel_kw: pd.Series  # fuel energy flow, kW (lower heating value), period average

    @model_validator(mode="after")
    def _non_negative(self) -> Self:
        if (self.fuel_kw < 0).any():
            raise ValueError("fuel_kw: must be >= 0")
        return self


class CombustionOutput(PlantOutput):
    heat_kw: pd.Series
    fuel_kw: pd.Series  # fuel not burned, passed on to the next plant (spec 0019 naming scheme)


class CombustionPlant(Plant[CombustionParams, CombustionInputs, CombustionOutput]):
    params_model = CombustionParams
    inputs_model = CombustionInputs
    output_model = CombustionOutput
    follows_requests = True
    askable = ("heat_kw", "power_kw", "fuel_kw")

    def _simulate(self, ts: CombustionInputs) -> CombustionOutput:
        ds = self.params.datasheet
        fuel = ts.fuel_kw.astype(float)
        burned = self.params.availability * fuel.clip(upper=ds.fuel_max_kw)
        return CombustionOutput(
            power_kw=(burned * ds.electrical_efficiency).rename("power_kw"),
            heat_kw=(burned * ds.thermal_efficiency).rename("heat_kw"),
            fuel_kw=(fuel - burned).clip(lower=0).rename("fuel_kw"),
        )

    def _burn_for(self, wanted: Mapping[str, float]) -> float:
        """Fuel the wanted heat and power need (the tightest); inf when neither is wanted."""
        ds = self.params.datasheet
        limits = [
            max(0.0, wanted[name]) / ds.efficiency(name)
            for name in MAKES
            if name in wanted and ds.efficiency(name) > 0
        ]
        return min(limits) if limits else math.inf

    def _fuel_for(self, burn: float, spare: float) -> float:
        """Fuel to send so it can burn `burn` on average and still leave `spare`."""
        a = self.params.availability
        return max(burn / a if a > 0 else 0.0, burn + spare)

    def want(
        self,
        state: State,
        t: pd.Timestamp,
        inputs: Mapping[str, float],
        wanted: Mapping[str, float],
        dt_h: float,
    ) -> dict[str, float]:
        burn = self._burn_for(wanted)
        if math.isinf(burn):
            return {}  # asked for nothing it makes: no limit
        burn = min(burn, self.params.availability * self.params.datasheet.fuel_max_kw)
        return {"fuel_kw": self._fuel_for(burn, max(0.0, wanted.get("fuel_kw", 0.0)))}

    def step(
        self,
        state: State,
        t: pd.Timestamp,
        inputs: Mapping[str, float],
        wanted: Mapping[str, float],
        dt_h: float,
    ) -> tuple[State, dict[str, float]]:
        ds = self.params.datasheet
        fuel = float(inputs["fuel_kw"])
        can = self.params.availability * min(fuel, ds.fuel_max_kw)
        burned = min(can, self._burn_for(wanted))
        return state, {
            "power_kw": burned * ds.electrical_efficiency,
            "heat_kw": burned * ds.thermal_efficiency,
            "fuel_kw": max(0.0, fuel - burned),
        }

    def needs(self, wanted: Mapping[str, float]) -> Sizing:
        """Average fuel for average heat or power (or spare fuel), within the plant's size."""
        self.check_asked(wanted)
        ds, a = self.params.datasheet, self.params.availability
        spare = max(0.0, wanted.get("fuel_kw", 0.0))
        given = {"fuel_kw": spare} if "fuel_kw" in wanted else {}
        made = [n for n in MAKES if n in wanted]
        if made:
            need = max(
                (wanted[n] / ds.efficiency(n) if ds.efficiency(n) > 0 else 0.0) for n in made
            )
            burn = min(need, a * ds.fuel_max_kw)
            given |= {n: min(wanted[n], burn * ds.efficiency(n)) for n in made}
            return Sizing({"fuel_kw": self._fuel_for(burn, spare)}, given)
        # asked only for spare fuel: it burns flat out and passes on the rest
        if spare == 0:
            return Sizing({"fuel_kw": 0.0}, given)
        if a < 1 and spare / (1 - a) <= ds.fuel_max_kw:
            return Sizing({"fuel_kw": spare / (1 - a)}, given)
        return Sizing({"fuel_kw": spare + a * ds.fuel_max_kw}, given)
