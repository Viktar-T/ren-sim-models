"""Bundled Savonius Cp(TSR) curve (zEPHYR wind tunnel data). Spec 0004, VAWT-007."""

from __future__ import annotations

from functools import cache
from importlib.resources import files

import pandas as pd


@cache
def _load(n_buckets: int) -> pd.DataFrame:
    path = files("kiozesim") / "datasheets" / "vawt" / "_data" / f"savonius_{n_buckets}.csv"
    with path.open() as f:
        return pd.read_csv(f, comment="#")


def curve(n_buckets: int) -> pd.DataFrame:
    """Measured points, columns tsr and cp, ordered by tsr. A copy: callers may modify it."""
    return _load(n_buckets).copy()
