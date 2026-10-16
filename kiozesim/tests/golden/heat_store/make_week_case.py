"""Build the heat store golden case `week_daily_demand`. Spec 0006 Acceptance.

Run by hand:  uv run python kiozesim/tests/golden/heat_store/make_week_case.py

One week, hourly: 210 kW of heat coming in all the time, a demand of 100 kW at night, 300 kW in
the morning (6-9 h) and 400 kW in the evening (from 17 h). A 50 m³ tank, 2 m high, U 0.4 W/(m²K),
80/40 °C, room 15 °C, starting half full.

Must not import kiozesim: the expected tank content is worked out here from the published
stratified-tank equations (oemof.thermal docs) and the step order of spec 0006, by hand.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import yaml

HERE = Path(__file__).parent / "week_daily_demand"
V, H, U, T_HOT, T_COLD, T_ROOM, FILL = 50.0, 2.0, 0.4, 80.0, 40.0, 15.0, 0.5
RHO, C = 971.803, 4195.52  # water at about 80 °C, kg/m³ and J/(kg K)


def main() -> None:
    index = pd.date_range("2026-01-12", periods=24 * 7, freq="h", tz="UTC")
    hours = index.hour
    demand = [300.0 if 6 <= h < 9 else 400.0 if h >= 17 else 100.0 for h in hours]
    heat_in = [210.0] * len(index)

    d = math.sqrt(4 * V / (math.pi * H))
    capacity = V * RHO * C * (T_HOT - T_COLD) / 3.6e6  # kWh
    beta = 4 * U * 3600 / (d * RHO * C)  # per hour
    gamma = 4 * U * (T_COLD - T_ROOM) * 3600 / (d * RHO * C * (T_HOT - T_COLD))
    delta = U * math.pi * d**2 / 4 * (T_HOT + T_COLD - 2 * T_ROOM) / 1000  # kWh per hour

    stored = FILL * capacity
    expected = []
    for q_in, q_dem in zip(heat_in, demand, strict=True):
        stored -= min(stored, beta * stored + gamma * capacity + delta)  # tank cools
        stored += q_in  # heat comes in (1 h steps: kW = kWh)
        stored -= min(q_dem, stored)  # demand drawn
        stored = min(stored, capacity)  # the rest is dumped
        expected.append(stored)

    HERE.mkdir(exist_ok=True)
    frame = pd.DataFrame({"heat_kw": heat_in, "heat_demand_kw": demand}, index=index)
    frame.index.name = "time"
    frame.to_csv(HERE / "inputs.csv")
    out = pd.DataFrame({"stored_kwh": expected}, index=index)
    out.index.name = "time"
    out.to_csv(HERE / "expected.csv")
    case = {
        "params": {
            "name": "tank_50m3",
            "volume_m3": V,
            "height_m": H,
            "u_value_w_m2k": U,
            "temp_hot_c": T_HOT,
            "temp_cold_c": T_COLD,
            "temp_room_c": T_ROOM,
            "initial_fill": FILL,
        },
        "column": "stored_kwh",
        "rtol": 1e-6,
        "atol": 1e-6,
        "source": "Spec 0006 Acceptance, worked out by make_week_case.py from the published "
        "stratified-tank equations (oemof.thermal docs) and 0006's step order, without kiozesim.",
    }
    (HERE / "case.yaml").write_text(yaml.safe_dump(case, sort_keys=False))


if __name__ == "__main__":
    main()
