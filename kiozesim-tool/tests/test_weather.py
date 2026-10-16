"""Spec 0016: the one-day weather file as a source (SRC-011, SRC-012, former SINK-041..044)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from kiozesim_tool.boxes import build_source
from kiozesim_tool.sources import Source
from kiozesim_tool.weather import FileWeatherParams, FileWeatherSource

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_DAY = ROOT / "kiozesim-tool" / "examples" / "day_weather.csv"


def write_day(path: Path, step: str = "1h") -> Path:
    offs = pd.timedelta_range("0h", "1D", freq=step, closed="left")
    times = [
        f"{int(o.total_seconds()) // 3600:02d}:{int(o.total_seconds()) // 60 % 60:02d}"
        for o in offs
    ]
    hours = [o.total_seconds() / 3600 for o in offs]
    pd.DataFrame({"time": times, "x": hours}).to_csv(path, index=False)
    return path


def source(path: Path) -> FileWeatherSource:
    return FileWeatherSource(FileWeatherParams(name="weather", path=path))


def axis(start: pd.Timestamp, end: pd.Timestamp, step: str) -> pd.DatetimeIndex:
    return pd.date_range(start, end, freq=step, inclusive="left")


@pytest.mark.spec("SRC-011")
def test_is_a_source_without_inputs(tmp_path: Path):
    src = source(write_day(tmp_path / "w.csv"))
    assert isinstance(src, Source) and src.name == "weather"
    idx = axis(pd.Timestamp("2026-10-07", tz="UTC"), pd.Timestamp("2026-10-08", tz="UTC"), "1h")
    out = src.simulate(idx)
    assert out.index.equals(idx) and list(out.columns) == ["x"]


@pytest.mark.spec("SRC-011")
@pytest.mark.parametrize(
    "rows",
    [
        "time,x\n00:00,1\n2026-06-21T01:00,2\n",  # both shapes mixed
        "time,x\n00:00,1\n01:00:30,2\n",  # neither shape
        "time,x\n00:00,1\n01:00,2\n",  # not a whole day
        "time,x\n" + "".join(f"{h:02d}:00,1\n" for h in range(24) if h != 5),  # gap
    ],
)
def test_rejects_bad_files(tmp_path: Path, rows: str):
    p = tmp_path / "w.csv"
    p.write_text(rows)
    with pytest.raises(ValueError):
        source(p)


@pytest.mark.spec("SRC-011")
def test_accepts_example_day():
    assert source(EXAMPLE_DAY).step == pd.Timedelta("1h")


@pytest.mark.spec("SRC-011")
def test_repeats_day_on_real_dates(tmp_path: Path):
    src = source(write_day(tmp_path / "w.csv"))
    start = pd.Timestamp("2026-10-07 22:00", tz="UTC")
    w = src.simulate(axis(start, start + pd.Timedelta("4h"), "1h"))
    assert list(w["x"]) == [22, 23, 0, 1]  # past midnight the same day starts on the next date


@pytest.mark.spec("SRC-011")
def test_resample_mean_and_interpolate(tmp_path: Path):
    src = source(write_day(tmp_path / "w.csv"))
    day = pd.Timestamp("2026-10-07", tz="UTC")
    coarse = src.simulate(axis(day, day + pd.Timedelta("1D"), "2h"))
    assert coarse["x"].iloc[0] == 0.5 and coarse["x"].iloc[5] == 10.5  # mean of 10:00 and 11:00
    fine = src.simulate(axis(day + pd.Timedelta("10h"), day + pd.Timedelta("11h"), "15min"))
    assert list(fine["x"]) == [10.0, 10.25, 10.5, 10.75]
    wrap = src.simulate(axis(day + pd.Timedelta("23h"), day + pd.Timedelta("24h"), "30min"))
    assert list(wrap["x"]) == [23.0, 11.5]  # between 23:00 and the next day's 00:00


@pytest.mark.spec("SRC-011")
def test_build_source_resolves_relative_path(tmp_path: Path):
    write_day(tmp_path / "day.csv")
    src = build_source("weather_file", {"name": "w", "path": "day.csv"}, base=tmp_path)
    assert isinstance(src, FileWeatherSource) and src.params.path == tmp_path / "day.csv"
    with pytest.raises(ValueError, match="unknown source type"):
        build_source("nope", {"name": "w"})


@pytest.mark.spec("SRC-012")
def test_apps_take_weather_only_from_weather_module():
    pkg = ROOT / "kiozesim-tool" / "src" / "kiozesim_tool"
    for py in pkg.rglob("*.py"):
        if py.name != "weather.py":
            assert "class FileWeather" not in py.read_text(), py
