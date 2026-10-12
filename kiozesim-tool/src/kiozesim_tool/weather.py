"""Weather from a one-day file, as a source (SRC-011; rules from the former SINK-041..044)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from kiozesim import Source

DAY = pd.Timedelta(days=1)


class FileWeatherParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    path: Path  # a CSV of one dateless day; apps resolve relative paths before building


class FileWeatherSource(Source[FileWeatherParams]):
    """A CSV holding one dateless day (`time` = `HH:MM` UTC), repeated on every date.

    No input columns; its output columns are the file's columns (SRC-011).
    """

    params_model = FileWeatherParams

    def __init__(self, params: FileWeatherParams) -> None:
        super().__init__(params)
        path = params.path
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

    def _simulate(self, index: pd.DatetimeIndex, inputs: pd.DataFrame | None) -> pd.DataFrame:
        step = index[1] - index[0]
        out = self.get(index[0], index[-1] + step, step)
        out.index = index
        return out

    def get(self, start: pd.Timestamp, end: pd.Timestamp, step: pd.Timedelta) -> pd.DataFrame:
        """Weather on `[start, end)` at `step`, UTC, period-start labels."""
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
