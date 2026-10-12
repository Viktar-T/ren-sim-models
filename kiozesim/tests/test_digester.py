"""Biogas digester (fuel source), spec 0005."""

import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from kiozesim.plants import REGISTRY
from kiozesim.plants.base import Plant
from kiozesim.plants.chp import CHPDatasheet, CHPInputs, CHPParams, CHPPlant
from kiozesim.sources import Source
from kiozesim.sources.digester import (
    Digester,
    DigesterParams,
    Substrate,
)
from kiozesim.timegrid import TimeGridError

# The spec's worked example: 40 t/day, DM 0.33, organic 0.95, C6H10O5, biodegradability 0.8.
SILAGE = {
    "name": "maize silage",
    "fresh_t_per_day": 40,
    "dry_matter_frac": 0.33,
    "organic_frac": 0.95,
    "formula": "C6H10O5",
    "biodegradability": 0.8,
}
SLURRY = {
    "name": "cattle slurry",
    "fresh_t_per_day": 30,
    "dry_matter_frac": 0.08,
    "organic_frac": 0.8,
    "formula": "C5H7NO2",
    "biodegradability": 0.5,
}
DAYS = pd.date_range("2026-01-01", periods=10, freq="D", tz="UTC")


def digester(*subs: dict) -> Digester:
    return Digester(
        DigesterParams(name="d", substrates=tuple(Substrate(**s) for s in subs or (SILAGE,)))
    )


@pytest.mark.spec("BIO-001")
def test_substrate_and_params_fields():
    assert set(Substrate.model_fields) == {
        "name",
        "fresh_t_per_day",
        "dry_matter_frac",
        "organic_frac",
        "formula",
        "biodegradability",
    }
    assert set(DigesterParams.model_fields) == {"name", "substrates"}


@pytest.mark.spec("BIO-001")
@pytest.mark.parametrize(
    "bad",
    [
        {"name": ""},
        {"fresh_t_per_day": -1},
        {"dry_matter_frac": 0},
        {"dry_matter_frac": 1.1},
        {"organic_frac": 0},
        {"organic_frac": 95},  # percent instead of a fraction
        {"biodegradability": 0},
        {"biodegradability": 1.01},
        {"dry_matter_frac": float("nan")},
        {"extra": 1},
    ],
)
def test_substrate_rejects(bad):
    with pytest.raises(ValidationError):
        Substrate(**(SILAGE | bad))


@pytest.mark.spec("BIO-001")
def test_params_need_unique_nonempty_substrates():
    with pytest.raises(ValidationError):
        DigesterParams(name="d", substrates=())
    with pytest.raises(ValidationError, match="maize silage"):
        DigesterParams(name="d", substrates=(Substrate(**SILAGE), Substrate(**SILAGE)))
    with pytest.raises(ValidationError):
        DigesterParams(name="", substrates=(Substrate(**SILAGE),))


@pytest.mark.spec("BIO-003")
@pytest.mark.parametrize(
    "formula", ["C6H10O5", "C5H7NO2", "C57H104O6", "CH4", "C1H1.6O0.6N0.1S0.01", "H4C"]
)
def test_formula_accepted(formula):
    Substrate(**(SILAGE | {"formula": formula}))


@pytest.mark.spec("BIO-003")
@pytest.mark.parametrize(
    "formula",
    [
        "",
        "H2O",  # no carbon
        "C6O5",  # no hydrogen
        "C6H10O5P",  # unknown element
        "C6H10C2O5",  # carbon twice
        "C0H4",  # zero count
        "C6H-10O5",
        "c6h10o5",
        "C6 H10 O5",
        "CH2O3",  # no methane by Buswell-Boyle: 1/2 + 2/8 - 3/4 = 0
    ],
)
def test_formula_rejected_naming_substrate(formula):
    with pytest.raises(ValidationError, match="maize silage"):
        Substrate(**(SILAGE | {"formula": formula}))


@pytest.mark.spec("BIO-004")
def test_simulate_takes_a_valid_time_axis():
    with pytest.raises(TimeGridError):
        digester().simulate(pd.date_range("2026-01-01", periods=10, freq="D"))  # not UTC
    with pytest.raises(TimeGridError):
        digester().simulate(DAYS[[0, 1, 3]])  # irregular


@pytest.mark.spec("BIO-002")
def test_is_fuel_source_not_plant():
    out = digester().simulate(DAYS)
    assert isinstance(out, pd.DataFrame) and out.index.equals(DAYS)
    assert list(out.columns) == ["fuel_kw", "methane_nm3_per_h"]
    assert issubclass(Digester, Source) and not issubclass(Digester, Plant)
    assert Digester not in REGISTRY.values()


@pytest.mark.spec("BIO-005")
def test_buswell_boyle():
    # C6H10O5: 3 mol CH4 per 162.141 g
    y = Substrate(**SILAGE).yield_nm3_per_kg
    assert y == pytest.approx(3 * 22.414 / (6 * 12.011 + 10 * 1.008 + 5 * 15.999), rel=1e-12)
    # with N and S: a/2 + b/8 - c/4 - 3d/8 - e/4
    s = Substrate(**(SILAGE | {"formula": "C2H8O1N1S1"}))
    mol = 1 + 1 - 0.25 - 0.375 - 0.25
    mass = 2 * 12.011 + 8 * 1.008 + 15.999 + 14.007 + 32.06
    assert s.yield_nm3_per_kg == pytest.approx(mol * 22.414 / mass, rel=1e-12)


@pytest.mark.spec("BIO-006")
def test_feed_to_fuel_two_substrates_constant():
    out = digester(SILAGE, SLURRY).simulate(DAYS)
    nm3_day = sum(
        s["fresh_t_per_day"]
        * 1000
        * s["dry_matter_frac"]
        * s["organic_frac"]
        * s["biodegradability"]
        * Substrate(**s).yield_nm3_per_kg
        for s in (SILAGE, SLURRY)
    )
    np.testing.assert_allclose(out.methane_nm3_per_h, nm3_day / 24)
    np.testing.assert_allclose(out.fuel_kw, nm3_day / 24 * 9.97)


@pytest.mark.spec("BIO-007")
def test_output_feeds_gas_engine_unchanged():
    out = digester().simulate(DAYS)
    sheet = CHPDatasheet(
        manufacturer="m",
        model="x",
        rated_electrical_kw=500,
        electrical_efficiency=0.4,
        thermal_efficiency=0.45,
    )
    engine = CHPPlant(CHPParams(name="e", datasheet=sheet, availability=1))
    res = engine.simulate(CHPInputs.from_frame(out))
    np.testing.assert_allclose(res.power_kw, 500.0)  # 1728 kW fuel > 1250 kW full load


@pytest.mark.spec("BIO-008")
def test_no_feed_no_gas():
    empty = ({**SILAGE, "fresh_t_per_day": 0}, {**SLURRY, "fresh_t_per_day": 0})
    out = digester(*empty).simulate(DAYS)
    assert (out.fuel_kw == 0).all() and (out.methane_nm3_per_h == 0).all()


@pytest.mark.spec("BIO-009")
def test_no_extra_dependency():
    code = (
        "import sys, pandas as pd\n"
        "sys.modules['pvlib'] = None; sys.modules['windpowerlib'] = None\n"
        "from kiozesim.sources.digester import (\n"
        "    Digester, DigesterParams, Substrate)\n"
        "s = Substrate(name='a', fresh_t_per_day=1, dry_matter_frac=0.3, organic_frac=0.9,"
        " formula='C6H10O5', biodegradability=0.8)\n"
        "i = pd.date_range('2026-01-01', periods=2, freq='D', tz='UTC')\n"
        "Digester(DigesterParams(name='d', substrates=(s,))).simulate(i)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


@pytest.mark.spec("BIO-010")
@pytest.mark.parametrize(
    ("formula", "textbook"), [("C6H10O5", 0.415), ("C5H7NO2", 0.496), ("C57H104O6", 1.014)]
)
def test_textbook_yields(formula, textbook):
    y = Substrate(**(SILAGE | {"formula": formula})).yield_nm3_per_kg
    assert y == pytest.approx(textbook, rel=0.01)


@pytest.mark.spec("BIO-011")
def test_worked_example():
    out = digester().simulate(DAYS)
    np.testing.assert_allclose(out.fuel_kw, 1728.3, rtol=0.001)


def test_digester_into_500kw_engine_for_a_year():
    """Spec 0005 Acceptance: a year of daily steps, digester -> 500 kW engine."""
    year = pd.date_range("2026-01-01", periods=365, freq="D", tz="UTC")
    gas = digester().simulate(year)
    sheet = CHPDatasheet.bundled("tedom_flexi_530_biogas")
    engine = CHPPlant(CHPParams(name="e", datasheet=sheet, availability=0.9))
    power = engine.simulate(CHPInputs.from_frame(gas)).power_kw
    # 1728 kW fuel > 1313 kW full load: the engine runs full whenever available
    np.testing.assert_allclose(power.sum() * 24 / 1000, 528 * 0.9 * 8760 / 1000, rtol=1e-9)
