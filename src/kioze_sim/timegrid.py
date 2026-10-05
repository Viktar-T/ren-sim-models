"""The one thing every plant shares: a UTC, regular, period-start time axis."""

from __future__ import annotations

import pandas as pd


class TimeGridError(ValueError):
    """Time index violates the time-grid rules."""


def validate_time_index(idx: pd.Index) -> pd.DatetimeIndex:
    """tz-aware UTC DatetimeIndex, >= 2 points, strictly increasing, regularly spaced."""
    if not isinstance(idx, pd.DatetimeIndex):
        raise TimeGridError("index must be a DatetimeIndex")
    if idx.tz is None or str(idx.tz) != "UTC":
        raise TimeGridError("index must be timezone-aware UTC")
    if len(idx) < 2:
        raise TimeGridError("index needs at least two timestamps")
    if not idx.is_monotonic_increasing or not idx.is_unique:
        raise TimeGridError("index must be strictly increasing")
    if len(set(idx.to_series().diff().dropna())) != 1:
        raise TimeGridError("index must be regularly spaced")
    return idx
