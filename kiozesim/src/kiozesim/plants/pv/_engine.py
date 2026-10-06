"""pvlib adapter for the PV plant: the only module that imports pvlib (optional extra 'pv').

Imported lazily by `PVPlant._simulate`; pvlib objects never leave this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
from pvlib.irradiance import erbs
from pvlib.location import Location
from pvlib.modelchain import ModelChain
from pvlib.pvsystem import PVSystem
from pvlib.temperature import TEMPERATURE_MODEL_PARAMETERS

if TYPE_CHECKING:
    from kiozesim.plants.pv.plant import PVInputs, PVParams

# Every component of pvlib.pvsystem.pvwatts_losses. All are passed explicitly because pvlib's
# defaults are non-zero (they add up to ~14 % on their own).
_LOSS_COMPONENTS = (
    "soiling",
    "shading",
    "snow",
    "mismatch",
    "wiring",
    "connections",
    "lid",
    "nameplate_rating",
    "age",
    "availability",
)


def build_modelchain(p: PVParams) -> ModelChain:
    """PVWatts ModelChain with every model named, so pvlib default changes cannot leak in."""
    location = Location(p.latitude_deg, p.longitude_deg, tz="UTC", altitude=p.altitude_m)
    system = PVSystem(
        surface_tilt=p.tilt_deg,
        surface_azimuth=p.azimuth_deg,
        albedo=p.albedo,
        module_parameters={
            "pdc0": p.n_modules * p.datasheet.pdc0_w,
            "gamma_pdc": p.datasheet.gamma_pdc_per_k,
        },
        inverter_parameters={
            # pvlib caps AC at eta_inv_nom * pdc0 = inverter_ac_kw
            "pdc0": p.inverter_ac_kw * 1000 / p.inverter_efficiency,
            "eta_inv_nom": p.inverter_efficiency,
        },
        temperature_model_parameters=TEMPERATURE_MODEL_PARAMETERS["sapm"][p.mounting],
        losses_parameters={c: 0.0 for c in _LOSS_COMPONENTS} | {"soiling": p.losses_pct},
    )
    return ModelChain(
        system,
        location,
        solar_position_method="nrel_numpy",
        airmass_model="kastenyoung1989",
        transposition_model="perez",
        aoi_model="physical",
        spectral_model="no_loss",
        temperature_model="sapm",
        dc_model="pvwatts",
        dc_ohmic_model="no_loss",
        losses_model="pvwatts",
        ac_model="pvwatts",
    )


def run(p: PVParams, ts: PVInputs) -> pd.DataFrame:
    """Columns ac_w, dc_w (after losses), poa_w_m2, temp_cell_c on the input index."""
    mc = build_modelchain(p)
    weather = prepare_weather(ts, mc.location)
    mc.run_model(weather)
    r = mc.results
    raw = pd.DataFrame(
        {
            "ac_w": r.ac,
            "dc_w": r.dc,
            "poa_w_m2": r.total_irrad["poa_global"],
            "temp_cell_c": r.cell_temperature,
            "sun_elevation_deg": r.solar_position["apparent_elevation"],
        },
        index=weather.index,
    )
    return collect(raw, weather, ts.index)


def prepare_weather(ts: PVInputs, location: Location) -> pd.DataFrame:
    """pvlib weather frame on each period's middle; DNI/DHI estimated with Erbs if absent."""
    index = ts.index
    mid = index + (index[1] - index[0]) / 2
    weather = pd.DataFrame(
        {
            "ghi": ts.ghi_w_m2.to_numpy(dtype=float),
            "temp_air": ts.temp_air_c.to_numpy(dtype=float),
            "wind_speed": ts.wind_speed_m_s.to_numpy(dtype=float),
        },
        index=mid,
    )
    if ts.dni_w_m2 is not None and ts.dhi_w_m2 is not None:
        weather["dni"] = ts.dni_w_m2.to_numpy(dtype=float)
        weather["dhi"] = ts.dhi_w_m2.to_numpy(dtype=float)
    else:
        sun = location.get_solarposition(mid, temperature=weather["temp_air"])
        parts = erbs(weather["ghi"], sun["zenith"], mid)
        weather["dni"], weather["dhi"] = parts["dni"], parts["dhi"]
    return weather


def collect(raw: pd.DataFrame, weather: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Clean pvlib's raw results (on period middles) and put them back on the input labels."""
    out = raw[["ac_w", "dc_w", "poa_w_m2", "temp_cell_c"]].copy()
    # pvlib leaves NaN where there is no light to work with (sun below the horizon, or Perez's
    # 0/0 when DHI = 0 just after sunrise). No light means no power and cell temperature = air.
    no_light = weather["ghi"] == 0
    dark = no_light | (raw["sun_elevation_deg"] <= 0)
    power = ["ac_w", "dc_w", "poa_w_m2"]
    out.loc[no_light, power] = 0.0
    out.loc[dark, power] = out.loc[dark, power].fillna(0.0)
    out.loc[dark, "temp_cell_c"] = out.loc[dark, "temp_cell_c"].fillna(weather["temp_air"])
    if out.isna().any().any():
        bad = out.index[out.isna().any(axis=1)][0]
        raise RuntimeError(
            f"pvlib returned NaN in daylight (period middle {bad}); check that DHI > 0 when GHI > 0"
        )
    return out.set_axis(index)
