"""HAWT plant, spec 0003."""

import socket
import subprocess
import sys
from importlib.util import find_spec

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from kiozesim.plants.hawt import (
    HAWTDatasheet,
    HAWTInputs,
    HAWTOutput,
    HAWTParams,
    HAWTPlant,
    _library,
)
from kiozesim.timegrid import TimeGridError

from .harness import discover, run_case

needs_wpl = pytest.mark.skipif(find_spec("windpowerlib") is None, reason="needs the 'wind' extra")

# A small made-up turbine: 0 kW below 3 m/s, rated 100 kW from 12 m/s, cut-out after 25 m/s.
DS = {
    "manufacturer": "m",
    "model": "x",
    "rated_power_kw": 100,
    "rotor_diameter_m": 20,
    "wind_speed_m_s": [0, 3, 6, 9, 12, 25],
    "power_kw": [0, 0, 20, 60, 100, 100],
}
DAY = pd.date_range("2026-01-15", periods=24, freq="h", tz="UTC")


def params(**kw: object) -> HAWTParams:
    base = {"name": "t", "datasheet": HAWTDatasheet(**DS), "hub_height_m": 30}
    return HAWTParams(**(base | kw))


def inputs(index: pd.DatetimeIndex = DAY, wind: object = 8.0, **kw: object) -> HAWTInputs:
    base = {"wind_speed_m_s": wind, "temp_air_c": 5.0, "pressure_hpa": 1000.0} | kw
    return HAWTInputs(**{k: pd.Series(v, index=index) for k, v in base.items() if v is not None})


@pytest.fixture
def hide_windpowerlib(monkeypatch):
    for name in [m for m in sys.modules if m == "windpowerlib" or m.startswith("windpowerlib.")]:
        monkeypatch.delitem(sys.modules, name)  # as if never imported...
    monkeypatch.setitem(sys.modules, "windpowerlib", None)  # ...and not installed
    monkeypatch.delitem(sys.modules, "kiozesim.plants.hawt._engine", raising=False)
    _library._turbines.cache_clear()
    yield
    _library._turbines.cache_clear()


# --- parameters and inputs -------------------------------------------------------------


@pytest.mark.spec("WIND-001")
def test_datasheet_fields():
    assert set(HAWTDatasheet.model_fields) == {
        "manufacturer",
        "model",
        "source",
        "rated_power_kw",
        "rotor_diameter_m",
        "wind_speed_m_s",
        "power_kw",
    }
    HAWTDatasheet(**DS | {"power_kw": [0, 0, 20, 60, 100, 105]})  # 1.05 x rated is allowed


@pytest.mark.spec("WIND-001")
@pytest.mark.parametrize(
    "change",
    [
        {"rated_power_kw": 0},
        {"rated_power_kw": float("inf")},
        {"rotor_diameter_m": -1},
        {"power_kw": [0, 0, 20, 60, 100]},  # length differs
        {"wind_speed_m_s": [0], "power_kw": [0]},  # one point
        {"wind_speed_m_s": [-1, 3, 6, 9, 12, 25]},
        {"wind_speed_m_s": [0, 3, 3, 9, 12, 25]},  # not strictly increasing
        {"wind_speed_m_s": [0, 6, 3, 9, 12, 25]},
        {"power_kw": [0, -1, 20, 60, 100, 100]},
        {"power_kw": [0, 0, 20, 60, 100, 105.1]},  # above 1.05 x rated
        {"power_kw": [0, 0, 20, 60, 100, float("nan")]},
    ],
)
def test_datasheet_rejects(change):
    with pytest.raises(ValidationError):
        HAWTDatasheet(**DS | change)


@pytest.mark.spec("WIND-002")
def test_params_fields_and_defaults():
    p = params()
    assert set(HAWTParams.model_fields) == {
        "name",
        "datasheet",
        "hub_height_m",
        "n_turbines",
        "wind_height_m",
        "roughness_length_m",
        "temp_height_m",
        "density_correction",
        "losses_pct",
    }
    assert (
        p.n_turbines,
        p.wind_height_m,
        p.roughness_length_m,
        p.temp_height_m,
        p.density_correction,
        p.losses_pct,
    ) == (1, 10, 0.1, 2, True, 10)
    params(losses_pct=0, n_turbines=1, roughness_length_m=9.99)  # boundaries


@pytest.mark.spec("WIND-002")
@pytest.mark.parametrize(
    "change",
    [
        {"hub_height_m": 0},
        {"n_turbines": 0},
        {"n_turbines": 1.5},
        {"wind_height_m": 0},
        {"roughness_length_m": 0},
        {"roughness_length_m": 10},  # not below wind_height_m (10)
        {"hub_height_m": 5, "wind_height_m": 10, "roughness_length_m": 5},  # not below hub
        {"temp_height_m": 0},
        {"losses_pct": -1},
        {"losses_pct": 100},
        {"hub_height_m": float("inf")},
        {"colour": "white"},
    ],
)
def test_params_reject(change):
    with pytest.raises(ValidationError):
        params(**change)


@pytest.mark.spec("WIND-003")
def test_inputs_wind_only_and_checks():
    HAWTInputs(wind_speed_m_s=pd.Series(5.0, index=DAY))
    HAWTInputs.from_frame(pd.DataFrame({"wind_speed_m_s": 5.0}, index=DAY))
    inputs(temp_air_c=-20.0)  # cold is fine
    with pytest.raises(ValidationError):
        HAWTInputs(temp_air_c=pd.Series(5.0, index=DAY))  # wind missing
    with pytest.raises(ValidationError, match="wind_speed_m_s"):
        inputs(wind=-1.0)
    with pytest.raises(ValidationError, match="pressure_hpa"):
        inputs(pressure_hpa=0.0)
    with pytest.raises(ValidationError, match="temp_air_c"):
        inputs(temp_air_c=float("inf"))


@needs_wpl
@pytest.mark.spec("WIND-004")
@pytest.mark.parametrize("missing", ["temp_air_c", "pressure_hpa"])
def test_density_correction_needs_temp_and_pressure(missing):
    with pytest.raises(ValueError, match=missing):
        HAWTPlant(params()).simulate(inputs(**{missing: None}))


@needs_wpl
@pytest.mark.spec("WIND-004")
def test_without_density_correction_temp_and_pressure_ignored():
    plant = HAWTPlant(params(density_correction=False))
    bare = plant.simulate(inputs(temp_air_c=None, pressure_hpa=None))
    given = plant.simulate(inputs(temp_air_c=-30.0, pressure_hpa=700.0))
    pd.testing.assert_series_equal(bare.power_kw, given.power_kw)


@needs_wpl
@pytest.mark.spec("WIND-005")
def test_step_limit():
    plant = HAWTPlant(params())
    with pytest.raises(TimeGridError, match="1 h"):
        plant.simulate(inputs(pd.date_range("2026-01-01", periods=4, freq="2h", tz="UTC")))
    for freq in ("1h", "10min", "1min"):
        plant.simulate(inputs(pd.date_range("2026-01-01", periods=4, freq=freq, tz="UTC")))


# --- model ---------------------------------------------------------------------------


@needs_wpl
@pytest.mark.spec("WIND-006")
def test_parameters_reach_engine():
    from kiozesim.plants.hawt import _engine

    mc = _engine.build(params(hub_height_m=45, density_correction=False))
    t = mc.power_plant
    assert (t.hub_height, t.nominal_power, t.rotor_diameter) == (45, 100_000, 20)
    assert t.power_curve["wind_speed"].tolist() == DS["wind_speed_m_s"]
    assert t.power_curve["value"].tolist() == [w * 1000 for w in DS["power_kw"]]
    assert mc.density_correction is False
    assert _engine.build(params()).density_correction is True


@needs_wpl
@pytest.mark.spec("WIND-006")
def test_weather_reaches_engine():
    from kiozesim.plants.hawt import _engine

    p = params(wind_height_m=12, temp_height_m=3, roughness_length_m=0.5)
    w = _engine.prepare_weather(p, inputs(wind=7.0, temp_air_c=10.0, pressure_hpa=990.0))
    assert set(w.columns) == {
        ("wind_speed", 12),
        ("roughness_length", 0),
        ("temperature", 3),
        ("pressure", 0),
    }
    row = w.iloc[0]
    assert row[("wind_speed", 12)] == 7.0
    assert row[("roughness_length", 0)] == 0.5
    assert row[("temperature", 3)] == pytest.approx(283.15)
    assert row[("pressure", 0)] == pytest.approx(99_000)
    bare = _engine.prepare_weather(params(density_correction=False), inputs())
    assert {c[0] for c in bare.columns} == {"wind_speed", "roughness_length"}


@pytest.mark.spec("WIND-007")
def test_results_become_outputs(monkeypatch):
    import kiozesim.plants.hawt._engine as engine  # noqa: F401  (needs the module importable)

    fake = pd.DataFrame(
        {"power_w": 50_000.0, "wind_speed_hub_m_s": 9.0, "air_density_kg_m3": 1.2}, index=DAY
    )
    monkeypatch.setattr(engine, "run", lambda p, ts: fake)
    out = HAWTPlant(params(n_turbines=3, losses_pct=10)).simulate(inputs())
    assert out.power_kw.index.equals(DAY)
    assert out.power_kw.iloc[0] == pytest.approx(3 * 50 * 0.9)
    assert out.wind_speed_hub_m_s.iloc[0] == 9.0
    assert out.air_density_kg_m3 is not None and out.air_density_kg_m3.iloc[0] == 1.2


@needs_wpl
@pytest.mark.spec("WIND-008")
def test_no_extrapolation_at_hub_height():
    wind = np.linspace(0, 20, 24)
    out = HAWTPlant(params(hub_height_m=30, wind_height_m=30)).simulate(inputs(wind=wind))
    np.testing.assert_allclose(out.wind_speed_hub_m_s.to_numpy(), wind, rtol=1e-12)


@needs_wpl
@pytest.mark.spec("WIND-009")
def test_zero_outside_curve_and_capped():
    p = params(wind_height_m=30, density_correction=False, losses_pct=0)
    out = HAWTPlant(p).simulate(inputs(wind=[1.0, 2.9, 25.1, 40.0] * 6))
    assert (out.power_kw == 0).all()
    shifted = HAWTDatasheet(**DS | {"wind_speed_m_s": [3, 4, 6, 9, 12, 25]})  # starts at 3 m/s
    out = HAWTPlant(p.model_copy(update={"datasheet": shifted})).simulate(inputs(wind=2.0))
    assert (out.power_kw == 0).all()
    rng = np.random.default_rng(0)
    for dc in (True, False):
        q = params(n_turbines=4, losses_pct=7, density_correction=dc)
        idx = pd.date_range("2026-01-01", periods=500, freq="10min", tz="UTC")
        out = HAWTPlant(q).simulate(
            inputs(idx, wind=rng.uniform(0, 30, 500), temp_air_c=-30.0, pressure_hpa=1050.0)
        )
        assert out.power_kw.max() <= 4 * 100 * 0.93 + 1e-9
        assert out.power_kw.max() > 0


@needs_wpl
@pytest.mark.spec("WIND-010")
def test_output_struct():
    out = HAWTPlant(params()).simulate(inputs())
    assert isinstance(out, HAWTOutput)
    for s in (out.power_kw, out.wind_speed_hub_m_s, out.air_density_kg_m3):
        assert isinstance(s, pd.Series) and s.index.equals(DAY)
    assert 1.1 < out.air_density_kg_m3.iloc[0] < 1.4
    bare = HAWTPlant(params(density_correction=False)).simulate(inputs())
    assert bare.air_density_kg_m3 is None


# --- engine --------------------------------------------------------------------------


@pytest.mark.spec("WIND-011")
def test_import_does_not_load_windpowerlib():
    code = (
        "import sys, kiozesim\n"
        "from kiozesim.plants.hawt import HAWTPlant\n"
        "assert 'windpowerlib' not in sys.modules, 'windpowerlib imported eagerly'\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


@pytest.mark.spec("WIND-011")
def test_missing_windpowerlib_explains_install(hide_windpowerlib):
    with pytest.raises(ImportError, match=r"kiozesim\[wind\]"):
        HAWTPlant(params()).simulate(inputs())


@needs_wpl
@pytest.mark.spec("WIND-012")
def test_model_choices_are_pinned():
    from kiozesim.plants.hawt import _engine

    mc = _engine.build(params())
    assert (
        mc.wind_speed_model,
        mc.temperature_model,
        mc.density_model,
        mc.power_output_model,
        mc.obstacle_height,
        mc.hellman_exp,
    ) == ("logarithmic", "linear_gradient", "barometric", "power_curve", 0, None)


@needs_wpl
@pytest.mark.spec("WIND-012")
@pytest.mark.parametrize("dc", [True, False])
def test_stepwise_run_equals_run_model(dc):
    from kiozesim.plants.hawt import _engine

    p = params(density_correction=dc)
    ts = inputs(wind=np.linspace(0, 20, 24), temp_air_c=-5.0)
    ours = _engine.run(p, ts)["power_w"]
    theirs = _engine.build(p).run_model(_engine.prepare_weather(p, ts)).power_output
    np.testing.assert_allclose(ours.to_numpy(), np.asarray(theirs, dtype=float))


# --- datasheets ----------------------------------------------------------------------


@needs_wpl
@pytest.mark.spec("WIND-013")
def test_library_turbines_listed_and_loadable():
    names = HAWTDatasheet.available()
    assert names == sorted(names)
    assert len(names) == 67
    assert {"E-82/2300", "MM92/2050", "V90/2000"} <= set(names)
    for name in names:
        ds = HAWTDatasheet.bundled(name)
        assert ds.model == name


@needs_wpl
@pytest.mark.spec("WIND-013")
def test_library_mapping():
    folder = _library._folder()
    assert folder is not None
    row = pd.read_csv(folder / "turbine_data.csv").set_index("turbine_type").loc["MM92/2050"]
    curve = pd.read_csv(folder / "power_curves.csv").set_index("turbine_type")
    curve = curve.loc["MM92/2050"].dropna()
    ds = HAWTDatasheet.bundled("MM92/2050")
    assert (ds.manufacturer, ds.source) == (row["manufacturer"], row["source"])
    assert ds.rated_power_kw == row["nominal_power"] / 1000 == 2050
    assert ds.rotor_diameter_m == row["rotor_diameter"]
    assert ds.wind_speed_m_s == [float(v) for v in curve.index]
    assert ds.power_kw == pytest.approx((curve / 1000).tolist())


@needs_wpl
@pytest.mark.spec("WIND-013")
def test_yaml_and_library_listed_together(tmp_path, monkeypatch):
    shelf = tmp_path / "hawt"
    shelf.mkdir()
    (shelf / "my_turbine.yaml").write_text(
        "manufacturer: m\nmodel: x\nrated_power_kw: 100\nrotor_diameter_m: 20\n"
        "wind_speed_m_s: [0, 12, 25]\npower_kw: [0, 100, 100]\n"
    )
    monkeypatch.setattr(HAWTDatasheet, "_shelf_dir", classmethod(lambda cls: shelf))
    names = HAWTDatasheet.available()
    assert "my_turbine" in names and "E-82/2300" in names and names == sorted(names)
    assert HAWTDatasheet.bundled("my_turbine").model == "x"


@needs_wpl
@pytest.mark.spec("WIND-015")
def test_library_needs_no_network(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("network access")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    _library._turbines.cache_clear()
    try:
        for name in HAWTDatasheet.available():
            HAWTDatasheet.bundled(name)
    finally:
        _library._turbines.cache_clear()


@pytest.mark.spec("WIND-016")
def test_without_windpowerlib(hide_windpowerlib):
    assert HAWTDatasheet.available() == []  # no YAML files on the shelf yet
    with pytest.raises(ImportError, match=r"kiozesim\[wind\]"):
        HAWTDatasheet.bundled("E-82/2300")


@needs_wpl
@pytest.mark.spec("WIND-016")
def test_unknown_name():
    with pytest.raises(FileNotFoundError, match="MM92/2050"):
        HAWTDatasheet.bundled("nope")


# --- validation ----------------------------------------------------------------------


@needs_wpl
@pytest.mark.spec("WIND-014")
def test_kelmarsh_annual_energy():
    (case,) = [c for c in discover() if c.id == "hawt/kelmarsh1_2020"]
    run_case(case)
