"""windpowerlib adapter for the HAWT plant: the only module that imports windpowerlib's models.

Imported lazily by `HAWTPlant._simulate`; windpowerlib objects never leave this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
from windpowerlib import data
from windpowerlib.modelchain import ModelChain
from windpowerlib.wind_turbine import WindTurbine

if TYPE_CHECKING:
    from kiozesim.plants.hawt.plant import HAWTInputs, HAWTParams


def build(p: HAWTParams) -> ModelChain:
    """ModelChain with every model named, so windpowerlib default changes cannot leak in."""
    ds = p.datasheet
    turbine = WindTurbine(
        hub_height=p.hub_height_m,
        nominal_power=ds.rated_power_kw * 1000,
        rotor_diameter=ds.rotor_diameter_m,
        power_curve=pd.DataFrame(
            {"wind_speed": ds.wind_speed_m_s, "value": [w * 1000 for w in ds.power_kw]}
        ),
        path=None,  # no library lookup inside windpowerlib
    )
    return ModelChain(
        turbine,
        wind_speed_model="logarithmic",
        temperature_model="linear_gradient",
        density_model="barometric",
        power_output_model="power_curve",
        density_correction=p.density_correction,
        obstacle_height=0,
        hellman_exp=None,
    )


def prepare_weather(p: HAWTParams, ts: HAWTInputs) -> pd.DataFrame:
    """windpowerlib's weather frame: columns (variable, height in m), SI units."""
    cols: dict[tuple[str, float], pd.Series] = {
        ("wind_speed", p.wind_height_m): ts.wind_speed_m_s,
        ("roughness_length", 0.0): pd.Series(p.roughness_length_m, index=ts.index),
    }
    if p.density_correction:
        assert ts.temp_air_c is not None and ts.pressure_hpa is not None  # checked by the plant
        cols[("temperature", p.temp_height_m)] = ts.temp_air_c + 273.15
        cols[("pressure", 0.0)] = ts.pressure_hpa * 100
    weather = pd.DataFrame(cols, index=ts.index)
    weather.columns = pd.MultiIndex.from_tuples(cols.keys())
    return weather


def run(p: HAWTParams, ts: HAWTInputs) -> pd.DataFrame:
    """Columns power_w, wind_speed_hub_m_s, air_density_kg_m3 (NaN without correction).

    The same public steps as `ModelChain.run_model`, which discards hub wind and density.
    """
    mc = build(p)
    weather = data.check_weather_data(prepare_weather(p, ts))
    v_hub = mc.wind_speed_hub(weather)
    rho_hub = mc.density_hub(weather) if p.density_correction else None
    power = mc.calculate_power_output(v_hub, rho_hub)
    return pd.DataFrame(
        {
            "power_w": pd.Series(power, index=ts.index, dtype=float),
            "wind_speed_hub_m_s": pd.Series(v_hub, index=ts.index, dtype=float),
            "air_density_kg_m3": (
                pd.Series(rho_hub, index=ts.index, dtype=float)
                if rho_hub is not None
                else pd.Series(float("nan"), index=ts.index)
            ),
        },
        index=ts.index,
    )
