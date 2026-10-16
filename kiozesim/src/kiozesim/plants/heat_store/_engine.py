"""oemof.thermal adapter for the heat store: the only module that imports oemof.thermal.

Imported lazily by `HeatStorePlant`; oemof values (MWh) are turned into kWh here and never leave
this module as oemof objects (constitution 6, BOIL-011).
"""

from __future__ import annotations

import math
from functools import lru_cache

from oemof.thermal.stratified_thermal_storage import calculate_capacities, calculate_losses


@lru_cache(maxsize=64)
def tank(
    volume_m3: float,
    height_m: float,
    u_value_w_m2k: float,
    temp_hot_c: float,
    temp_cold_c: float,
    temp_room_c: float,
    dt_h: float,
) -> tuple[float, float, float, float]:
    """(capacity_kwh, loss_rate, fixed_losses_relative, fixed_losses_absolute_kwh) for one step.

    The tank is an upright cylinder of `volume_m3` and `height_m`; its diameter follows.
    """
    diameter_m = math.sqrt(4 * volume_m3 / (math.pi * height_m))
    capacity_mwh = calculate_capacities(volume_m3, temp_hot_c, temp_cold_c)
    loss_rate, fixed_relative, fixed_absolute_mwh = calculate_losses(
        u_value_w_m2k, diameter_m, temp_hot_c, temp_cold_c, temp_room_c, time_increment=dt_h
    )
    return (
        float(capacity_mwh) * 1000,
        float(loss_rate),
        float(fixed_relative),
        float(fixed_absolute_mwh) * 1000,
    )
