"""Spec 0018: real weather, from Open-Meteo and from dated files. No test reaches the network."""

from __future__ import annotations

import io
import json
import os
import urllib.error
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from kiozesim import Source
from kiozesim_tool import cli, weather
from kiozesim_tool.boxes import build_source
from kiozesim_tool.ui import form
from kiozesim_tool.ui.app import app
from kiozesim_tool.weather import (
    VARIABLES,
    FileWeatherParams,
    FileWeatherSource,
    OpenMeteoParams,
    OpenMeteoSource,
    WeatherError,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
TODAY = pd.Timestamp("2026-10-13 08:30", tz="UTC")
EPOCH = pd.Timestamp("2000-01-01", tz="UTC")
_real_fetch_json = weather.fetch_json  # taken before the autouse fixture replaces it
COLUMNS = ["ghi_w_m2", "dni_w_m2", "dhi_w_m2", "temp_air_c", "wind_speed_m_s", "pressure_hpa"]


def hours(t: pd.Timestamp) -> float:
    return (t - EPOCH) / pd.Timedelta("1h")


class FakeOpenMeteo:
    """Answers of Open-Meteo's shape; variable k at label t is the hours since 2000 + 1000 k.

    `plausible` gives weather plants can run on instead (sun from 05:00 to 19:00, 15 °C, 5 m/s,
    1013 hPa); `null_at` labels get `null` in every variable; `fail` makes every call raise.
    """

    def __init__(
        self, null_at: tuple[str, ...] = (), fail: str = "", plausible: bool = False
    ) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.null_at = {pd.Timestamp(t, tz="UTC") for t in null_at}
        self.fail = fail
        self.plausible = plausible

    def value(self, t: pd.Timestamp, k: int) -> float | None:
        if t in self.null_at:
            return None
        if not self.plausible:
            return hours(t) + 1000 * k
        sun = max(0.0, 800 - 16 * (t.hour - 12) ** 2)  # labelled at the hour's end
        return [sun, sun, sun / 4, 15.0, 5.0, 1013.0][k]

    def __call__(self, url: str, query: Mapping[str, str]) -> dict[str, Any]:
        self.calls.append((url, dict(query)))
        if self.fail:
            raise ValueError(self.fail)
        times = pd.date_range(
            pd.Timestamp(query["start_date"], tz="UTC"),
            pd.Timestamp(query["end_date"], tz="UTC") + pd.Timedelta("1D"),
            freq="h",
            inclusive="left",
        )
        hourly: dict[str, Any] = {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in times]}
        for k, v in enumerate(query["hourly"].split(",")):
            hourly[v] = [self.value(t, k) for t in times]
        return {"latitude": 52.23, "utc_offset_seconds": 0, "hourly": hourly}

    def apis(self) -> list[tuple[str, str, str]]:
        return [
            (u.split("//")[1].split(".")[0], q["start_date"], q["end_date"]) for u, q in self.calls
        ]


def source(fake: FakeOpenMeteo, cache: Path, today: pd.Timestamp = TODAY) -> OpenMeteoSource:
    return OpenMeteoSource(
        OpenMeteoParams(name="sky", latitude_deg=52.23, longitude_deg=21.01),
        fetch=fake,
        cache_dir=cache,
        today=lambda: today,
    )


def axis(start: str, end: str, step: str = "1h") -> pd.DatetimeIndex:
    return pd.date_range(
        pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"), freq=step, inclusive="left"
    )


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeOpenMeteo:
    """Default fetch replaced and the cache kept in tmp_path, for sources built by the apps."""
    fake = FakeOpenMeteo(plausible=True)
    monkeypatch.setattr(weather, "fetch_json", fake)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    return fake


# --- online weather ---------------------------------------------------------------------------


@pytest.mark.spec("WX-001")
def test_source_without_inputs_and_its_columns(tmp_path: Path) -> None:
    src = source(FakeOpenMeteo(), tmp_path)
    assert isinstance(src, Source) and src.name == "sky"
    idx = axis("2026-06-21", "2026-06-22")
    out = src.simulate(idx)
    assert out.index.equals(idx) and list(out.columns) == COLUMNS
    for lat, lon in ((91, 0), (0, 181), (-90.5, 0)):
        with pytest.raises(ValueError):
            OpenMeteoParams(name="x", latitude_deg=lat, longitude_deg=lon)


@pytest.mark.spec("WX-002")
def test_query_and_sunlight_moved_to_period_start(tmp_path: Path) -> None:
    fake = FakeOpenMeteo()
    out = source(fake, tmp_path).simulate(axis("2026-06-21", "2026-06-22"))
    q = fake.calls[0][1]
    assert q["timezone"] == "UTC" and q["wind_speed_unit"] == "ms"
    assert q["hourly"].split(",") == list(VARIABLES.values())
    t = pd.Timestamp("2026-06-21 12:00", tz="UTC")
    # the sunlight labelled 13:00 by Open-Meteo is the 12:00-13:00 period here; snapshots stay
    assert out.loc[t, "ghi_w_m2"] == hours(t + pd.Timedelta("1h"))
    assert out.loc[t, "dni_w_m2"] == hours(t + pd.Timedelta("1h")) + 1000
    assert out.loc[t, "temp_air_c"] == hours(t) + 3000
    assert out.loc[t, "pressure_hpa"] == hours(t) + 5000
    last = pd.Timestamp("2026-06-21 23:00", tz="UTC")  # needs the next day's first value
    assert out.loc[last, "ghi_w_m2"] == hours(last + pd.Timedelta("1h"))


@pytest.mark.spec("WX-003")
def test_archive_and_forecast_stitched(tmp_path: Path) -> None:
    fake = FakeOpenMeteo()
    # today - 92 days = 2026-07-13: the forecast's first day
    out = source(fake, tmp_path).simulate(axis("2026-07-11", "2026-07-15"))
    assert fake.apis() == [
        ("api", "2026-07-13", "2026-07-15"),
        ("archive-api", "2026-07-10", "2026-07-12"),
    ]
    assert out.notna().all().all()
    assert (out["temp_air_c"].diff().dropna() == 1).all()  # one hour after another, no gap


@pytest.mark.spec("WX-003")
def test_far_past_from_archive_only_and_future_from_forecast(tmp_path: Path) -> None:
    fake = FakeOpenMeteo()
    source(fake, tmp_path).simulate(axis("2024-06-21", "2024-06-22"))
    source(fake, tmp_path).simulate(axis("2026-10-20", "2026-10-21"))
    assert fake.apis() == [
        ("archive-api", "2024-06-20", "2024-06-22"),
        ("api", "2026-10-19", "2026-10-21"),
    ]


@pytest.mark.spec("WX-004")
def test_average_and_interpolate(tmp_path: Path) -> None:
    src = source(FakeOpenMeteo(), tmp_path)
    day = src.simulate(axis("2026-06-21", "2026-06-23", "1D"))
    first = hours(pd.Timestamp("2026-06-21", tz="UTC"))
    assert day["temp_air_c"].iloc[0] == pytest.approx(first + 3000 + 11.5)  # mean of 0..23
    fine = src.simulate(axis("2026-06-21 23:00", "2026-06-22 00:00", "15min"))
    t = hours(pd.Timestamp("2026-06-21 23:00", tz="UTC")) + 3000
    assert list(fine["temp_air_c"]) == [t, t + 0.25, t + 0.5, t + 0.75]  # into the next day


@pytest.mark.spec("WX-005")
@pytest.mark.parametrize(
    ("start", "end", "first_missing"),
    [
        ("1939-12-31 20:00", "1940-01-01 04:00", "1939-12-31 20:00"),
        ("2026-10-28 00:00", "2026-10-30 00:00", "2026-10-29 00:00"),  # forecast ends 10-28
    ],
)
def test_outside_open_meteo(tmp_path: Path, start: str, end: str, first_missing: str) -> None:
    fake = FakeOpenMeteo()
    with pytest.raises(WeatherError, match=rf"^sky: .*{first_missing}") as e:
        source(fake, tmp_path).simulate(axis(start, end))
    assert e.value.box == "sky" and fake.calls == []  # nothing fetched for a hopeless request


@pytest.mark.spec("WX-005")
def test_last_forecast_hour_has_no_sunlight_after_it(tmp_path: Path) -> None:
    src = source(FakeOpenMeteo(), tmp_path)
    assert len(src.simulate(axis("2026-10-28 00:00", "2026-10-28 23:00"))) == 23
    with pytest.raises(WeatherError, match="2026-10-28 23:00"):
        src.simulate(axis("2026-10-28 00:00", "2026-10-29 00:00"))


@pytest.mark.spec("WX-005")
def test_missing_values_in_the_answer(tmp_path: Path) -> None:
    fake = FakeOpenMeteo(null_at=("2026-06-21 05:00",))
    with pytest.raises(WeatherError, match="sky: .*2026-06-21 04:00"):  # sunlight 04-05 is gone
        source(fake, tmp_path).simulate(axis("2026-06-21", "2026-06-22"))


@pytest.mark.spec("WX-006")
def test_failures_name_the_source(tmp_path: Path) -> None:
    with pytest.raises(WeatherError, match="^sky: cannot reach Open-Meteo: down"):
        source(FakeOpenMeteo(fail="cannot reach Open-Meteo: down"), tmp_path).simulate(
            axis("2026-06-21", "2026-06-22")
        )

    def junk(url: str, query: Mapping[str, str]) -> dict[str, Any]:
        return {"reason": "?"}

    src = OpenMeteoSource(
        OpenMeteoParams(name="sky", latitude_deg=0, longitude_deg=0), fetch=junk, cache_dir=tmp_path
    )
    with pytest.raises(WeatherError, match="without hourly data"):
        src.simulate(axis("2026-06-21", "2026-06-22"))


@pytest.mark.spec("WX-006")
def test_fetch_json_passes_on_the_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    def http_error(url: str, timeout: float) -> None:
        body = io.BytesIO(b'{"error": true, "reason": "start_date is out of range"}')
        raise urllib.error.HTTPError(url, 400, "Bad Request", {}, body)  # type: ignore[arg-type]

    monkeypatch.setattr(weather.urllib.request, "urlopen", http_error)
    with pytest.raises(ValueError, match="answered 400: start_date is out of range"):
        _real_fetch_json("u", {})

    def offline(url: str, timeout: float) -> None:
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(weather.urllib.request, "urlopen", offline)
    with pytest.raises(ValueError, match="cannot reach Open-Meteo: no route"):
        _real_fetch_json("u", {})


@pytest.mark.spec("WX-007")
def test_no_network_when_built(no_network: FakeOpenMeteo) -> None:
    src = build_source("open_meteo", {"name": "sky", "latitude_deg": 52.23, "longitude_deg": 21})
    assert isinstance(src, OpenMeteoSource) and no_network.calls == []
    src.simulate(axis("2026-06-21", "2026-06-22"))
    assert len(no_network.calls) == 1  # the app's default fetch, replaced here


# --- cache ------------------------------------------------------------------------------------


@pytest.mark.spec("WX-010")
def test_second_request_comes_from_the_cache(tmp_path: Path) -> None:
    fake = FakeOpenMeteo()
    first = source(fake, tmp_path).simulate(axis("2026-06-21", "2026-06-22"))
    again = source(fake, tmp_path).simulate(axis("2026-06-21 06:00", "2026-06-22", "15min"))
    assert len(fake.calls) == 1
    assert (
        again.loc[pd.Timestamp("2026-06-21 12:00", tz="UTC"), "ghi_w_m2"]
        == first.loc[pd.Timestamp("2026-06-21 12:00", tz="UTC"), "ghi_w_m2"]
    )
    files = sorted(p.name for p in (tmp_path / "open-meteo" / "archive").rglob("*.json"))
    assert files == ["2026-06-20.json", "2026-06-21.json", "2026-06-22.json"]
    source(fake, tmp_path).simulate(axis("2026-06-21", "2026-06-24"))  # only the new days
    assert fake.apis()[-1] == ("archive-api", "2026-06-23", "2026-06-24")


@pytest.mark.spec("WX-010")
def test_default_cache_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert weather.default_cache_dir() == tmp_path / "kiozesim-tool"
    monkeypatch.delenv("XDG_CACHE_HOME")
    assert weather.default_cache_dir() == Path.home() / ".cache" / "kiozesim-tool"


@pytest.mark.spec("WX-011")
def test_forecast_expires_after_an_hour_archive_never(tmp_path: Path) -> None:
    fake = FakeOpenMeteo()
    for start, end in (("2026-10-14", "2026-10-15"), ("2024-06-21", "2024-06-22")):
        source(fake, tmp_path).simulate(axis(start, end))
    old = pd.Timestamp("2026-10-13 06:00").timestamp()
    for f in (tmp_path / "open-meteo").rglob("*.json"):
        os.utime(f, (old, old))
    n = len(fake.calls)
    source(fake, tmp_path).simulate(axis("2024-06-21", "2024-06-22"))
    assert len(fake.calls) == n
    source(fake, tmp_path).simulate(axis("2026-10-14", "2026-10-15"))
    assert len(fake.calls) == n + 1


@pytest.mark.spec("WX-012")
def test_broken_cache_does_not_stop_a_run(tmp_path: Path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("a file where the cache folder should be")
    fake = FakeOpenMeteo()
    with pytest.warns(UserWarning, match="sky: cannot write weather cache") as caught:
        out = source(fake, blocker).simulate(axis("2026-06-21", "2026-06-22"))
    assert len(out) == 24 and len(caught) == 1  # warned once, though three days failed
    (tmp_path / "c" / "open-meteo" / "archive" / "52.2300_21.0100").mkdir(parents=True)
    (tmp_path / "c" / "open-meteo" / "archive" / "52.2300_21.0100" / "2026-06-21.json").write_text(
        "{not json"
    )
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        assert len(source(fake, tmp_path / "c").simulate(axis("2026-06-21", "2026-06-22"))) == 24


# --- dated files ------------------------------------------------------------------------------


def dated(tmp_path: Path, times: list[str], values: list[float] | None = None) -> FileWeatherSource:
    p = tmp_path / "dated.csv"
    vals = values if values is not None else list(range(len(times)))
    pd.DataFrame({"time": times, "x": vals}).to_csv(p, index=False)
    return FileWeatherSource(FileWeatherParams(name="w", path=p))


def hourly(start: str, n: int, fmt: str = "%Y-%m-%dT%H:%M") -> list[str]:
    return [t.strftime(fmt) for t in pd.date_range(start, periods=n, freq="h")]


@pytest.mark.spec("WX-020")
def test_one_day_files_still_repeat(tmp_path: Path) -> None:
    p = tmp_path / "day.csv"
    p.write_text("time,x\n" + "".join(f"{h:02d}:00,{h}\n" for h in range(24)))
    src = FileWeatherSource(FileWeatherParams(name="w", path=p))
    assert not src.dated
    out = src.simulate(axis("2026-01-05 22:00", "2026-01-06 02:00"))
    assert list(out["x"]) == [22, 23, 0, 1]


@pytest.mark.spec("WX-020")
def test_dated_file_read_as_series(tmp_path: Path) -> None:
    src = dated(tmp_path, hourly("2024-06-01", 48))
    assert src.dated and src.step == pd.Timedelta("1h")
    out = src.simulate(axis("2024-06-01 22:00", "2024-06-02 02:00"))
    assert list(out["x"]) == [22, 23, 24, 25]  # not repeated: the next day has its own values
    zoned = dated(tmp_path, [t + "+02:00" for t in hourly("2024-06-01 02:00", 3)])
    assert zoned.simulate(axis("2024-06-01 00:00", "2024-06-01 02:00"))["x"].tolist() == [0, 1]


@pytest.mark.spec("WX-020")
@pytest.mark.parametrize(
    "times",
    [
        ["2024-06-01T00:00", "2024-06-01T01:00", "2024-06-01T03:00"],  # gap
        ["2024-06-01T01:00", "2024-06-01T00:00"],  # backwards
        ["2024-06-01T00:00", "June 1st"],  # not a date-time
    ],
)
def test_dated_file_rules(tmp_path: Path, times: list[str]) -> None:
    with pytest.raises(ValueError):
        dated(tmp_path, times)
    p = tmp_path / "empty.csv"
    p.write_text("time,x\n2024-06-01T00:00,1\n2024-06-01T01:00,\n")
    with pytest.raises(ValueError, match="empty values"):
        FileWeatherSource(FileWeatherParams(name="w", path=p))


@pytest.mark.spec("WX-021")
def test_dated_file_never_invents_data(tmp_path: Path) -> None:
    src = dated(tmp_path, hourly("2024-06-01", 24))
    with pytest.raises(ValueError, match=r"dated.csv: no weather for 2024-06-02 00:00"):
        src.simulate(axis("2024-06-01 22:00", "2024-06-02 02:00"))
    with pytest.raises(ValueError, match=r"no weather for 2024-05-31 23:00"):
        src.simulate(axis("2024-05-31 23:00", "2024-06-01 02:00"))


@pytest.mark.spec("WX-022")
def test_dated_file_average_and_interpolate(tmp_path: Path) -> None:
    src = dated(tmp_path, hourly("2024-06-01", 24))
    assert src.simulate(axis("2024-06-01", "2024-06-01 04:00", "2h"))["x"].tolist() == [0.5, 2.5]
    fine = src.simulate(axis("2024-06-01 22:00", "2024-06-02", "30min"))
    assert fine["x"].tolist() == [22, 22.5, 23, 23]  # the last hour holds its value


# --- sink -------------------------------------------------------------------------------------


PV = {
    "type": "pv",
    "name": "roof",
    "from": "weather",
    "datasheet": "jinko_solar_jkm440n_54hl4r_b",
    "latitude_deg": 52.23,
    "longitude_deg": 21.01,
    "tilt_deg": 35,
    "azimuth_deg": 180,
    "n_modules": 10,
    "inverter_ac_kw": 4.0,
}
ONLINE = {"type": "open_meteo", "name": "weather", "latitude_deg": 52.23, "longitude_deg": 21.01}


def config(tmp_path: Path, **over: object) -> Path:
    cfg: dict[str, object] = {
        "speed": 0,
        "start": "2026-06-21T00:00",
        "end": "2026-06-22T00:00",
        "sources": [ONLINE],
        "plants": [PV],
        "sinks": [{"type": "stdout"}],
    } | over
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


@pytest.mark.spec("WX-030")
def test_sink_config_takes_open_meteo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], no_network: FakeOpenMeteo
) -> None:
    assert cli.run_sink("15min", str(config(tmp_path))) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert len(lines) == 96 and len(no_network.calls) == 1
    assert max(x["power_kw"]["roof"] for x in lines) > 0


@pytest.mark.spec("WX-031")
def test_example_real_weather_yaml(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], no_network: FakeOpenMeteo
) -> None:
    cfg = yaml.safe_load((EXAMPLES / "real_weather.yaml").read_text())
    sink = yaml.safe_load((EXAMPLES / "sink.yaml").read_text())
    assert cfg["speed"] == 0
    assert pd.Timestamp(cfg["end"]) - pd.Timestamp(cfg["start"]) == pd.Timedelta("7D")
    assert pd.Timestamp(cfg["end"]) < TODAY.tz_localize(None)  # a past week
    online = [s for s in cfg["sources"] if s["type"] == "open_meteo"]
    assert [(s["latitude_deg"], s["longitude_deg"]) for s in online] == [(52.23, 21.01)]
    assert cfg["plants"] == sink["plants"]
    assert cli.run_sink("1h", str(EXAMPLES / "real_weather.yaml")) == 0
    assert len(capsys.readouterr().out.splitlines()) == 7 * 24


@pytest.mark.spec("WX-032")
def test_sink_stops_when_weather_runs_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # past the forecast's last day, 2026-10-28, two days into the run
    cfg = config(tmp_path, start="2026-10-26T00:00", end="2026-11-05T00:00")
    monkeypatch.setattr(OpenMeteoSource, "__init__", _with_today(OpenMeteoSource.__init__))
    assert cli.run_sink("1h", str(cfg)) == 2
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 2 * 24  # the days it had were played
    assert "error: weather: Open-Meteo has no weather for 2026-10-28 23:00" in captured.err


def _with_today(init: Any) -> Any:
    def patched(self: OpenMeteoSource, params: OpenMeteoParams, **kw: Any) -> None:
        init(self, params, today=lambda: TODAY, **kw)

    return patched


# --- web page ---------------------------------------------------------------------------------

client = TestClient(app)
PV_BOX = {
    "type": "pv",
    "shown_type": "pv",
    "name": "roof",
    "datasheet": "jinko_solar_jkm440n_54hl4r_b",
    "latitude_deg": "52.23",
    "longitude_deg": "21.01",
    "altitude_m": "119",
    "tilt_deg": "35",
    "azimuth_deg": "180",
    "n_modules": "10",
    "inverter_ac_kw": "4.0",
    "inverter_efficiency": "0.96",
    "losses_pct": "14",
    "albedo": "0.2",
    "mounting": "open_rack_glass_polymer",
}
SAMPLE = {"type": "sample weather", "shown_type": "sample weather", "name": "weather"}
ONLINE_BOX = {
    "type": "online weather",
    "shown_type": "online weather",
    "name": "weather",
    "latitude_deg": "52.23",
    "longitude_deg": "21.01",
}


def post(action: str, source: dict[str, str], **extra: str) -> str:
    data = {"action": action, "n": "1", "ns": "1", "p0.from.0": "weather"}
    data |= {f"p0.{k}": v for k, v in PV_BOX.items()} | {f"s0.{k}": v for k, v in source.items()}
    r = client.post("/", data=data | extra)
    assert r.status_code == 200
    return r.text


def kwh(page: str) -> float:
    import re

    m = re.search(r'<td data-energy-kwh="roof">([\d.]+)</td>', page)
    assert m, "no result"
    return float(m.group(1))


@pytest.mark.spec("WX-040")
def test_online_weather_box(no_network: FakeOpenMeteo) -> None:
    page = post("apply", {**ONLINE_BOX, "shown_type": "sample weather"})
    assert 'name="s0.latitude_deg"' in page and 'name="s0.longitude_deg"' in page
    assert form.SOURCE_TYPES["online weather"] == ("open_meteo", {})
    ran = post("run", ONLINE_BOX)
    assert kwh(ran) > 0 and len(no_network.calls) == 1
    bad = post("run", {**ONLINE_BOX, "latitude_deg": "95"})
    assert 'data-for="s0.latitude_deg"' in bad and "data-energy-kwh" not in bad


@pytest.mark.spec("WX-041")
def test_run_period(no_network: FakeOpenMeteo) -> None:
    first = client.get("/").text
    assert 'name="run_from"' in first and 'value="2026-06-21"' in first
    assert 'name="run_days"' in first and 'max="31"' in first
    one = kwh(post("run", SAMPLE))
    three = post("run", SAMPLE, run_from="2026-06-21", run_days="3")
    assert kwh(three) == pytest.approx(3 * one, rel=1e-3)
    kept = post("add", SAMPLE, run_from="2025-01-02", run_days="5")
    assert 'value="2025-01-02"' in kept and 'value="5"' in kept
    online = post("run", ONLINE_BOX, run_from="2025-01-02", run_days="2")
    assert kwh(online) > 0
    assert no_network.apis()[-1] == ("archive-api", "2025-01-01", "2025-01-04")
    for field, value in (("run_days", "32"), ("run_days", "1.5"), ("run_from", "next week")):
        bad = post("run", SAMPLE, **{field: value})
        assert f'data-for="{field}"' in bad and "data-energy-kwh" not in bad


@pytest.mark.spec("WX-042")
def test_failed_download_on_the_source_box(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(weather, "fetch_json", FakeOpenMeteo(fail="cannot reach Open-Meteo: x"))
    page = post("run", ONLINE_BOX, run_from="2025-03-04")
    assert '<p class="error" data-for="s0">weather: cannot reach Open-Meteo: x</p>' in page
    assert 'value="2025-03-04"' in page and 'value="52.23"' in page


@pytest.mark.spec("WX-043")
def test_sample_weather_stays_first_and_repeats() -> None:
    first = client.get("/").text
    assert form.SOURCES_OFFERED[0] == "sample weather"
    assert 'name="s0.type"' in first and '<option value="sample weather" selected' in first
    two = post("run", SAMPLE, run_days="2")
    assert kwh(two) == pytest.approx(2 * kwh(post("run", SAMPLE)), rel=1e-3)
