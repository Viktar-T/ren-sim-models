"""Spec 0011: the `kiozesim-tool sink` command, sinks, player and weather source."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pandas as pd
import pytest

from kiozesim_tool import cli
from kiozesim_tool.player import Player
from kiozesim_tool.sink import SINKS, Sample, Sink, StdoutSink
from kiozesim_tool.weather import FileWeatherSource, WeatherSource

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
T0 = pd.Timestamp("2026-10-07 10:00", tz="UTC")
NOW = pd.Timestamp("2026-10-07 10:07", tz="UTC")

PV = {
    "type": "pv",
    "name": "roof",
    "datasheet": "jinko_solar_jkm440n_54hl4r_b",
    "latitude_deg": 52.23,
    "longitude_deg": 21.01,
    "tilt_deg": 35,
    "azimuth_deg": 180,
    "n_modules": 10,
    "inverter_ac_kw": 4.0,
}


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


class Recorder(Sink):
    def __init__(self, clock: FakeClock | None = None, cost_s: float = 0.0) -> None:
        self.events: list[str] = []
        self.samples: list[Sample] = []
        self.sent_at: list[float] = []
        self.clock, self.cost_s = clock, cost_s

    def open(self) -> None:
        self.events.append("open")

    def send(self, sample: Sample) -> None:
        self.samples.append(sample)
        if self.clock:
            self.sent_at.append(self.clock.t)
            self.clock.t += self.cost_s  # a slow delivery

    def close(self) -> None:
        self.events.append("close")


def frame(n: int, step: str = "15min", start: pd.Timestamp = T0) -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq=step)
    df = pd.DataFrame({"a": range(n), "b": 1.0}, index=idx, dtype=float)
    df["total"] = df.sum(axis=1)
    return df


def write_day(path: Path, step: str = "1h") -> Path:
    offs = pd.timedelta_range("0h", "1D", freq=step, closed="left")
    times = [
        f"{int(o.total_seconds()) // 3600:02d}:{int(o.total_seconds()) // 60 % 60:02d}"
        for o in offs
    ]
    hours = [o.total_seconds() / 3600 for o in offs]
    pd.DataFrame({"time": times, "x": hours}).to_csv(path, index=False)
    return path


def write_config(tmp_path: Path, **over: object) -> Path:
    import yaml

    cfg: dict[str, object] = {
        "speed": 0,
        "plants": [PV],
        "weather": {"type": "file", "path": str(EXAMPLES / "day_weather.csv")},
        "sinks": [{"type": "stdout"}],
        "end": "2027-01-01T00:00:00Z",  # far away; tests cut playback short with max_chunks
    }
    cfg.update(over)
    cfg = {k: v for k, v in cfg.items() if v is not None}  # None: leave the key out
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


def run(cfg: Path, step: str = "1h", **kw: object) -> int:
    return cli.run_sink(step, str(cfg), now=lambda: NOW, **kw)  # type: ignore[arg-type]


# --- interface -------------------------------------------------------------------------------


@pytest.mark.spec("SINK-001")
def test_sample_fields_and_frozen() -> None:
    s = Sample(T0, pd.Timedelta("15min"), {"a": 1.0})
    assert s.power_kw["a"] == 1.0
    with pytest.raises(AttributeError):
        s.time = T0  # type: ignore[misc]
    with pytest.raises(TypeError):
        s.power_kw["a"] = 2.0  # type: ignore[index]
    with pytest.raises(ValueError):
        Sample(pd.Timestamp("2026-10-07"), pd.Timedelta("1h"), {})


@pytest.mark.spec("SINK-002")
def test_sink_context_manager_closes_on_error() -> None:
    r = Recorder()
    with pytest.raises(RuntimeError), r:
        assert r.events == ["open"]
        raise RuntimeError
    assert r.events == ["open", "close"]
    with pytest.raises(TypeError):
        Sink()  # type: ignore[abstract]


@pytest.mark.spec("SINK-003")
def test_sink_has_no_simulation_or_waiting() -> None:
    clock = FakeClock()
    Player([sink := Recorder()], speed=1, clock=clock).play(frame(3))
    # all waiting is done by the player through the clock, the sink only receives
    assert len(sink.samples) == 3
    assert not any(hasattr(Sink, a) for a in ("simulate", "sleep", "play"))


@pytest.mark.spec("SINK-004")
def test_sinks_registry_and_settings() -> None:
    assert SINKS["stdout"] is StdoutSink
    assert all(issubclass(c, Sink) for c in SINKS.values())
    assert isinstance(StdoutSink.from_settings({}), StdoutSink)
    with pytest.raises(ValueError):
        StdoutSink.from_settings({"host": "x"})


# --- player ----------------------------------------------------------------------------------


@pytest.mark.spec("SINK-010")
def test_player_sends_every_row_in_order_to_every_sink() -> None:
    a, b = Recorder(), Recorder()
    df = frame(4).iloc[::-1]
    Player([a, b], speed=0).play(df)
    for r in (a, b):
        assert [s.time for s in r.samples] == list(df.index[::-1])
        assert r.samples[1].power_kw == {"a": 1.0, "b": 1.0}  # no total
        assert r.samples[0].step == pd.Timedelta("15min")


@pytest.mark.spec("SINK-011")
@pytest.mark.spec("SINK-013")
def test_player_paces_without_drift() -> None:
    clock = FakeClock()
    sink = Recorder(clock, cost_s=7.0)  # each send takes 7 s of a 15 s slot
    player = Player([sink], speed=60, clock=clock)  # 15 min step -> 15 s
    player.play(frame(4))
    player.play(frame(4, start=T0 + pd.Timedelta("1h")))  # next chunk continues the timeline
    assert sink.sent_at == [15.0 * i for i in range(8)]


@pytest.mark.spec("SINK-012")
def test_speed_zero_never_waits() -> None:
    clock = FakeClock()
    Player([Recorder()], speed=0, clock=clock).play(frame(10))
    assert clock.sleeps == []


@pytest.mark.spec("SINK-015")
def test_overdue_rows_sent_at_once_none_skipped() -> None:
    clock = FakeClock()
    sink = Recorder(clock, cost_s=40.0)  # slower than the 15 s slot
    Player([sink], speed=60, clock=clock).play(frame(4))
    assert len(sink.samples) == 4
    assert sink.sent_at == [0.0, 40.0, 80.0, 120.0]  # back to back, no extra waiting
    assert clock.sleeps == []


@pytest.mark.spec("SINK-014")
def test_ctrl_c_closes_sinks_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Interrupting(Recorder):
        def send(self, sample: Sample) -> None:
            super().send(sample)
            if len(self.samples) == 3:
                raise KeyboardInterrupt

    rec = Interrupting()
    monkeypatch.setattr(Interrupting, "from_settings", classmethod(lambda cls, s: rec))
    monkeypatch.setitem(SINKS, "rec", Interrupting)
    assert run(write_config(tmp_path, sinks=[{"type": "rec"}])) == 0
    assert len(rec.samples) == 3
    assert rec.events == ["open", "close"]


# --- weather source --------------------------------------------------------------------------


@pytest.mark.spec("SINK-040")
def test_weather_source_interface() -> None:
    assert issubclass(FileWeatherSource, WeatherSource)
    with pytest.raises(TypeError):
        WeatherSource()  # type: ignore[abstract]


@pytest.mark.spec("SINK-041")
@pytest.mark.parametrize(
    "rows",
    [
        "time,x\n2026-06-21T00:00:00Z,1\n2026-06-21T01:00:00Z,2\n",  # dates
        "time,x\n00:00,1\n01:00,2\n",  # not a whole day
        "time,x\n" + "".join(f"{h:02d}:00,1\n" for h in range(24) if h != 5),  # gap
    ],
)
def test_file_source_rejects_bad_files(tmp_path: Path, rows: str) -> None:
    p = tmp_path / "w.csv"
    p.write_text(rows)
    with pytest.raises(ValueError):
        FileWeatherSource(p)


@pytest.mark.spec("SINK-041")
def test_file_source_accepts_example_day() -> None:
    assert FileWeatherSource(EXAMPLES / "day_weather.csv").step == pd.Timedelta("1h")


@pytest.mark.spec("SINK-042")
def test_file_source_repeats_day_on_real_dates(tmp_path: Path) -> None:
    src = FileWeatherSource(write_day(tmp_path / "w.csv"))
    start = pd.Timestamp("2026-10-07 22:00", tz="UTC")
    w = src.get(start, start + pd.Timedelta("4h"), pd.Timedelta("1h"))
    assert list(w.index) == list(pd.date_range(start, periods=4, freq="1h"))
    assert list(w["x"]) == [22, 23, 0, 1]  # past midnight the same day starts on the next date


@pytest.mark.spec("SINK-043")
def test_playback_starts_now_rounded_down(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write_config(tmp_path), "15min", max_chunks=1) == 0
    first = json.loads(capsys.readouterr().out.splitlines()[0])
    assert first["time"] == "2026-10-07T10:00:00Z"


@pytest.mark.spec("SINK-044")
def test_resample_mean_and_interpolate(tmp_path: Path) -> None:
    src = FileWeatherSource(write_day(tmp_path / "w.csv"))
    day = pd.Timestamp("2026-10-07", tz="UTC")
    coarse = src.get(day, day + pd.Timedelta("1D"), pd.Timedelta("2h"))
    assert coarse["x"].iloc[0] == 0.5 and coarse["x"].iloc[5] == 10.5  # mean of 10:00 and 11:00
    fine = src.get(day + pd.Timedelta("10h"), day + pd.Timedelta("11h"), pd.Timedelta("15min"))
    assert list(fine["x"]) == [10.0, 10.25, 10.5, 10.75]
    wrap = src.get(day + pd.Timedelta("23h"), day + pd.Timedelta("24h"), pd.Timedelta("30min"))
    assert list(wrap["x"]) == [23.0, 11.5]  # between 23:00 and the next day's 00:00


# --- command ---------------------------------------------------------------------------------


@pytest.mark.spec("SINK-020")
def test_sink_command_streams_a_day(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = write_config(tmp_path, plants=[PV, {**PV, "name": "shed", "n_modules": 4}])
    assert run(cfg, "30min", max_chunks=2) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert len(lines) == 96  # two days of half-hours
    assert lines[0]["step_s"] == 1800
    assert set(lines[0]["power_kw"]) == {"roof", "shed"}
    assert any(x["power_kw"]["roof"] > 0 for x in lines)


@pytest.mark.spec("SINK-021")
def test_config_file_and_relative_weather(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_day(tmp_path / "day.csv")
    cfg = write_config(
        tmp_path,
        weather={"type": "file", "path": "day.csv"},
        plants=[{**PV, "datasheet": "jinko_solar_jkm440n_54hl4r_b"}],
    )
    # day.csv has no PV columns -> a clear config error, proving the relative path was used
    assert run(cfg, max_chunks=1) == 2
    assert "ghi_w_m2" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["sink", "1h", "--config", str(cfg), "--speed", "2"])  # no other options


@pytest.mark.spec("SINK-022")
def test_speed_from_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    assert run(write_config(tmp_path, speed=3600), clock=clock, max_chunks=1) == 0
    assert clock.sleeps and all(s == pytest.approx(1.0) for s in clock.sleeps)  # 1 h -> 1 s
    cfg = write_config(tmp_path, speed=None)
    from kiozesim_tool import config

    assert config.load(cfg)[0].speed == 1.0


@pytest.mark.spec("SINK-023")
@pytest.mark.parametrize(
    ("step", "over", "msg"),
    [
        ("banana", {}, "invalid step"),
        ("7min", {}, "divide one day"),
        ("1h", {"sinks": [{"type": "nope"}]}, "unknown sink"),
        ("1h", {"plants": [{**PV, "n_modules": 0}]}, "n_modules"),
        ("1h", {"plants": [{**PV, "datasheet": "nope"}]}, "nope"),
        ("1h", {"plants": [{**PV, "type": "nope"}]}, "unknown plant type"),
        ("1h", {"colour": "red"}, "colour"),
        ("2h", {}, "at most 1 h"),
        ("1h", {"end": None}, "speed 0 needs an end"),
        ("1h", {"start": "2026-10-07T12:00", "end": "2026-10-07T11:00"}, "later than start"),
        ("1h", {"start": "2026-10-07T12:30"}, "not on the 1h grid"),
        ("1h", {"start": "2026-10-07T12:00", "end": "2026-10-07T13:30"}, "not on the 1h grid"),
    ],
)
def test_invalid_input_fails_before_sending(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], step: str, over: dict[str, object], msg: str
) -> None:
    assert run(write_config(tmp_path, **over), step, max_chunks=1) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert msg in err


@pytest.mark.spec("SINK-030")
def test_stdout_json_line() -> None:
    buf = io.StringIO()
    StdoutSink(buf).send(Sample(T0, pd.Timedelta("15min"), {"roof": 1.5}))
    assert buf.getvalue().endswith("\n") and buf.getvalue().count("\n") == 1
    assert json.loads(buf.getvalue()) == {
        "time": "2026-10-07T10:00:00Z",
        "step_s": 900,
        "power_kw": {"roof": 1.5},
    }


@pytest.mark.spec("SINK-024")
@pytest.mark.parametrize(
    ("start", "end", "step", "first", "n"),
    [
        (
            "2026-01-10T22:00Z",
            "2026-01-11T02:00Z",
            "1h",
            "2026-01-10T22:00:00Z",
            4,
        ),  # over midnight
        ("2026-01-10T00:00Z", "2026-01-13T00:00Z", "1h", "2026-01-10T00:00:00Z", 72),  # 3 chunks
        ("2026-01-10T12:00", "2026-01-10T12:15", "15min", "2026-01-10T12:00:00Z", 1),  # naive=UTC
        ("2026-01-10T13:00+01:00", "2026-01-10T14:00+01:00", "30min", "2026-01-10T12:00:00Z", 2),
    ],
)
def test_time_range_played_exactly_then_exits(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    start: str,
    end: str,
    step: str,
    first: str,
    n: int,
) -> None:
    assert run(write_config(tmp_path, start=start, end=end), step) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert len(lines) == n
    assert lines[0]["time"] == first
    times = [pd.Timestamp(x["time"]) for x in lines]
    assert times == sorted(set(times))
    stop = pd.Timestamp(end)
    assert times[-1] < (stop.tz_localize("UTC") if stop.tz is None else stop)


@pytest.mark.spec("SINK-025")
def test_speed_zero_needs_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write_config(tmp_path, end=None)) == 2
    assert "speed 0 needs an end" in capsys.readouterr().err
    clock = FakeClock()
    assert run(write_config(tmp_path, end=None, speed=3600), clock=clock, max_chunks=1) == 0


# --- plant types and examples ----------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
# spec prefix -> plant type key in kiozesim.plants.REGISTRY
PREFIX_TO_TYPE = {"PV": "pv", "WIND": "hawt", "VAWT": "vawt", "BIO": "biogas", "BOIL": "boiler"}
HAWT = {"type": "hawt", "name": "turbine", "datasheet": "E-82/2300", "hub_height_m": 108}
VAWT = {"type": "vawt", "name": "spire", "datasheet": "mariah_power_windspire", "hub_height_m": 10}
ONE_OF_EACH = {"pv": PV, "hawt": HAWT, "vawt": VAWT}  # a working config entry per implemented type


def implemented_types() -> set[str]:
    types = set()
    for spec in (ROOT / "specs").glob("[0-9]*/spec.md"):
        fm = dict(
            line.split(":", 1) for line in spec.read_text().split("---")[1].strip().splitlines()
        )
        prefix, status = fm["prefix"].strip(), fm["status"].split("#")[0].strip()
        if prefix in PREFIX_TO_TYPE and status == "implemented":
            types.add(PREFIX_TO_TYPE[prefix])
    return types


@pytest.mark.spec("SINK-026")
def test_every_implemented_type_usable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import tomllib

    assert implemented_types() <= set(ONE_OF_EACH), "add a config entry for the new type"
    plants = [ONE_OF_EACH[t] for t in sorted(implemented_types())]
    assert run(write_config(tmp_path, plants=plants), max_chunks=1) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert set(lines[0]["power_kw"]) == {p["name"] for p in plants}
    assert any(x["power_kw"]["turbine"] > 0 for x in lines)
    deps = tomllib.loads((ROOT / "kiozesim-tool" / "pyproject.toml").read_text())
    assert "kiozesim[pv,wind]" in deps["project"]["dependencies"]


@pytest.mark.spec("SINK-045")
def test_example_weather_columns_match_ui_sample() -> None:
    day = pd.read_csv(EXAMPLES / "day_weather.csv")
    assert {"ghi_w_m2", "temp_air_c", "wind_speed_m_s", "pressure_hpa"} <= set(day.columns)
    ui = pd.read_csv(ROOT / "kiozesim-ui" / "src" / "kiozesim_ui" / "sample_weather.csv")
    pd.testing.assert_frame_equal(day.drop(columns="time"), ui.drop(columns="time"))
    assert (day["time"] == pd.to_datetime(ui["time"]).dt.strftime("%H:%M")).all()


@pytest.mark.spec("SINK-046")
def test_example_sink_yaml_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import yaml

    cfg = yaml.safe_load((EXAMPLES / "sink.yaml").read_text())
    assert {p["type"] for p in cfg["plants"]} == implemented_types()
    cfg["speed"] = 0
    cfg["weather"]["path"] = str(EXAMPLES / cfg["weather"]["path"])
    p = tmp_path / "sink.yaml"
    p.write_text(yaml.safe_dump(cfg))
    assert run(p, "15min") == 0
    lines = capsys.readouterr().out.splitlines()
    start, end = pd.Timestamp(cfg["start"]), pd.Timestamp(cfg["end"])
    assert len(lines) == (end - start) / pd.Timedelta("15min")
