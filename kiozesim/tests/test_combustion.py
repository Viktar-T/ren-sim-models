"""Combustion plant (gas engines and boilers), specs 0015, 0006 (bundled boilers), 0019."""

import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from kiozesim.plants import REGISTRY
from kiozesim.plants.combustion import (
    CombustionDatasheet,
    CombustionInputs,
    CombustionOutput,
    CombustionParams,
    CombustionPlant,
)

SHEET = {
    "manufacturer": "m",
    "model": "x",
    "rated_electrical_kw": 500,
    "electrical_efficiency": 0.40,
    "thermal_efficiency": 0.45,
}
BOILER = {
    "manufacturer": "m",
    "model": "b",
    "rated_thermal_kw": 300,
    "electrical_efficiency": 0,
    "thermal_efficiency": 0.92,
}
DAY = pd.date_range("2026-01-15", periods=24, freq="h", tz="UTC")
FUEL_MAX = 500 / 0.40  # 1250 kW


def plant(availability: float = 1.0, **ds: object) -> CombustionPlant:
    sheet = CombustionDatasheet(**(SHEET | ds))
    return CombustionPlant(CombustionParams(name="e", datasheet=sheet, availability=availability))


def fuel(values: object, index: pd.DatetimeIndex = DAY) -> CombustionInputs:
    return CombustionInputs(fuel_kw=pd.Series(values, index=index, dtype=float))


@pytest.mark.spec("CHP-001")
def test_datasheet_fields():
    assert set(CombustionDatasheet.model_fields) == {
        "manufacturer",
        "model",
        "source",
        "rated_electrical_kw",
        "rated_thermal_kw",
        "electrical_efficiency",
        "thermal_efficiency",
    }
    assert CombustionDatasheet.shelf == "combustion"


@pytest.mark.spec("CHP-001")
@pytest.mark.parametrize(
    "bad",
    [
        {"rated_electrical_kw": 0},
        {"electrical_efficiency": 0},  # rated by electricity, makes none
        {"rated_electrical_kw": None},  # no rating
        {"rated_thermal_kw": 500},  # two ratings
        {"electrical_efficiency": 1},
        {"electrical_efficiency": 40},  # percent instead of a fraction
        {"thermal_efficiency": -0.1},
        {"thermal_efficiency": 1},
        {"electrical_efficiency": 0.5, "thermal_efficiency": 0.55},  # sum > 1
        {"rated_electrical_kw": float("nan")},
        {"extra": 1},
    ],
)
def test_datasheet_rejects(bad):
    with pytest.raises(ValidationError):
        CombustionDatasheet(**(SHEET | bad))


@pytest.mark.spec("CHP-001")
def test_boiler_datasheet_rated_by_heat():
    boiler = CombustionDatasheet(**BOILER)
    assert boiler.fuel_max_kw == pytest.approx(300 / 0.92)
    with pytest.raises(ValidationError):
        CombustionDatasheet(**(BOILER | {"thermal_efficiency": 0}))


@pytest.mark.spec("CHP-002")
def test_params_fields_and_default():
    assert set(CombustionParams.model_fields) == {"name", "datasheet", "availability"}
    p = CombustionParams(name="e", datasheet=CombustionDatasheet(**SHEET))
    assert p.availability == 1.0


@pytest.mark.spec("CHP-002")
@pytest.mark.parametrize("bad", [{"availability": -0.1}, {"availability": 1.1}, {"x": 1}])
def test_params_rejects(bad):
    with pytest.raises(ValidationError):
        CombustionParams(**({"name": "e", "datasheet": CombustionDatasheet(**SHEET)} | bad))


@pytest.mark.spec("CHP-003")
def test_inputs_require_fuel():
    with pytest.raises(ValidationError):
        CombustionInputs()  # type: ignore[call-arg]


@pytest.mark.spec("CHP-003")
def test_inputs_reject_negative_fuel():
    with pytest.raises(ValidationError, match="fuel_kw"):
        fuel([-1.0] + [0.0] * 23)


@pytest.mark.spec("CHP-004")
def test_equations_below_and_above_full_load():
    fuel_kw = np.r_[np.full(12, 1000.0), np.full(12, 2000.0)]
    out = plant(availability=0.9).simulate(fuel(fuel_kw))
    burned = 0.9 * np.minimum(fuel_kw, FUEL_MAX)
    np.testing.assert_allclose(out.power_kw, burned * 0.40)
    np.testing.assert_allclose(out.heat_kw, burned * 0.45)
    np.testing.assert_allclose(out.fuel_kw, fuel_kw - burned)
    np.testing.assert_allclose(out.power_kw.iloc[-1], 450.0)  # never above rated × availability


@pytest.mark.spec("CHP-004")
def test_full_availability_no_fuel_left_below_full_load():
    out = plant().simulate(fuel(1000.0))
    np.testing.assert_allclose(out.power_kw, 400.0)
    np.testing.assert_allclose(out.fuel_kw, 0.0)


@pytest.mark.spec("CHP-004")
def test_boiler_makes_heat_only():
    boiler = CombustionPlant(
        CombustionParams(name="b", datasheet=CombustionDatasheet(**BOILER), availability=0.98)
    )
    out = boiler.simulate(fuel(500.0))
    burned = 0.98 * 300 / 0.92
    np.testing.assert_allclose(out.power_kw, 0.0)
    np.testing.assert_allclose(out.heat_kw, burned * 0.92)
    np.testing.assert_allclose(out.fuel_kw, 500.0 - burned)


@pytest.mark.spec("CHP-005")
def test_output_series_on_input_index():
    out = plant().simulate(fuel(1000.0))
    assert isinstance(out, CombustionOutput)
    for s in (out.power_kw, out.heat_kw, out.fuel_kw):
        assert isinstance(s, pd.Series) and s.index.equals(DAY)
    assert (out.power_kw.name, out.heat_kw.name, out.fuel_kw.name) == (
        "power_kw",
        "heat_kw",
        "fuel_kw",
    )


@pytest.mark.spec("CHP-006")
def test_zero_fuel_or_zero_availability():
    for out in (plant().simulate(fuel(0.0)), plant(availability=0).simulate(fuel(1000.0))):
        assert (out.power_kw == 0).all() and (out.heat_kw == 0).all()


@pytest.mark.spec("CHP-007")
def test_no_extra_dependency():
    code = (
        "import sys, pandas as pd\n"
        "sys.modules['pvlib'] = None; sys.modules['windpowerlib'] = None\n"
        "from kiozesim.plants.combustion import (\n"
        "    CombustionDatasheet, CombustionInputs, CombustionParams, CombustionPlant)\n"
        "ds = CombustionDatasheet(manufacturer='m', model='x', rated_electrical_kw=1,"
        " electrical_efficiency=0.4, thermal_efficiency=0.4)\n"
        "i = pd.date_range('2026-01-01', periods=2, freq='h', tz='UTC')\n"
        "CombustionPlant(CombustionParams(name='e', datasheet=ds)).simulate("
        "CombustionInputs(fuel_kw=pd.Series(1.0, index=i)))\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


@pytest.mark.spec("CHP-008")
def test_registered_as_combustion():
    assert REGISTRY["combustion"] is CombustionPlant
    assert not {"biogas", "chp", "boiler"} & set(REGISTRY)


@pytest.mark.spec("CHP-009")
def test_shelf_ships_spec_units():
    expected = {
        "tedom_cento_100_biogas": (106, 0.366, 0.490),
        "tedom_cento_200_biogas": (200, 0.391, 0.479),
        "tedom_flexi_530_biogas": (528, 0.402, 0.445),
    }
    assert set(expected) <= set(CombustionDatasheet.available())
    for name, values in expected.items():
        d = CombustionDatasheet.bundled(name)
        assert (d.rated_electrical_kw, d.electrical_efficiency, d.thermal_efficiency) == values
        assert d.rated_thermal_kw is None


@pytest.mark.spec("BOIL-012")
@pytest.mark.spec("CHP-009")
def test_shelf_ships_spec_boilers():
    expected = {"ici_caldaie_rex_15": 150, "ici_caldaie_rex_30": 300, "ici_caldaie_rex_62": 620}
    assert set(CombustionDatasheet.available()) == set(expected) | {
        "tedom_cento_100_biogas",
        "tedom_cento_200_biogas",
        "tedom_flexi_530_biogas",
    }
    for name, kw in expected.items():
        d = CombustionDatasheet.bundled(name)
        assert d.manufacturer == "ICI Caldaie"
        assert (d.rated_thermal_kw, d.rated_electrical_kw) == (kw, None)
        assert (d.electrical_efficiency, d.thermal_efficiency) == (0, 0.92)


@pytest.mark.spec("CHP-010")
def test_500kw_year():
    year = pd.date_range("2026-01-01", periods=8760, freq="h", tz="UTC")
    out = plant(availability=0.9).simulate(fuel(2000.0, year))
    np.testing.assert_allclose(out.power_kw.sum() / 1000, 3942.0, rtol=0.001)
