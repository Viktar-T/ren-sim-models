"""PV plant, spec 0002."""

import subprocess
import sys
from importlib.util import find_spec

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from kiozesim.plants.pv import PVDatasheet, PVInputs, PVOutput, PVParams, PVPlant
from kiozesim.timegrid import TimeGridError

from .harness import discover, run_case

needs_pvlib = pytest.mark.skipif(find_spec("pvlib") is None, reason="needs the 'pv' extra")

LAT, LON = 52.23, 21.01
DS = {"manufacturer": "m", "model": "x", "pdc0_w": 400, "gamma_pdc_per_k": -0.0035}
DAY = pd.date_range("2025-06-21", periods=24, freq="h", tz="UTC")


def params(**kw: object) -> PVParams:
    base = {
        "name": "roof",
        "datasheet": PVDatasheet(**DS),
        "latitude_deg": LAT,
        "longitude_deg": LON,
        "tilt_deg": 35,
        "azimuth_deg": 180,
        "n_modules": 10,
        "inverter_ac_kw": 3.0,
    }
    return PVParams(**(base | kw))


def const(index: pd.DatetimeIndex, **values: float) -> PVInputs:
    base = {"ghi_w_m2": 100.0, "temp_air_c": 10.0, "wind_speed_m_s": 2.0} | values
    return PVInputs(**{k: pd.Series(v, index=index) for k, v in base.items()})


def clear_sky(
    index: pd.DatetimeIndex = DAY, components: bool = True, temp: float = 20.0, wind: float = 2.0
) -> PVInputs:
    """Clear-sky test weather (pvlib's clear-sky model), evaluated mid-period."""
    from pvlib.location import Location

    cs = Location(LAT, LON, tz="UTC").get_clearsky(index + (index[1] - index[0]) / 2)
    cs = cs.set_axis(index).rename(columns=lambda c: f"{c}_w_m2")
    df = cs.assign(temp_air_c=temp, wind_speed_m_s=wind)
    return PVInputs.from_frame(df if components else df.drop(columns=["dni_w_m2", "dhi_w_m2"]))


# --- parameters and inputs -------------------------------------------------------------


@pytest.mark.spec("PV-001")
def test_datasheet_fields():
    assert set(PVDatasheet.model_fields) == {
        "manufacturer",
        "model",
        "source",
        "pdc0_w",
        "gamma_pdc_per_k",
    }
    for gamma in (-0.01, -0.0035, 0.0):
        PVDatasheet(**DS | {"gamma_pdc_per_k": gamma})


@pytest.mark.spec("PV-001")
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pdc0_w", 0),
        ("pdc0_w", -400),
        ("pdc0_w", float("inf")),
        ("gamma_pdc_per_k", -0.35),
        ("gamma_pdc_per_k", 0.001),
        ("gamma_pdc_per_k", float("nan")),
    ],
)
def test_datasheet_rejects(field, value):
    with pytest.raises(ValidationError, match=field):
        PVDatasheet(**DS | {field: value})


@pytest.mark.spec("PV-002")
def test_params_fields_and_defaults():
    defaults = {
        "altitude_m": 0.0,
        "inverter_efficiency": 0.96,
        "losses_pct": 14.0,
        "albedo": 0.2,
        "mounting": "open_rack_glass_polymer",
    }
    required = {
        "name",
        "datasheet",
        "latitude_deg",
        "longitude_deg",
        "tilt_deg",
        "azimuth_deg",
        "n_modules",
        "inverter_ac_kw",
    }
    fields = PVParams.model_fields
    assert set(fields) == required | set(defaults)
    assert {k for k, f in fields.items() if f.is_required()} == required
    p = params()
    assert {k: getattr(p, k) for k in defaults} == defaults


@pytest.mark.spec("PV-002")
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("latitude_deg", 90.1),
        ("latitude_deg", -91),
        ("longitude_deg", 181),
        ("altitude_m", -501),
        ("altitude_m", 9001),
        ("tilt_deg", -1),
        ("tilt_deg", 91),
        ("azimuth_deg", -1),
        ("azimuth_deg", 360),
        ("n_modules", 0),
        ("n_modules", 2.5),
        ("inverter_ac_kw", 0),
        ("inverter_ac_kw", float("inf")),
        ("inverter_efficiency", 0),
        ("inverter_efficiency", 1.01),
        ("losses_pct", -1),
        ("losses_pct", 100),
        ("albedo", -0.1),
        ("albedo", 1.1),
        ("mounting", "roof"),
    ],
)
def test_params_reject_out_of_range(field, value):
    with pytest.raises(ValidationError, match=field):
        params(**{field: value})


@pytest.mark.spec("PV-002")
def test_params_accept_boundaries():
    params(tilt_deg=0, azimuth_deg=0, losses_pct=0, albedo=1, inverter_efficiency=1)
    params(tilt_deg=90, azimuth_deg=359.9, latitude_deg=-90, longitude_deg=-180)


@pytest.mark.spec("PV-003")
def test_inputs_ghi_only_and_pair():
    ts = const(DAY)
    assert ts.dni_w_m2 is None and ts.dhi_w_m2 is None
    df = pd.DataFrame({"ghi_w_m2": 1.0, "temp_air_c": 1.0, "wind_speed_m_s": 1.0}, index=DAY)
    assert PVInputs.from_frame(df).dni_w_m2 is None
    full = PVInputs.from_frame(df.assign(dni_w_m2=1.0, dhi_w_m2=1.0))
    assert full.dni_w_m2 is not None and full.dhi_w_m2 is not None


@pytest.mark.spec("PV-003")
@pytest.mark.parametrize("only", ["dni_w_m2", "dhi_w_m2"])
def test_inputs_reject_half_pair(only):
    with pytest.raises(ValidationError, match="together"):
        const(DAY, **{only: 50.0})


@pytest.mark.spec("PV-003")
@pytest.mark.parametrize("missing", ["ghi_w_m2", "temp_air_c", "wind_speed_m_s"])
def test_inputs_require_fields(missing):
    s = pd.Series(1.0, index=DAY)
    kw = {k: s for k in ("ghi_w_m2", "temp_air_c", "wind_speed_m_s") if k != missing}
    with pytest.raises(ValidationError, match=missing):
        PVInputs(**kw)


@pytest.mark.spec("PV-004")
@pytest.mark.parametrize("name", ["ghi_w_m2", "dni_w_m2", "dhi_w_m2", "wind_speed_m_s"])
def test_inputs_reject_negative(name):
    values = {"dni_w_m2": 50.0, "dhi_w_m2": 50.0}
    ts = const(DAY, **values).to_frame()
    ts.iloc[12, ts.columns.get_loc(name)] = -1.0
    with pytest.raises(ValidationError, match=f"{name}: contains negative"):
        PVInputs.from_frame(ts)


@pytest.mark.spec("PV-004")
def test_inputs_accept_frost_reject_inf():
    const(DAY, temp_air_c=-20.0)
    with pytest.raises(ValidationError, match="ghi_w_m2: contains non-finite"):
        const(DAY, ghi_w_m2=float("inf"))


@pytest.mark.spec("PV-005")
def test_rejects_steps_over_one_hour():
    two_hourly = pd.date_range("2025-06-21", periods=12, freq="2h", tz="UTC")
    with pytest.raises(TimeGridError, match="1 h"):
        PVPlant(params()).simulate(const(two_hourly))


@needs_pvlib
@pytest.mark.spec("PV-005")
@pytest.mark.parametrize("freq", ["h", "15min", "1min"])
def test_accepts_steps_up_to_one_hour(freq):
    index = pd.date_range("2025-06-21 10:00", periods=8, freq=freq, tz="UTC")
    assert PVPlant(params()).simulate(const(index)).power_kw.index.equals(index)


# --- our side of the engine: what goes in, what comes out --------------------------------
# pvlib's physics is pvlib's to test; it is checked here only end to end, by PV-018.


def weather_for(ts: PVInputs) -> pd.DataFrame:
    from kiozesim.plants.pv._engine import build_modelchain, prepare_weather

    return prepare_weather(ts, build_modelchain(params()).location)


def raw_results(index: pd.DatetimeIndex, **cols: object) -> pd.DataFrame:
    """Made-up pvlib results on period middles, for testing what we do with them."""
    base = {"ac_w": 900.0, "dc_w": 1000.0, "poa_w_m2": 500.0, "temp_cell_c": 30.0}
    mid = index + (index[1] - index[0]) / 2
    return pd.DataFrame(base | {"sun_elevation_deg": 30.0} | cols, index=mid)


@needs_pvlib
@pytest.mark.spec("PV-006")
@pytest.mark.parametrize("freq", ["h", "15min"])
def test_engine_sees_period_middles(freq):
    index = pd.date_range("2025-06-21 00:10", periods=8, freq=freq, tz="UTC")
    assert weather_for(const(index)).index.equals(index + (index[1] - index[0]) / 2)


@needs_pvlib
@pytest.mark.spec("PV-006")
def test_results_return_on_input_labels():
    from kiozesim.plants.pv._engine import collect

    index = pd.date_range("2025-06-21 00:10", periods=4, freq="h", tz="UTC")  # 10 past
    raw = raw_results(index)
    out = collect(raw, weather_for(const(index)), index)
    assert out.index.equals(index)
    full = PVPlant(params()).simulate(clear_sky(index))
    for s in (full.power_kw, full.dc_kw, full.poa_w_m2, full.temp_cell_c):
        assert s.index.equals(index)


@needs_pvlib
@pytest.mark.spec("PV-007")
def test_given_dni_dhi_reach_engine_unchanged():
    w = weather_for(const(DAY, dni_w_m2=300.0, dhi_w_m2=80.0))
    assert (w["dni"] == 300.0).all() and (w["dhi"] == 80.0).all()


@needs_pvlib
@pytest.mark.spec("PV-007")
def test_missing_dni_dhi_come_from_erbs(monkeypatch):
    from kiozesim.plants.pv import _engine

    seen = {}

    def fake_erbs(ghi, zenith, times):
        seen.update(ghi=np.asarray(ghi), times=times)
        return {"dni": pd.Series(111.0, index=times), "dhi": pd.Series(22.0, index=times)}

    monkeypatch.setattr(_engine, "erbs", fake_erbs)
    ts = const(DAY, ghi_w_m2=250.0)
    w = weather_for(ts)
    assert (seen["ghi"] == 250.0).all() and seen["times"].equals(w.index)
    assert (w["dni"] == 111.0).all() and (w["dhi"] == 22.0).all()


@needs_pvlib
@pytest.mark.spec("PV-020")
def test_parameters_reach_pvlib():
    import inspect

    from pvlib.pvsystem import pvwatts_losses
    from pvlib.temperature import TEMPERATURE_MODEL_PARAMETERS

    from kiozesim.plants.pv._engine import build_modelchain

    p = params(
        latitude_deg=50.1,
        longitude_deg=19.9,
        altitude_m=220,
        tilt_deg=30,
        azimuth_deg=200,
        albedo=0.31,  # not pvlib's default (0.25)
        n_modules=12,
        inverter_ac_kw=4.5,
        inverter_efficiency=0.97,
        losses_pct=9.5,
        mounting="close_mount_glass_glass",
    )
    mc = build_modelchain(p)
    loc, array = mc.location, mc.system.arrays[0]
    assert (loc.latitude, loc.longitude, loc.altitude, str(loc.tz)) == (50.1, 19.9, 220, "UTC")
    assert (array.mount.surface_tilt, array.mount.surface_azimuth, array.albedo) == (30, 200, 0.31)
    assert array.module_parameters == {"pdc0": 12 * 400, "gamma_pdc": -0.0035}
    assert mc.system.inverter_parameters == {
        "pdc0": pytest.approx(4500 / 0.97),
        "eta_inv_nom": 0.97,
    }
    sapm = TEMPERATURE_MODEL_PARAMETERS["sapm"]["close_mount_glass_glass"]
    assert array.temperature_model_parameters == sapm
    components = set(inspect.signature(pvwatts_losses).parameters)
    expected = {c: 0.0 for c in components} | {"soiling": 9.5}
    assert mc.system.losses_parameters == expected


@needs_pvlib
@pytest.mark.spec("PV-020")
def test_weather_reaches_pvlib():
    values = {
        "ghi_w_m2": 400.0,
        "dni_w_m2": 500.0,
        "dhi_w_m2": 90.0,
        "temp_air_c": -4.0,
        "wind_speed_m_s": 6.5,
    }
    w = weather_for(const(DAY, **values))
    names = {
        "ghi_w_m2": "ghi",
        "dni_w_m2": "dni",
        "dhi_w_m2": "dhi",
        "temp_air_c": "temp_air",
        "wind_speed_m_s": "wind_speed",
    }
    assert set(w.columns) == set(names.values())
    for ours, theirs in names.items():
        assert (w[theirs] == values[ours]).all()


@pytest.mark.spec("PV-021")
def test_engine_results_become_outputs(monkeypatch):
    pytest.importorskip("pvlib")
    from kiozesim.plants.pv import _engine

    def fake_run(p, ts):
        cols = {"ac_w": 1500.0, "dc_w": 1600.0, "poa_w_m2": 700.0, "temp_cell_c": 35.0}
        return pd.DataFrame(cols, index=ts.index)

    monkeypatch.setattr(_engine, "run", fake_run)
    out = PVPlant(params()).simulate(const(DAY))
    assert (out.power_kw == 1.5).all() and (out.dc_kw == 1.6).all()
    assert (out.poa_w_m2 == 700.0).all() and (out.temp_cell_c == 35.0).all()


@needs_pvlib
@pytest.mark.spec("PV-021")
def test_missing_values_without_light_are_filled():
    from kiozesim.plants.pv._engine import collect

    index = DAY[:3]
    nan = float("nan")
    # night; dawn with the sun up but no light (seen in PVGIS data); daylight
    raw = raw_results(index, sun_elevation_deg=[-5.0, 2.8, 30.0])
    raw.iloc[:2] = raw.iloc[:2].assign(ac_w=nan, dc_w=nan, poa_w_m2=nan, temp_cell_c=nan)
    weather = weather_for(const(index, ghi_w_m2=0.0, temp_air_c=-3.0))
    weather["ghi"] = [0.0, 0.0, 400.0]
    out = collect(raw, weather, index)
    assert out.iloc[:2][["ac_w", "dc_w", "poa_w_m2"]].eq(0).all().all()
    assert (out["temp_cell_c"].iloc[:2] == -3.0).all()
    assert out.iloc[2].tolist() == [900.0, 1000.0, 500.0, 30.0]  # daylight untouched


@needs_pvlib
@pytest.mark.spec("PV-021")
def test_missing_value_in_daylight_raises():
    from kiozesim.plants.pv._engine import collect

    raw = raw_results(DAY[:2], ac_w=[float("nan"), 900.0])
    with pytest.raises(RuntimeError, match="daylight"):
        collect(raw, weather_for(const(DAY[:2], ghi_w_m2=400.0)), DAY[:2])


@needs_pvlib
@pytest.mark.spec("PV-014")
def test_no_ghi_means_no_power():
    from kiozesim.plants.pv._engine import collect

    raw = raw_results(DAY[:2])  # engine claims 900 W in both periods
    weather = weather_for(const(DAY[:2]))
    weather["ghi"] = [0.0, 400.0]
    out = collect(raw, weather, DAY[:2])
    assert out["ac_w"].tolist() == [0.0, 900.0] and out["dc_w"].tolist() == [0.0, 1000.0]


@needs_pvlib
@pytest.mark.spec("PV-015")
def test_output_has_diagnostics():
    out = PVPlant(params()).simulate(clear_sky())
    assert isinstance(out, PVOutput)
    for name in ("dc_kw", "poa_w_m2", "temp_cell_c"):
        s = getattr(out, name)
        assert isinstance(s, pd.Series) and s.index.equals(DAY)


# --- engine ----------------------------------------------------------------------------


@pytest.mark.spec("PV-016")
def test_import_does_not_load_pvlib():
    code = (
        "import sys, kiozesim\n"
        "from kiozesim.plants.pv import PVPlant\n"
        "assert 'pvlib' not in sys.modules, 'pvlib imported eagerly'\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


@pytest.mark.spec("PV-016")
def test_missing_pvlib_explains_install(monkeypatch):
    for name in [m for m in sys.modules if m == "pvlib" or m.startswith("pvlib.")]:
        monkeypatch.delitem(sys.modules, name)  # as if never imported...
    monkeypatch.setitem(sys.modules, "pvlib", None)  # ...and not installed
    monkeypatch.delitem(sys.modules, "kiozesim.plants.pv._engine", raising=False)
    with pytest.raises(ImportError, match=r"kiozesim\[pv\]"):
        PVPlant(params()).simulate(const(DAY))


@needs_pvlib
@pytest.mark.spec("PV-019")
def test_model_choices_are_pinned(monkeypatch):
    from kiozesim.plants.pv import _engine

    mc = _engine.build_modelchain(params())
    assert (mc.transposition_model, mc.solar_position_method, mc.airmass_model) == (
        "perez",
        "nrel_numpy",
        "kastenyoung1989",
    )
    steps = ["aoi_model", "spectral_model", "temperature_model", "dc_model", "losses_model"]
    assert [getattr(mc, s).__name__ for s in steps + ["ac_model"]] == [
        "physical_aoi_loss",
        "no_spectral_loss",
        "sapm_temp",
        "pvwatts_dc",
        "pvwatts_losses",
        "pvwatts_inverter",
    ]
    calls = []
    real_erbs = _engine.erbs
    monkeypatch.setattr(_engine, "erbs", lambda *a, **k: calls.append(1) or real_erbs(*a, **k))
    PVPlant(params()).simulate(clear_sky(components=False))
    assert calls  # DNI/DHI estimated with Erbs


# --- validation ------------------------------------------------------------------------


@needs_pvlib
@pytest.mark.spec("PV-018")
def test_annual_yield_matches_pvgis_warsaw():
    (case,) = [c for c in discover() if c.id == "pv/warsaw_pvgis_annual"]
    run_case(case)
