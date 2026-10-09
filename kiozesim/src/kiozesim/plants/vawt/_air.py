"""Wind and air at hub height for the VAWT plant. Spec 0004, VAWT-014.

The same formulas windpowerlib uses for HAWT (logarithmic profile without obstacles, linear
temperature gradient, barometric density), written out so VAWT does not need windpowerlib.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RHO_STD = 1.225  # kg/m³, the density power curves are published for


def wind_at_hub(
    wind_m_s: pd.Series, wind_height_m: float, hub_height_m: float, roughness_length_m: float
) -> pd.Series:
    """Logarithmic wind profile: v_hub = v × ln(h_hub / z0) / ln(h_meas / z0)."""
    if wind_height_m == hub_height_m:
        return wind_m_s.astype(float)
    z0 = roughness_length_m
    return wind_m_s * float(np.log(hub_height_m / z0) / np.log(wind_height_m / z0))


def density_at_hub(
    temp_air_c: pd.Series, temp_height_m: float, pressure_hpa: pd.Series, hub_height_m: float
) -> pd.Series:
    """Air density in kg/m³ at hub height, from temperature and surface pressure.

    Temperature falls 6.5 K per km; pressure falls 1/8 hPa per metre above the ground (height 0).
    """
    temp_hub_k = temp_air_c + 273.15 - 0.0065 * (hub_height_m - temp_height_m)
    p_hub_hpa = pressure_hpa - hub_height_m / 8
    return p_hub_hpa * RHO_STD * 288.15 * 100 / (101330 * temp_hub_k)
