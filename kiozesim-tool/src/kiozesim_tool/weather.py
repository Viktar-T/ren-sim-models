"""Weather sources: where the tool's weather comes from (spec 0011, SINK-040..044)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd

DAY = pd.Timedelta(days=1)


class WeatherSource(ABC):
    @abstractmethod
    def get(self, start: pd.Timestamp, end: pd.Timestamp, step: pd.Timedelta) -> pd.DataFrame:
        """Weather on `[start, end)` at `step`, UTC, period-start labels."""


class FileWeatherSource(WeatherSource):
    """A CSV holding one dateless day (`time` = `HH:MM` UTC), repeated on every date."""

    def __init__(self, path: str | Path) -> None:
        df = pd.read_csv(path, dtype={"time": str})
        if "time" not in df.columns:
            raise ValueError(f"{path}: needs a 'time' column")
        if not df["time"].str.fullmatch(r"\d{2}:\d{2}").all():
            raise ValueError(f"{path}: 'time' must be a time of day HH:MM without a date")
        offsets = pd.to_timedelta(df["time"] + ":00")
        steps = set(offsets.diff().dropna())
        if len(df) < 2 or len(steps) != 1 or next(iter(steps)) <= pd.Timedelta(0):
            raise ValueError(f"{path}: times must be increasing with one regular step")
        self.step: pd.Timedelta = next(iter(steps))
        if offsets.iloc[0] != pd.Timedelta(0) or offsets.iloc[-1] + self.step != DAY:
            raise ValueError(f"{path}: must cover exactly one day from 00:00")
        if df.drop(columns="time").isna().any().any():
            raise ValueError(f"{path}: contains empty values")
        self._offsets = pd.TimedeltaIndex(offsets)
        self._values = df.drop(columns="time").astype(float).reset_index(drop=True)

    def get(self, start: pd.Timestamp, end: pd.Timestamp, step: pd.Timedelta) -> pd.DataFrame:
        # Lay the day over every date from the day before to the day after, so averaging and
        # interpolation at midnight see the neighbouring (identical) day.
        first, last = start.floor("D") - DAY, end.ceil("D") + DAY
        days = pd.date_range(first, last, freq="D", inclusive="left")
        frames = []
        for d in days:
            day = self._values.copy()
            day.index = d + self._offsets
            frames.append(day)
        tiled = pd.concat(frames)
        if step >= self.step:
            out = tiled.resample(step, origin="epoch", label="left", closed="left").mean()
        else:
            grid = pd.date_range(first, last, freq=step, inclusive="left")
            out = tiled.reindex(tiled.index.union(grid)).interpolate(method="time").reindex(grid)
        out = out[(out.index >= start) & (out.index < end)]
        out.index.name = "time"
        return out
