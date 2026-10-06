"""Simulate a small rooftop solar (PV) system for one sunny June day in Warsaw.

Run:  uv run python kiozesim/examples/pv.py
"""

from pathlib import Path

import pandas as pd

from kiozesim.plants.pv import PVDatasheet, PVInputs, PVParams, PVPlant

HERE = Path(__file__).resolve().parent

# 1. The solar module (one panel): the manufacturer's numbers, from a real datasheet shipped
#    with the library. PVDatasheet.available() lists the others.
module = PVDatasheet.bundled("jinko_solar_jkm440n_54hl4r_b")

# 2. The installation: where it is, how the panels face, how many, and the inverter
#    (the box that turns the panels' DC into AC for the house and grid).
params = PVParams(
    name="warsaw_rooftop",
    datasheet=module,
    latitude_deg=52.23,
    longitude_deg=21.01,
    altitude_m=119,
    tilt_deg=35,  # panel angle from flat ground
    azimuth_deg=180,  # facing south
    n_modules=10,  # 10 x 440 W = 4.4 kW of panels
    inverter_ac_kw=4.0,
)
plant = PVPlant(params)

# 3. The weather: one row per hour, times in UTC.
#    ghi = sunlight on flat ground (W/m2), plus air temperature and wind (wind cools panels).
weather = pd.read_csv(HERE / "pv_weather.csv", index_col="time", parse_dates=True)
inputs = PVInputs(
    ghi_w_m2=weather["ghi_w_m2"],
    temp_air_c=weather["temp_air_c"],
    wind_speed_m_s=weather["wind_speed_m_s"],
)

# 4. Run the simulation. power_kw is the average AC power in each hour.
result = plant.simulate(inputs)

# 5. Show the result. Each step is 1 hour, so kW x 1 h = kWh.
for time, kw in result.power_kw.items():
    print(f"{time:%Y-%m-%d %H:%M} UTC  {kw:5.2f} kW")
total_kwh = result.power_kw.sum() * 1.0
print(f"Total for the day: {total_kwh:.1f} kWh")
