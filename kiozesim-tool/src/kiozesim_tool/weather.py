"""Weather sources: a one-day or dated file (SRC-011, WX-020..022) and Open-Meteo (spec 0018)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from kiozesim import Source

DAY = pd.Timedelta(days=1)
HOUR = pd.Timedelta(hours=1)


class WeatherError(ValueError):
    """Weather that cannot be had; `box` names the source the message belongs to."""

    def __init__(self, box: str, message: str) -> None:
        self.box = box
        super().__init__(f"{box}: {message}")


def _regrid(
    table: pd.DataFrame,
    src_step: pd.Timedelta,
    start: pd.Timestamp,
    end: pd.Timestamp,
    step: pd.Timedelta,
    what: str,
) -> pd.DataFrame:
    """`table` (rows `src_step` apart) on `[start, end)` at `step`: averaged, or interpolated.

    Raises ValueError naming `what` and the first time the table does not cover (WX-021).
    """
    first, covered = table.index[0], table.index[-1] + src_step
    if start < first:
        raise ValueError(f"{what}: no weather for {start} (it starts at {first})")
    if end > covered:
        raise ValueError(f"{what}: no weather for {max(start, covered)} (it ends at {covered})")
    if step >= src_step:
        out = table.resample(step, origin="epoch", label="left", closed="left").mean()
    else:
        grid = pd.date_range(start, end, freq=step, inclusive="left")
        out = table.reindex(table.index.union(grid))
        out = out.interpolate(method="time", limit_area="inside").ffill().reindex(grid)
    out = out[(out.index >= start) & (out.index < end)]
    out.index.name = "time"
    return out


def _simulate_on(
    get: Callable[[pd.Timestamp, pd.Timestamp, pd.Timedelta], pd.DataFrame],
    index: pd.DatetimeIndex,
) -> pd.DataFrame:
    step = index[1] - index[0]
    out = get(index[0], index[-1] + step, step)
    out.index = index
    return out


class FileWeatherParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    path: Path  # a CSV; apps resolve relative paths before building


class FileWeatherSource(Source[FileWeatherParams]):
    """A weather CSV in one of two shapes, told apart by its `time` column.

    - `HH:MM` (UTC, no date): one day, repeated on every date (SRC-011).
    - full date-times (UTC unless a zone is written): a dated series, never repeated (WX-020).

    No input columns; its output columns are the file's columns.
    """

    params_model = FileWeatherParams

    def __init__(self, params: FileWeatherParams) -> None:
        super().__init__(params)
        path = params.path
        df = pd.read_csv(path, dtype={"time": str})
        if "time" not in df.columns:
            raise ValueError(f"{path}: needs a 'time' column")
        if df.drop(columns="time").isna().any().any():
            raise ValueError(f"{path}: contains empty values")
        values = df.drop(columns="time").astype(float).reset_index(drop=True)
        self.dated = not df["time"].str.fullmatch(r"\d{2}:\d{2}").all()
        if self.dated:
            try:
                if not df["time"].str.match(r"\d{4}-\d{2}-\d{2}[T ]\d").all():
                    raise ValueError
                times = pd.DatetimeIndex([self._utc(t) for t in df["time"]])
            except (ValueError, TypeError):
                raise ValueError(
                    f"{path}: 'time' must be a time of day HH:MM or a date and time "
                    "like 2024-06-01T13:00"
                ) from None
            offsets = times - times[0]
        else:
            offsets = pd.TimedeltaIndex(pd.to_timedelta(df["time"] + ":00"))
        steps = set(offsets.to_series().diff().dropna())
        if len(df) < 2 or len(steps) != 1 or next(iter(steps)) <= pd.Timedelta(0):
            raise ValueError(f"{path}: times must be increasing with one regular step")
        self.step: pd.Timedelta = next(iter(steps))
        if self.dated:
            values.index = times
            self._series = values
        else:
            if offsets[0] != pd.Timedelta(0) or offsets[-1] + self.step != DAY:
                raise ValueError(f"{path}: must cover exactly one day from 00:00")
            self._offsets = offsets
            self._values = values

    @staticmethod
    def _utc(text: str) -> pd.Timestamp:
        ts = pd.Timestamp(text)
        return ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")

    def _simulate(self, index: pd.DatetimeIndex, inputs: pd.DataFrame | None) -> pd.DataFrame:
        return _simulate_on(self.get, index)

    def get(self, start: pd.Timestamp, end: pd.Timestamp, step: pd.Timedelta) -> pd.DataFrame:
        """Weather on `[start, end)` at `step`, UTC, period-start labels."""
        if self.dated:
            return _regrid(self._series, self.step, start, end, step, str(self.params.path))
        # Lay the day over every date from the day before to the day after, so averaging and
        # interpolation at midnight see the neighbouring (identical) day.
        first, last = start.floor("D") - DAY, end.ceil("D") + DAY
        days = pd.date_range(first, last, freq="D", inclusive="left")
        frames = []
        for d in days:
            day = self._values.copy()
            day.index = d + self._offsets
            frames.append(day)
        return _regrid(pd.concat(frames), self.step, start, end, step, str(self.params.path))


# --- Open-Meteo (spec 0018) -------------------------------------------------------------------

FORECAST = "forecast"
ARCHIVE = "archive"
URLS = {
    FORECAST: "https://api.open-meteo.com/v1/forecast",
    ARCHIVE: "https://archive-api.open-meteo.com/v1/archive",
}
FORECAST_PAST_DAYS = 92  # WX-003: the Forecast API reaches this many days back ...
FORECAST_AHEAD_DAYS = 15  # ... and this many days after today
FIRST_DAY = pd.Timestamp("1940-01-01", tz="UTC")
FORECAST_EXPIRY_S = 3600.0  # WX-011
# Our column -> Open-Meteo variable (Domain notes of spec 0018).
VARIABLES = {
    "ghi_w_m2": "shortwave_radiation",
    "dni_w_m2": "direct_normal_irradiance",
    "dhi_w_m2": "diffuse_radiation",
    "temp_air_c": "temperature_2m",
    "wind_speed_m_s": "wind_speed_10m",
    "pressure_hpa": "surface_pressure",
}
# Averages over the hour before their label: moved back one hour to label the period start.
SUNLIGHT = ("ghi_w_m2", "dni_w_m2", "dhi_w_m2")

Fetch = Callable[[str, Mapping[str, str]], dict[str, Any]]


def fetch_json(url: str, query: Mapping[str, str]) -> dict[str, Any]:
    """GET `url?query` as JSON. Raises ValueError with Open-Meteo's reason or the network error."""
    full = f"{url}?{urllib.parse.urlencode(query)}"
    try:
        with urllib.request.urlopen(full, timeout=60) as r:  # noqa: S310 (fixed https URLs)
            data = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            reason = json.load(e).get("reason", e.reason)
        except (ValueError, AttributeError):
            reason = e.reason
        raise ValueError(f"Open-Meteo answered {e.code}: {reason}") from None
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise ValueError(f"cannot reach Open-Meteo: {reason}") from None
    if not isinstance(data, dict):
        raise ValueError("Open-Meteo sent an answer that is not a JSON object")
    if data.get("error"):
        raise ValueError(f"Open-Meteo: {data.get('reason', 'error')}")
    return data


def default_cache_dir() -> Path:
    """`$XDG_CACHE_HOME/kiozesim-tool`, default `~/.cache/kiozesim-tool` (WX-010)."""
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "kiozesim-tool"


class OpenMeteoParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    latitude_deg: float = Field(ge=-90, le=90)
    longitude_deg: float = Field(ge=-180, le=180)


class OpenMeteoSource(Source[OpenMeteoParams]):
    """Real weather for a place from Open-Meteo: the past (from 1940) and the forecast (WX-001).

    No input columns; outputs the columns of `VARIABLES`. The network is only reached when data is
    asked for (WX-007). `fetch`, `cache_dir` and `today` replace the real ones in tests.
    """

    params_model = OpenMeteoParams

    def __init__(
        self,
        params: OpenMeteoParams,
        *,
        fetch: Fetch | None = None,
        cache_dir: Path | None = None,
        today: Callable[[], pd.Timestamp] | None = None,
    ) -> None:
        super().__init__(params)
        self._fetch = fetch
        self._cache_dir = cache_dir
        self._today = today or (lambda: pd.Timestamp.now(tz="UTC"))
        self._warned = False
        self._lat = f"{params.latitude_deg:.4f}"
        self._lon = f"{params.longitude_deg:.4f}"

    def _simulate(self, index: pd.DatetimeIndex, inputs: pd.DataFrame | None) -> pd.DataFrame:
        return _simulate_on(self.get, index)

    def get(self, start: pd.Timestamp, end: pd.Timestamp, step: pd.Timedelta) -> pd.DataFrame:
        """Weather on `[start, end)` at `step`, UTC, period-start labels."""
        core = pd.date_range(start.floor("D"), (end - pd.Timedelta(1)).floor("D"), freq="D")
        days = [core[0] - DAY, *core, core[-1] + DAY]  # margins for the shift and interpolation
        by_api: dict[str, list[pd.Timestamp]] = {FORECAST: [], ARCHIVE: []}
        for d in days:
            api = self._api(d)
            if api is not None:
                by_api[api].append(d)
            elif d in core:
                raise WeatherError(self.name, f"Open-Meteo has no weather for {max(d, start)}")
        hours: dict[pd.Timestamp, dict[str, Any]] = {}
        for api, wanted in by_api.items():
            hours |= self._days(api, wanted)
        table = self._table(hours)
        # the rows the request uses, plus the next one when interpolating between hours
        used = table[(table.index >= start.floor("h")) & (table.index < end.ceil("h"))]
        if step < HOUR:
            used = table[(table.index >= start.floor("h")) & (table.index <= end.ceil("h"))]
        gaps = used.index[used.isna().any(axis=1)]
        if len(gaps):
            raise WeatherError(self.name, f"Open-Meteo has no weather for {gaps[0]}")
        try:
            return _regrid(table.dropna(), HOUR, start, end, step, self.name)
        except ValueError as e:
            raise WeatherError(self.name, str(e).removeprefix(f"{self.name}: ")) from None

    def _api(self, day: pd.Timestamp) -> str | None:
        """Which Open-Meteo API has this day (WX-003), or None."""
        today = self._today().tz_convert("UTC").floor("D")
        if today - FORECAST_PAST_DAYS * DAY <= day <= today + FORECAST_AHEAD_DAYS * DAY:
            return FORECAST
        if FIRST_DAY <= day < today:
            return ARCHIVE
        return None

    def _days(self, api: str, days: list[pd.Timestamp]) -> dict[pd.Timestamp, dict[str, Any]]:
        """Each day's 24 hours of variables, from the cache or fetched in one go per run of days."""
        found: dict[pd.Timestamp, dict[str, Any]] = {}
        missing: list[pd.Timestamp] = []
        for d in days:
            cached = self._cache_read(api, d)
            if cached is None:
                missing.append(d)
            else:
                found[d] = cached
        runs: list[list[pd.Timestamp]] = []
        for d in missing:
            if runs and d - runs[-1][-1] == DAY:
                runs[-1].append(d)
            else:
                runs.append([d])
        for run in runs:
            for d, hourly in self._download(api, run[0], run[-1]).items():
                found[d] = hourly
                self._cache_write(api, d, hourly)
        return found

    def _download(
        self, api: str, first: pd.Timestamp, last: pd.Timestamp
    ) -> dict[pd.Timestamp, dict[str, Any]]:
        query = {
            "latitude": self._lat,
            "longitude": self._lon,
            "hourly": ",".join(VARIABLES.values()),
            "timezone": "UTC",
            "wind_speed_unit": "ms",
            "start_date": first.strftime("%Y-%m-%d"),
            "end_date": last.strftime("%Y-%m-%d"),
        }
        fetch = self._fetch or fetch_json
        try:
            hourly = fetch(URLS[api], query)["hourly"]
            times = pd.DatetimeIndex(hourly["time"]).tz_localize("UTC")
            columns = {v: list(hourly[v]) for v in VARIABLES.values()}
        except ValueError as e:
            raise WeatherError(self.name, str(e)) from None
        except (KeyError, TypeError):
            raise WeatherError(self.name, "Open-Meteo sent an answer without hourly data") from None
        out: dict[pd.Timestamp, dict[str, Any]] = {}
        for d in pd.date_range(first, last, freq="D"):
            rows = [i for i, t in enumerate(times) if t.floor("D") == d]
            out[d] = {v: [columns[v][i] for i in rows] for v in columns}
            out[d]["time"] = [times[i].isoformat() for i in rows]
        return out

    def _table(self, hours: Mapping[pd.Timestamp, Mapping[str, Any]]) -> pd.DataFrame:
        frames = []
        for d in sorted(hours):
            h = hours[d]
            index = pd.DatetimeIndex(h["time"]).tz_convert("UTC")
            frames.append(
                pd.DataFrame({c: h[v] for c, v in VARIABLES.items()}, index=index, dtype=float)
            )
        table = pd.concat(frames).sort_index()
        full = pd.date_range(table.index[0], table.index[-1], freq="h")
        table = table[~table.index.duplicated()].reindex(full)  # a gap in the days becomes NaN
        for c in SUNLIGHT:
            table[c] = table[c].shift(-1)  # value labelled 13:00 is 12:00-13:00 (WX-002)
        return table

    # --- cache (WX-010..012) ---

    def _cache_file(self, api: str, day: pd.Timestamp) -> Path:
        base = self._cache_dir or default_cache_dir()
        place = f"{self._lat}_{self._lon}"
        return base / "open-meteo" / api / place / f"{day.strftime('%Y-%m-%d')}.json"

    def _cache_read(self, api: str, day: pd.Timestamp) -> dict[str, Any] | None:
        path = self._cache_file(api, day)
        try:
            if not path.exists():
                return None
            if api == FORECAST and time.time() - path.stat().st_mtime > FORECAST_EXPIRY_S:
                return None
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or not all(v in data for v in [*VARIABLES.values()]):
                return None
            return data
        except (OSError, ValueError) as e:
            self._warn(f"cannot read weather cache {path}: {e}")
            return None

    def _cache_write(self, api: str, day: pd.Timestamp, hourly: Mapping[str, Any]) -> None:
        path = self._cache_file(api, day)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(hourly))
            tmp.replace(path)
        except OSError as e:
            self._warn(f"cannot write weather cache {path}: {e}")

    def _warn(self, message: str) -> None:
        if not self._warned:
            self._warned = True
            warnings.warn(f"{self.name}: {message}; downloading instead", stacklevel=3)
