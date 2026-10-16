"""Heat store: a hot-water tank between a heat maker and the buildings that use the heat. Spec 0006.

I/O contract
  input : HeatStoreInputs (TimeSeries): heat_kw, heat coming in from the plant in front (a
          combustion plant, spec 0019), and heat_demand_kw, heat wanted, from a source
  output: HeatStoreOutput: delivered_kw, unmet_kw, dumped_kw, loss_kw, stored_kwh and power_kw 0
          on the input index; none of them flows on.
Has memory (the heat it holds, kWh) and follows requests: each step it asks the plant in front for
this step's demand plus the room left in the tank. Tank capacity and wall losses come from
oemof.thermal (stratified tank), through `_engine` (imported only for a tank larger than 0 m³).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple, Self

import pandas as pd
from pydantic import ConfigDict, Field, model_validator

from kiozesim.plants.base import Plant, PlantOutput, PlantParams, Sizing, State, TimeSeries


class Tank(NamedTuple):
    """The tank's numbers for one step length (BOIL-003, BOIL-004)."""

    capacity_kwh: float
    loss_rate: float  # share of the content lost per step
    fixed_relative: float  # share of the capacity lost per step
    fixed_absolute_kwh: float  # lost per step through lid and floor

    def loss_kwh(self, stored_kwh: float) -> float:
        """Heat lost in one step; never more than the tank holds."""
        loss = (
            self.loss_rate * stored_kwh
            + self.fixed_relative * self.capacity_kwh
            + self.fixed_absolute_kwh
        )
        return min(stored_kwh, loss)


class HeatStoreParams(PlantParams):
    model_config = ConfigDict(allow_inf_nan=False)

    volume_m3: float = Field(ge=0)  # 0 = no tank: heat passes straight through
    height_m: float = Field(default=2.0, gt=0)  # sets the diameter
    u_value_w_m2k: float = Field(default=0.4, gt=0)  # heat lost through the wall
    temp_hot_c: float = 80.0  # water when charged
    temp_cold_c: float = 40.0  # water when discharged
    temp_room_c: float = 15.0  # air around the tank
    initial_fill: float = Field(default=0.5, ge=0, le=1)  # share charged at the start

    @model_validator(mode="after")
    def _temperatures(self) -> Self:
        if not self.temp_hot_c > self.temp_cold_c > self.temp_room_c:
            raise ValueError("temperatures must be temp_hot_c > temp_cold_c > temp_room_c")
        return self


class HeatStoreInputs(TimeSeries):
    heat_kw: pd.Series  # heat coming in, kW, period average
    heat_demand_kw: pd.Series  # heat wanted, kW, period average

    @model_validator(mode="after")
    def _non_negative(self) -> Self:
        for name in ("heat_kw", "heat_demand_kw"):
            if (getattr(self, name) < 0).any():
                raise ValueError(f"{name}: must be >= 0")
        return self


class HeatStoreOutput(PlantOutput):
    delivered_kw: pd.Series  # heat delivered to the demand
    unmet_kw: pd.Series  # demand not covered
    dumped_kw: pd.Series  # heat in that neither the demand nor the tank could take
    loss_kw: pd.Series  # lost through the walls
    stored_kwh: pd.Series  # in the tank at the end of the period


class HeatStorePlant(Plant[HeatStoreParams, HeatStoreInputs, HeatStoreOutput]):
    params_model = HeatStoreParams
    inputs_model = HeatStoreInputs
    output_model = HeatStoreOutput
    follows_requests = True
    askable = ("delivered_kw",)

    def tank(self, dt_h: float = 1.0) -> Tank:
        p = self.params
        if p.volume_m3 == 0:
            return Tank(0.0, 0.0, 0.0, 0.0)
        from kiozesim.plants.heat_store import _engine  # lazy: oemof.thermal is an extra

        return Tank(
            *_engine.tank(
                p.volume_m3,
                p.height_m,
                p.u_value_w_m2k,
                p.temp_hot_c,
                p.temp_cold_c,
                p.temp_room_c,
                dt_h,
            )
        )

    def initial_state(self) -> State:
        return self.params.initial_fill * self.tank().capacity_kwh

    def want(
        self,
        state: State,
        t: pd.Timestamp,
        inputs: Mapping[str, float],
        wanted: Mapping[str, float],
        dt_h: float,
    ) -> dict[str, float]:
        tank = self.tank(dt_h)
        stored = float(state) - tank.loss_kwh(float(state))
        room = tank.capacity_kwh - stored
        return {"heat_kw": float(inputs["heat_demand_kw"]) + room / dt_h}

    def step(
        self,
        state: State,
        t: pd.Timestamp,
        inputs: Mapping[str, float],
        wanted: Mapping[str, float],
        dt_h: float,
    ) -> tuple[State, dict[str, float]]:
        tank = self.tank(dt_h)
        stored = float(state)
        loss = tank.loss_kwh(stored)
        stored -= loss
        stored += float(inputs["heat_kw"]) * dt_h
        demand = float(inputs["heat_demand_kw"]) * dt_h
        delivered = min(demand, stored)
        stored -= delivered
        dumped = max(0.0, stored - tank.capacity_kwh)
        stored = min(stored, tank.capacity_kwh)
        return stored, {
            "power_kw": 0.0,
            "delivered_kw": delivered / dt_h,
            "unmet_kw": (demand - delivered) / dt_h,
            "dumped_kw": dumped / dt_h,
            "loss_kw": loss / dt_h,
            "stored_kwh": stored,
        }

    def _simulate(self, ts: HeatStoreInputs) -> HeatStoreOutput:
        index = ts.index
        dt_h = (index[1] - index[0]) / pd.Timedelta(hours=1)
        frame = ts.to_frame()
        state = self.initial_state()
        rows = []
        for t, heat_kw, demand_kw in zip(
            index, frame["heat_kw"], frame["heat_demand_kw"], strict=True
        ):
            inputs = {"heat_kw": float(heat_kw), "heat_demand_kw": float(demand_kw)}
            state, out = self.step(state, t, inputs, {}, dt_h)
            rows.append(out)
        table = pd.DataFrame(rows, index=index, dtype=float)
        return HeatStoreOutput(**{c: table[c].rename(c) for c in table.columns})

    def needs(self, wanted: Mapping[str, float]) -> Sizing:
        """Heat in for an average delivery: the delivery plus the tank's hourly losses at its
        starting fill (CHAIN-023)."""
        self.check_asked(wanted)
        tank = self.tank(1.0)
        loss_kw = tank.loss_kwh(self.params.initial_fill * tank.capacity_kwh)
        want = max(0.0, wanted.get("delivered_kw", 0.0))
        return Sizing({"heat_kw": want + loss_kw}, {"delivered_kw": want})
