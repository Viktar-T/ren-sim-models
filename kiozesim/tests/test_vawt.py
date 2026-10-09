"""VAWT plant, spec 0004."""

import subprocess
import sys
from importlib.resources import files
from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from kiozesim.plants.vawt import (
    VAWTDatasheet,
    VAWTInputs,
    VAWTOutput,
    VAWTParams,
    VAWTPlant,
    _air,
)
from kiozesim.timegrid import TimeGridError

needs_wpl = pytest.mark.skipif(find_spec("windpowerlib") is None, reason="needs the 'wind' extra")

# Made-up small turbines. Power curve: 0 below 3 m/s, rated 5 kW from 12 m/s, cut-out after 20 m/s.
BASE = {
    "manufacturer": "m",
    "model": "x",
    "rotor_type": "darrieus",
    "rotor_diameter_m": 3,
    "rotor_height_m": 4,
    "rated_power_kw": 5,
}
PC = BASE | {
    "method": "power_curve",
    "wind_speed_m_s": [3, 6, 9, 12, 20],
    "power_kw": [0, 1, 3, 5, 5],
}
GEOMETRY = BASE | {
    "method": "geometry",
    "cut_in_m_s": 3,
    "cut_out_m_s": 20,
    "drivetrain_efficiency_pct": 85,
    "control": "optimal_tsr",
    "rated_wind_speed_m_s": 12,
}
DARRIEUS = GEOMETRY | {
    "n_blades": 3,
    "chord_m": 0.2,
    "airfoil": "NACA0018",
    "blade_shape": "straight",
}
SAVONIUS = GEOMETRY | {"rotor_type": "savonius", "n_buckets": 2}
DAY = pd.date_range("2026-01-15", periods=24, freq="h", tz="UTC")


def params(ds: dict = PC, **kw: object) -> VAWTParams:
    base = {"name": "t", "datasheet": VAWTDatasheet(**ds), "hub_height_m": 12}
    return VAWTParams(**(base | kw))


def inputs(index: pd.DatetimeIndex = DAY, wind: object = 8.0, **kw: object) -> VAWTInputs:
    base = {"wind_speed_m_s": wind, "temp_air_c": 5.0, "pressure_hpa": 1000.0} | kw
    return VAWTInputs(**{k: pd.Series(v, index=index) for k, v in base.items() if v is not None})


def at_hub(**kw: object) -> VAWTParams:
    """Wind measured at hub height, standard air, no losses: the curve as published."""
    return params(wind_height_m=12, density_correction=False, losses_pct=0, **kw)


# --- parameters and inputs -------------------------------------------------------------


@pytest.mark.spec("VAWT-001")
def test_datasheet_fields():
    assert set(VAWTDatasheet.model_fields) == {
        "manufacturer",
        "model",
        "source",
        "method",
        "rotor_type",
        "rotor_diameter_m",
        "rotor_height_m",
        "rated_power_kw",
        "wind_speed_m_s",
        "power_kw",
        "cut_in_m_s",
        "cut_out_m_s",
        "drivetrain_efficiency_pct",
        "control",
        "rpm",
        "rated_wind_speed_m_s",
        "n_blades",
        "chord_m",
        "tip_chord_m",
        "airfoil",
        "blade_shape",
        "n_buckets",
    }
    for ds in (PC, DARRIEUS, SAVONIUS, PC | {"rotor_type": "savonius"}):
        VAWTDatasheet(**ds)
    fixed = DARRIEUS | {"control": "fixed_rpm", "rpm": 120}
    del fixed["rated_wind_speed_m_s"]
    VAWTDatasheet(**fixed)
    VAWTDatasheet(**PC | {"power_kw": [0, 1, 3, 5, 5.5]})  # 1.10 x rated is allowed
    VAWTDatasheet(**DARRIEUS | {"tip_chord_m": 0.1})  # tapered


@pytest.mark.spec("VAWT-001")
@pytest.mark.parametrize(
    ("ds", "change"),
    [
        # ranges
        (PC, {"rated_power_kw": 0}),
        (PC, {"rotor_diameter_m": -1}),
        (PC, {"rotor_height_m": float("inf")}),
        (PC, {"method": "magic"}),
        (PC, {"rotor_type": "eggbeater"}),
        (DARRIEUS, {"cut_in_m_s": -1}),
        (DARRIEUS, {"cut_out_m_s": 3}),  # not above cut-in
        (DARRIEUS, {"drivetrain_efficiency_pct": 0}),
        (DARRIEUS, {"drivetrain_efficiency_pct": 101}),
        (DARRIEUS, {"rated_wind_speed_m_s": 3}),  # not above cut-in
        (DARRIEUS, {"rated_wind_speed_m_s": 20}),  # not below cut-out
        (DARRIEUS, {"n_blades": 0}),
        (DARRIEUS, {"n_blades": 7}),
        (DARRIEUS, {"chord_m": 0}),
        (DARRIEUS, {"airfoil": "NACA4412"}),
        (DARRIEUS, {"airfoil": "NACA0012"}),  # no full table bundled
        (DARRIEUS, {"tip_chord_m": 0}),
        (SAVONIUS, {"tip_chord_m": 0.1}),
        (PC, {"tip_chord_m": 0.1}),
        (DARRIEUS, {"blade_shape": "helical"}),
        (SAVONIUS, {"n_buckets": 3}),  # no open 3-scoop data
        # power curve as HAWT
        (PC, {"power_kw": [0, 1, 3, 5]}),  # length differs
        (PC, {"wind_speed_m_s": [3], "power_kw": [0]}),  # one point
        (PC, {"wind_speed_m_s": [-1, 6, 9, 12, 20]}),
        (PC, {"wind_speed_m_s": [3, 6, 6, 12, 20]}),
        (PC, {"power_kw": [0, -1, 3, 5, 5]}),
        (PC, {"power_kw": [0, 1, 3, 5, 5.6]}),  # above 1.10 x rated
        # fields of the other method or family
        (PC, {"cut_in_m_s": 3}),
        (PC, {"n_blades": 3}),
        (DARRIEUS, {"wind_speed_m_s": [3, 6], "power_kw": [0, 1]}),
        (DARRIEUS, {"n_buckets": 2}),
        (SAVONIUS, {"chord_m": 0.2}),
        # speed control fields
        (DARRIEUS, {"rpm": 120}),  # rpm without fixed_rpm
        (DARRIEUS, {"control": "fixed_rpm"}),  # fixed_rpm without rpm, with rated wind
        (DARRIEUS, {"colour": "white"}),
    ],
)
def test_datasheet_rejects(ds, change):
    with pytest.raises(ValidationError):
        VAWTDatasheet(**ds | change)


@pytest.mark.spec("VAWT-001")
@pytest.mark.parametrize(
    ("ds", "field"),
    [
        (PC, "power_kw"),
        (DARRIEUS, "chord_m"),
        (DARRIEUS, "control"),
        (DARRIEUS, "rated_wind_speed_m_s"),
        (SAVONIUS, "n_buckets"),
    ],
)
def test_datasheet_missing_field_named(ds, field):
    with pytest.raises(ValidationError, match=field):
        VAWTDatasheet(**{k: v for k, v in ds.items() if k != field})


@pytest.mark.spec("VAWT-002")
def test_params_fields_and_defaults():
    p = params()
    assert set(VAWTParams.model_fields) == {
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
    params(losses_pct=0, roughness_length_m=9.99)  # boundaries
    params(hub_height_m=2.01)


@pytest.mark.spec("VAWT-002")
@pytest.mark.parametrize(
    "change",
    [
        {"hub_height_m": 0},
        {"hub_height_m": 2},  # rotor (4 m tall) would touch the ground
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


@pytest.mark.spec("VAWT-003")
def test_inputs_wind_only_and_checks():
    VAWTInputs(wind_speed_m_s=pd.Series(5.0, index=DAY))
    VAWTInputs.from_frame(pd.DataFrame({"wind_speed_m_s": 5.0}, index=DAY))
    inputs(temp_air_c=-20.0)  # cold is fine
    with pytest.raises(ValidationError):
        VAWTInputs(temp_air_c=pd.Series(5.0, index=DAY))  # wind missing
    with pytest.raises(ValidationError, match="wind_speed_m_s"):
        inputs(wind=-1.0)
    with pytest.raises(ValidationError, match="pressure_hpa"):
        inputs(pressure_hpa=0.0)
    with pytest.raises(ValidationError, match="temp_air_c"):
        inputs(temp_air_c=float("inf"))


@pytest.mark.spec("VAWT-004")
@pytest.mark.parametrize("missing", ["temp_air_c", "pressure_hpa"])
def test_density_correction_needs_temp_and_pressure(missing):
    with pytest.raises(ValueError, match=missing):
        VAWTPlant(params()).simulate(inputs(**{missing: None}))


@pytest.mark.spec("VAWT-004")
def test_without_density_correction_temp_and_pressure_ignored():
    plant = VAWTPlant(params(density_correction=False))
    bare = plant.simulate(inputs(temp_air_c=None, pressure_hpa=None))
    given = plant.simulate(inputs(temp_air_c=-30.0, pressure_hpa=700.0))
    pd.testing.assert_series_equal(bare.power_kw, given.power_kw)
    assert (bare.air_density_kg_m3 == 1.225).all()


@pytest.mark.spec("VAWT-005")
def test_step_limit():
    plant = VAWTPlant(params())
    with pytest.raises(TimeGridError, match="1 h"):
        plant.simulate(inputs(pd.date_range("2026-01-01", periods=4, freq="2h", tz="UTC")))
    for freq in ("1h", "10min", "1min"):
        plant.simulate(inputs(pd.date_range("2026-01-01", periods=4, freq=freq, tz="UTC")))


# --- model -----------------------------------------------------------------------------


@pytest.mark.spec("VAWT-014")
def test_wind_at_hub_height_unchanged():
    wind = pd.Series(np.linspace(0, 30, 24), index=DAY)
    out = VAWTPlant(params(wind_height_m=12)).simulate(inputs(wind=wind.to_numpy()))
    pd.testing.assert_series_equal(out.wind_speed_hub_m_s, wind, check_names=False)


@pytest.mark.spec("VAWT-014")
def test_wind_and_density_hand_values():
    # 5 m/s at 10 m over farmland (z0 = 0.1) is 5 × ln(1000) / ln(100) = 7.5 m/s at 100 m.
    v = _air.wind_at_hub(pd.Series([5.0]), 10, 100, 0.1)
    assert v.iloc[0] == pytest.approx(7.5)
    # 15 °C and 1013.25 hPa at the ground, density at 0 m: the standard 1.225 kg/m³ (±0.1 %).
    rho = _air.density_at_hub(pd.Series([15.0]), 0, pd.Series([1013.25]), 0)
    assert rho.iloc[0] == pytest.approx(1.225, rel=1e-3)


@needs_wpl
@pytest.mark.spec("VAWT-014")
def test_wind_and_density_as_windpowerlib():
    from windpowerlib.density import barometric
    from windpowerlib.temperature import linear_gradient
    from windpowerlib.wind_speed import logarithmic_profile

    rng = np.random.default_rng(0)
    wind = pd.Series(rng.uniform(0, 25, 50))
    temp = pd.Series(rng.uniform(-25, 35, 50))
    pres = pd.Series(rng.uniform(950, 1040, 50))
    pd.testing.assert_series_equal(
        _air.wind_at_hub(wind, 10, 18, 0.3), logarithmic_profile(wind, 10, 18, 0.3, 0)
    )
    t_hub = linear_gradient(temp + 273.15, 2, 18)
    pd.testing.assert_series_equal(
        _air.density_at_hub(temp, 2, pres, 18), barometric(pres * 100, 0, 18, t_hub)
    )


@pytest.mark.spec("VAWT-015")
def test_output_shape_power_curve():
    out = VAWTPlant(params()).simulate(inputs())
    assert isinstance(out, VAWTOutput)
    for s in (out.power_kw, out.wind_speed_hub_m_s, out.air_density_kg_m3):
        assert s.index.equals(DAY)
    assert out.tsr is None and out.cp is None


@pytest.mark.spec("VAWT-008")
def test_power_curve_has_no_cp_curve():
    assert VAWTPlant(params()).cp_curve() is None


@pytest.mark.spec("VAWT-016")
def test_import_does_not_build_curves():
    code = (
        "import sys, kiozesim\n"
        "from kiozesim.plants.vawt import VAWTPlant\n"
        "loaded = [m for m in sys.modules if m.startswith('kiozesim.plants.vawt._')"
        " and m != 'kiozesim.plants.vawt._air']\n"
        "assert not loaded, loaded\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


@pytest.mark.spec("VAWT-020")
def test_power_curve_zero_outside_and_scaling():
    wind = np.array([0, 2.9, 3, 7.5, 20, 20.1, 30] + [8.0] * 17)
    out = VAWTPlant(at_hub()).simulate(inputs(wind=wind)).power_kw.to_numpy()
    assert out[:7] == pytest.approx([0, 0, 0, 2, 5, 0, 0])
    # n_turbines and losses
    p = at_hub(n_turbines=3).model_copy(update={"losses_pct": 20})
    out = VAWTPlant(p).simulate(inputs(wind=7.5)).power_kw
    np.testing.assert_allclose(out, 3 * 2 * 0.8)


@pytest.mark.spec("VAWT-020")
def test_power_curve_density_scaling_and_cap():
    p = params(wind_height_m=12, losses_pct=0)
    # 1 kW at 6 m/s scales with density; 5 kW at 15 m/s may not exceed the curve's maximum.
    ts = inputs(wind=6.0, temp_air_c=-20.0, pressure_hpa=1030.0)
    out = VAWTPlant(p).simulate(ts)
    np.testing.assert_allclose(out.power_kw, out.air_density_kg_m3 / 1.225)
    assert (out.air_density_kg_m3 > 1.3).all()  # cold, heavy air
    out = VAWTPlant(p).simulate(inputs(wind=15.0, temp_air_c=-20.0, pressure_hpa=1030.0))
    assert (out.power_kw == 5).all()
    out = VAWTPlant(p).simulate(inputs(wind=15.0, temp_air_c=35.0, pressure_hpa=950.0))
    assert (out.power_kw < 5).all()  # warm, thin air


@pytest.mark.spec("VAWT-021")
def test_power_curve_reproduced():
    speeds, powers = PC["wind_speed_m_s"], PC["power_kw"]
    plant = VAWTPlant(at_hub())
    index = DAY[: len(speeds)]
    out = plant.simulate(inputs(index, wind=speeds)).power_kw.to_numpy()
    assert out.tolist() == powers
    mids = [(a + b) / 2 for a, b in zip(speeds, speeds[1:], strict=False)]
    out = plant.simulate(inputs(DAY[: len(mids)], wind=mids)).power_kw.to_numpy()
    assert out == pytest.approx([(a + b) / 2 for a, b in zip(powers, powers[1:], strict=False)])


# --- geometry: Savonius ------------------------------------------------------------------

ZEPHYR = Path(__file__).parent / "golden" / "vawt" / "zephyr" / "U6_characteristics.txt"
SAV_FIXED = {k: v for k, v in SAVONIUS.items() if k != "rated_wind_speed_m_s"} | {
    "control": "fixed_rpm",
    "rpm": 150,
}


def savonius(ds: dict = SAVONIUS, **kw: object) -> VAWTPlant:
    """Savonius at hub height, standard air, no losses unless overridden."""
    base = {"wind_height_m": 12, "density_correction": False, "losses_pct": 0}
    return VAWTPlant(params(ds, **(base | kw)))


@pytest.mark.spec("VAWT-007")
@pytest.mark.spec("VAWT-010")
@pytest.mark.spec("VAWT-019")
def test_savonius_curve_is_zephyr_unchanged():
    raw = pd.read_csv(ZEPHYR, sep="\t", index_col=0).dropna(how="all")
    assert raw.loc["L8"].equals(raw.loc["L7"])  # the duplicate that is left out
    expected = raw.drop("L8").sort_values("TSR")
    curve = savonius().cp_curve()
    assert list(curve.columns) == ["tsr", "cp"]
    np.testing.assert_array_equal(curve["tsr"], expected["TSR"])
    np.testing.assert_array_equal(curve["cp"], expected["Cp"])
    bundled = files("kiozesim") / "datasheets" / "vawt" / "_data" / "savonius_2.csv"
    assert "doi:10.5281/zenodo.8328824" in bundled.read_text()  # source recorded


@pytest.mark.spec("VAWT-008")
def test_curve_built_once(monkeypatch):
    from kiozesim.plants.vawt import _savonius

    calls = []
    real = _savonius.curve
    monkeypatch.setattr(_savonius, "curve", lambda n: calls.append(n) or real(n))
    plant = savonius()
    plant.simulate(inputs(wind=np.linspace(0, 25, 24)))
    plant.simulate(inputs(wind=7.0))
    plant.cp_curve()
    assert calls == [2]
    got = plant.cp_curve()
    got.loc[0, "cp"] = 99  # a copy: callers cannot corrupt the cached curve
    assert plant.cp_curve()["cp"].max() < 1


@pytest.mark.spec("VAWT-009")
@pytest.mark.parametrize("bad", [-0.01, 0.6])
def test_curve_outside_betz_rejected(monkeypatch, bad):
    from kiozesim.plants.vawt import _savonius

    monkeypatch.setattr(
        _savonius, "curve", lambda n: pd.DataFrame({"tsr": [0.5, 1.0], "cp": [0.1, bad]})
    )
    with pytest.raises(ValueError, match="Betz"):
        savonius().cp_curve()


@pytest.mark.spec("VAWT-011")
def test_swept_area():
    assert savonius().swept_area_m2() == 3 * 4
    curved = DARRIEUS | {"blade_shape": "troposkien"}
    assert VAWTPlant(params(DARRIEUS)).swept_area_m2() == 3 * 4
    assert VAWTPlant(params(curved)).swept_area_m2() == pytest.approx(2 / 3 * 3 * 4)


@pytest.mark.spec("VAWT-012")
def test_tsr_optimal_and_fixed():
    best = savonius().cp_curve().set_index("tsr")["cp"].idxmax()
    out = savonius().simulate(inputs(wind=np.linspace(0, 25, 24)))
    assert (out.tsr == best).all()
    assert out.cp.max() == pytest.approx(0.158123569)
    # fixed 150 rpm, radius 1.5 m: tip speed 23.56 m/s; at 10 m/s λ = 2.356, beyond the curve
    wind = np.array([0.0, 10.0, 25.0, 40.0] + [5.0] * 20)
    out = savonius(SAV_FIXED, hub_height_m=12).simulate(inputs(wind=wind))
    tip = 150 * 2 * np.pi / 60 * 1.5
    np.testing.assert_allclose(out.tsr[:4], [0.0, tip / 10, tip / 25, tip / 40])
    assert out.cp.iloc[1] == 0  # outside the measured λ range


@pytest.mark.spec("VAWT-013")
@pytest.mark.spec("VAWT-019")
def test_savonius_power_hand_calculation():
    # λ = 0.739732156 (best), Cp = 0.158123569, A = 3 m x 4 m, ρ = 1.225, v = 8 m/s, η = 85 %
    hand_kw = 0.158123569 * 0.5 * 1.225 * 12 * 8**3 / 1000 * 0.85
    out = savonius().simulate(inputs(wind=8.0))
    assert out.power_kw.iloc[0] == pytest.approx(hand_kw, rel=1e-3)
    # n_turbines and losses
    out = savonius(n_turbines=2, losses_pct=10).simulate(inputs(wind=8.0))
    assert out.power_kw.iloc[0] == pytest.approx(2 * hand_kw * 0.9, rel=1e-3)


@pytest.mark.spec("VAWT-013")
def test_cut_in_cut_out_and_rated_cap():
    wind = np.array([2.9, 3.0, 20.0, 20.1] + [8.0] * 20)
    kw = savonius().simulate(inputs(wind=wind)).power_kw.to_numpy()
    assert kw[0] == 0 and kw[1] > 0 and kw[3] == 0
    assert kw[2] == 5  # capped at rated_power_kw
    kw = savonius(density_correction=True).simulate(inputs(wind=8.0, temp_air_c=-20.0))
    assert kw.power_kw.iloc[0] > savonius().simulate(inputs(wind=8.0)).power_kw.iloc[0]


@pytest.mark.spec("VAWT-015")
def test_output_shape_geometry():
    out = savonius().simulate(inputs())
    for s in (out.power_kw, out.wind_speed_hub_m_s, out.air_density_kg_m3, out.tsr, out.cp):
        assert isinstance(s, pd.Series) and s.index.equals(DAY)


# --- geometry: Darrieus ------------------------------------------------------------------

GOLDEN = Path(__file__).parent / "golden" / "vawt"
FT, INCH = 0.3048, 0.0254


def darrieus_plant(**ds: object) -> VAWTPlant:
    return VAWTPlant(params(DARRIEUS | ds, hub_height_m=50))


def measured_peak(tsr: np.ndarray, cp: np.ndarray) -> tuple[float, float]:
    """Highest measured Cp, and the top of a parabola through points >= 85 % of it (spec)."""
    top = cp >= 0.85 * cp.max()
    a, b, _ = np.polyfit(tsr[top], cp[top], 2)
    return float(cp.max()), float(-b / (2 * a))


def computed_peak(plant: VAWTPlant) -> tuple[float, float]:
    curve = plant.cp_curve()
    i = curve["cp"].idxmax()
    return float(curve.loc[i, "cp"]), float(curve.loc[i, "tsr"])


@pytest.mark.spec("VAWT-010")
@pytest.mark.parametrize(
    ("airfoil", "re", "alpha", "cl", "cd"),
    [  # read off the printed SAND80-2114 tables (page 27: Table 3; page 47: Table 4)
        ("naca0015", 10000, 7, -0.1517, 0.0510),
        ("naca0015", 10000, 50, 1.0200, 1.2150),
        ("naca0015", 10000, 120, -0.6700, 1.4650),
        ("naca0018", 700000, 7, 0.7291, 0.0123),
        ("naca0018", 700000, 13, 1.0289, 0.0223),
        ("naca0018", 700000, 15, 0.9938, 0.1020),
        ("naca0018", 700000, 25, 0.9326, 0.4050),
    ],
)
def test_airfoil_tables_match_print(airfoil, re, alpha, cl, cd):
    table = files("kiozesim") / "datasheets" / "vawt" / "_data" / f"{airfoil}.csv"
    with table.open() as f:
        t = pd.read_csv(f, comment="#")
    row = t[(t["re"] == re) & (t["alpha_deg"] == alpha)]
    assert row[["cl", "cd"]].to_numpy().tolist() == [[cl, cd]]


@pytest.mark.spec("VAWT-010")
def test_airfoil_tables_complete_with_source():
    expected_re = {
        "naca0015": [1e4, 2e4, 4e4, 8e4, 1.6e5, 3.6e5, 7e5, 1e6, 2e6, 5e6, 1e7],
        "naca0018": [1e4, 2e4, 4e4, 8e4, 1.6e5, 3.6e5, 7e5, 1e6, 2e6, 5e6],
        "naca0021": [1e4, 2e4, 4e4, 8e4, 1.6e5, 3.6e5, 7e5, 1e6, 2e6, 5e6],
    }
    for airfoil, res in expected_re.items():
        table = files("kiozesim") / "datasheets" / "vawt" / "_data" / f"{airfoil}.csv"
        text = table.read_text()
        assert "SAND80-2114" in text and "BSD-3-Clause" in text
        with table.open() as f:
            t = pd.read_csv(f, comment="#")
        assert sorted(t["re"].unique()) == res
        for _, block in t.groupby("re"):
            assert block["alpha_deg"].min() == 0 and block["alpha_deg"].max() == 180


@pytest.mark.spec("VAWT-006")
def test_polar_symmetry_and_reynolds_interpolation():
    from kiozesim.plants.vawt import _dmst

    pol = _dmst.polar("NACA0018")
    a = np.radians(np.array([7.0, -7.0]))
    cl, cd = pol.coefficients(a, np.array([7e5, 7e5]))
    np.testing.assert_allclose(cl, [0.7291, -0.7291])
    np.testing.assert_allclose(cd, [0.0123, 0.0123])
    # halfway between Re 7e5 and 1e6 is the mean of the two tables
    lo, _ = pol.coefficients(a[:1], np.array([7e5]))
    hi, _ = pol.coefficients(a[:1], np.array([1e6]))
    mid, _ = pol.coefficients(a[:1], np.array([8.5e5]))
    np.testing.assert_allclose(mid, (lo + hi) / 2)
    # beyond the tables: the nearest table
    np.testing.assert_allclose(
        pol.coefficients(a[:1], np.array([1e9]))[0], pol.coefficients(a[:1], np.array([5e6]))[0]
    )


@pytest.mark.spec("VAWT-006")
def test_dmst_converged_and_responds_to_geometry():
    from kiozesim.plants.vawt import _dmst

    rotor = _dmst.Rotor(3, 1.5, 4, 0.2, 0.2, "straight", "NACA0018")
    tsr = np.array([2.0, 3.0, 4.0, 5.0])
    v = np.full(4, 10.0)
    base = _dmst.cp(rotor, tsr, v)
    fine = {"N_LAYERS": 40, "N_TUBES": 72}
    with pytest.MonkeyPatch.context() as mp:
        for k, val in fine.items():
            mp.setattr(_dmst, k, val)
        np.testing.assert_allclose(_dmst.cp(rotor, tsr, v), base, atol=2e-3)
    # tapering and curving change the answer; thicker airfoils and Reynolds numbers are used
    from dataclasses import replace

    for change in ({"tip_chord_m": 0.1}, {"shape": "troposkien"}, {"airfoil": "NACA0021"}):
        assert not np.allclose(_dmst.cp(replace(rotor, **change), tsr, v), base)
    assert not np.allclose(_dmst.cp(rotor, tsr, v / 10), base)


@pytest.mark.spec("VAWT-009")
def test_darrieus_curve_trimmed_to_positive_stretch():
    from kiozesim.plants.vawt import _dmst
    from kiozesim.plants.vawt.plant import TSR_GRID

    plant = darrieus_plant()
    curve = plant.cp_curve()
    assert (curve["cp"] > 0).all() and curve["cp"].max() < 16 / 27
    full = _dmst.cp(
        _dmst.Rotor(3, 1.5, 4, 0.2, 0.2, "straight", "NACA0018"),
        TSR_GRID,
        np.full_like(TSR_GRID, 12.0),
    )
    lo, hi = curve["tsr"].iloc[0], curve["tsr"].iloc[-1]
    assert lo > TSR_GRID[0] and hi < TSR_GRID[-1]  # both ends were negative and cut off
    i_lo, i_hi = np.searchsorted(TSR_GRID, [lo, hi])
    assert full[i_lo - 1] <= 0 and full[i_hi + 1] <= 0
    np.testing.assert_allclose(curve["cp"], full[i_lo : i_hi + 1])
    # outside the curve the rotor makes nothing
    out = VAWTPlant(
        params(
            DARRIEUS | {"control": "fixed_rpm", "rpm": 2000, "rated_wind_speed_m_s": None},
            hub_height_m=50,
            wind_height_m=50,
        )
    ).simulate(inputs(wind=5.0))
    assert (out.power_kw == 0).all() and (out.cp == 0).all()


@pytest.mark.spec("VAWT-009")
def test_darrieus_without_power_rejected(monkeypatch):
    from kiozesim.plants.vawt import _dmst

    monkeypatch.setattr(_dmst, "cp", lambda rotor, tsr, v: -np.ones_like(tsr))
    with pytest.raises(ValueError, match="no power"):
        darrieus_plant().cp_curve()


@pytest.mark.spec("VAWT-012")
def test_darrieus_fixed_rpm_sets_reynolds_per_tsr(monkeypatch):
    from kiozesim.plants.vawt import _dmst
    from kiozesim.plants.vawt.plant import TSR_GRID

    seen = {}
    real = _dmst.cp
    monkeypatch.setattr(_dmst, "cp", lambda r, t, v: seen.update(v=v) or real(r, t, v))
    ds = {k: v for k, v in DARRIEUS.items() if k != "rated_wind_speed_m_s"}
    VAWTPlant(params(ds | {"control": "fixed_rpm", "rpm": 120}, hub_height_m=50)).cp_curve()
    np.testing.assert_allclose(seen["v"], 120 * 2 * np.pi / 60 * 1.5 / TSR_GRID)
    darrieus_plant().cp_curve()
    assert (seen["v"] == 12).all()  # optimal_tsr: rated wind speed for every λ


@pytest.mark.spec("VAWT-013")
def test_darrieus_power_from_curve():
    plant = darrieus_plant()
    cp_best, _ = computed_peak(plant)
    out = VAWTPlant(
        params(DARRIEUS, hub_height_m=50, wind_height_m=50, density_correction=False, losses_pct=0)
    ).simulate(inputs(wind=6.0))
    hand_kw = cp_best * 0.5 * 1.225 * 12 * 6**3 / 1000 * 0.85
    np.testing.assert_allclose(out.power_kw, hand_kw)


@pytest.mark.spec("VAWT-017")
@pytest.mark.parametrize("case", ["rm2", "sandia_17m", "zephyr"])
def test_golden_cases_have_provenance(case):
    import yaml

    src = yaml.safe_load((GOLDEN / case / "source.yaml").read_text())
    assert {"citation", "licence", "rotor", "fetched"} <= set(src)
    assert any(p.suffix in {".csv", ".txt"} for p in (GOLDEN / case).iterdir())


@pytest.mark.spec("VAWT-018")
def test_validation_rm2():
    data = pd.read_csv(GOLDEN / "rm2" / "Perf-1.2.csv")
    cp_meas, tsr_meas = measured_peak(data["mean_tsr"].to_numpy(), data["mean_cp"].to_numpy())
    ds = {
        "manufacturer": "UNH",
        "model": "RM2 1:6",
        "method": "geometry",
        "rotor_type": "darrieus",
        "rotor_diameter_m": 1.075,
        "rotor_height_m": 0.8067,
        "rated_power_kw": 1,
        "cut_in_m_s": 0.1,
        "cut_out_m_s": 40,
        "drivetrain_efficiency_pct": 100,
        "control": "optimal_tsr",
        "rated_wind_speed_m_s": 1.2 * 1.46e-5 / 1.0e-6,
        "n_blades": 3,
        "chord_m": 0.06667,
        "tip_chord_m": 0.04,
        "airfoil": "NACA0021",
        "blade_shape": "straight",
    }
    cp_model, tsr_model = computed_peak(VAWTPlant(params(ds, hub_height_m=2)))
    print(
        f"RM2 measured {cp_meas:.3f} at λ {tsr_meas:.2f}, model {cp_model:.3f} at λ {tsr_model:.2f}"
    )
    assert cp_model == pytest.approx(cp_meas, rel=0.25)
    assert tsr_model == pytest.approx(tsr_meas, abs=1.0)


@pytest.mark.spec("VAWT-022")
def test_validation_sandia_17m():
    data = pd.read_csv(GOLDEN / "sandia_17m" / "measured.csv")
    assert len(data) == 30
    cp_meas, tsr_meas = measured_peak(data["tsr"].to_numpy(), data["cp"].to_numpy())
    ds = {
        "manufacturer": "Sandia",
        "model": "17-m",
        "method": "geometry",
        "rotor_type": "darrieus",
        "rotor_diameter_m": 54.9 * FT,
        "rotor_height_m": 55.8 * FT,
        "rated_power_kw": 60,
        "cut_in_m_s": 0.1,
        "cut_out_m_s": 40,
        "drivetrain_efficiency_pct": 100,
        "control": "fixed_rpm",
        "rpm": 46.7,
        "n_blades": 2,
        "chord_m": 24 * INCH,
        "airfoil": "NACA0015",
        "blade_shape": "troposkien",
    }
    cp_model, tsr_model = computed_peak(VAWTPlant(params(ds, hub_height_m=30)))
    print(
        f"17-m measured {cp_meas:.3f} at λ {tsr_meas:.2f},"
        f" model {cp_model:.3f} at λ {tsr_model:.2f}"
    )
    assert cp_model == pytest.approx(cp_meas, rel=0.15)
    assert tsr_model == pytest.approx(tsr_meas, abs=0.5)


# --- bundled datasheets --------------------------------------------------------------------


@pytest.mark.spec("VAWT-023")
def test_shelf_ships_examples_and_real_products():
    assert VAWTDatasheet.available() == [
        "example_darrieus_h_rotor_3_kw",
        "example_savonius_0_4_kw",
        "hi_vawt_technology_corp_ds3000",
        "mariah_power_windspire",
    ]
    h = VAWTDatasheet.bundled("example_darrieus_h_rotor_3_kw")
    assert (h.rotor_type, h.rotor_diameter_m, h.rotor_height_m, h.rated_power_kw) == (
        "darrieus",
        3.0,
        3.5,
        3.0,
    )
    assert (h.cut_in_m_s, h.cut_out_m_s, h.drivetrain_efficiency_pct) == (3.0, 20.0, 85)
    assert (h.control, h.rated_wind_speed_m_s) == ("optimal_tsr", 10.5)
    assert (h.n_blades, h.chord_m, h.airfoil, h.blade_shape) == (3, 0.10, "NACA0018", "straight")
    s = VAWTDatasheet.bundled("example_savonius_0_4_kw")
    assert (s.rotor_type, s.rotor_diameter_m, s.rotor_height_m, s.rated_power_kw) == (
        "savonius",
        1.2,
        2.4,
        0.4,
    )
    assert (s.cut_in_m_s, s.cut_out_m_s, s.drivetrain_efficiency_pct) == (2.5, 25.0, 85)
    assert (s.control, s.rated_wind_speed_m_s, s.n_buckets) == ("optimal_tsr", 12.0, 2)
    w = VAWTDatasheet.bundled("mariah_power_windspire")
    assert "NREL/TP-500-46192" in w.source and w.method == "power_curve"
    assert (w.wind_speed_m_s[-1], w.power_kw[-1], max(w.power_kw)) == (13.47, 0.99, 1.09)
    d = VAWTDatasheet.bundled("hi_vawt_technology_corp_ds3000")
    assert "SWCC-18-02" in d.source and d.rated_power_kw == 1.4
    assert d.power_kw[d.wind_speed_m_s.index(10.50)] == 1.4356  # 1435.6 W in the report


@pytest.mark.spec("VAWT-023")
@pytest.mark.parametrize("name", VAWTDatasheet.available())
def test_every_bundled_vawt_runs(name):
    out = VAWTPlant(
        VAWTParams(name="t", datasheet=VAWTDatasheet.bundled(name), hub_height_m=10)
    ).simulate(inputs(wind=np.linspace(0, 15, 24)))
    assert out.power_kw.max() > 0
