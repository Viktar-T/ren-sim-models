"""Aggregates plants into a total generation series."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from kiozesim.plants.base import Plant, TimeSeries


class Portfolio:
    def __init__(self, plants: list[Plant]) -> None:  # type: ignore[type-arg]
        names = [p.name for p in plants]
        if len(set(names)) != len(names):
            raise ValueError("plant names in a portfolio must be unique")
        self.plants = plants

    def simulate(self, inputs: Mapping[str, TimeSeries]) -> pd.DataFrame:
        """`inputs` maps plant name -> its TimeSeries (omit plants that take none).

        Steady-state plants are broadcast onto the common time axis. Returns kW per plant
        plus `total`.
        """
        outs = {p.name: p.simulate(inputs.get(p.name)).power_kw for p in self.plants}
        series = {n: v for n, v in outs.items() if isinstance(v, pd.Series)}
        if not series:
            raise ValueError("a portfolio needs at least one plant with a time series")
        index = next(iter(series.values())).index
        if any(not s.index.equals(index) for s in series.values()):
            raise ValueError("all plants in a portfolio must share one time axis")
        out = pd.DataFrame(
            {n: (v if n in series else float(v)) for n, v in outs.items()}, index=index
        )
        out["total"] = out.sum(axis=1)
        return out
