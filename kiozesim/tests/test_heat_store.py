"""Heat store plant, spec 0006 (bundled boilers: test_combustion.py, BOIL-012)."""

import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from kiozesim.plants import REGISTRY
from kiozesim.plants.heat_store import (
    HeatStoreInputs,
    HeatStoreOutput,
    HeatStoreParams,
    HeatStorePlant,
)

DAY = pd.date_range("2026-01-15", periods=24, freq="h", tz="UTC")
WEEK = pd.date_range("2026-01-12", periods=24 * 7, freq="h", tz="UTC")

# BOIL-013: a 50 m³ tank, 2 m high, U 0.4, 80/40 °C, room 15 °C, worked out by hand from the
# published equations (oemof.thermal docs, "Stratified thermal storage"), not by oemof:
#   d = sqrt(4 V / (pi h)) = 5.641895835 m; rho c = 971.803 * 4195.52 J/(m3 K)
#   beta  = 4 U 3600 / (d rho c)
#   gamma = 4 U (40 - 15) 3600 / (d rho c (80 - 40))
#   delta = U (pi d^2 / 4) (80 + 40 - 2 * 15) 1 h = 0.4 * 25 * 90 Wh = 0.9 kWh
#   capacity = 50 rho c (80 - 40) / 3.6e6 kWh
BETA = 0.0002503994603950662
GAMMA = 0.00015649966274691637
DELTA_KWH = 0.9
CAPACITY_KWH = 2265.1216236444448
AFTER_24H_KWH = (
    2221.527065195618  # full tank, 24 steps of stored = (1 - beta) stored - (gamma cap + delta)
)


def store(**params: object) -> HeatStorePlant:
    return HeatStorePlant(HeatStoreParams(**({"name": "tank", "volume_m3": 50} | params)))


def inputs(heat: object, demand: object, index: pd.DatetimeIndex = DAY) -> HeatStoreInputs:
    return HeatStoreInputs(
        heat_kw=pd.Series(heat, index=index, dtype=float),
        heat_demand_kw=pd.Series(demand, index=index, dtype=float),
    )


def daily_demand(index: pd.DatetimeIndex) -> np.ndarray:
    """Low at night, a morning and an evening peak."""
    hours = index.hour.to_numpy()
    return np.where((hours >= 6) & (hours < 9), 300.0, np.where(hours >= 17, 400.0, 100.0))


@pytest.mark.spec("BOIL-001")
def test_params_fields_and_defaults():
    assert set(HeatStoreParams.model_fields) == {
        "name",
        "volume_m3",
        "height_m",
        "u_value_w_m2k",
        "temp_hot_c",
        "temp_cold_c",
        "temp_room_c",
        "initial_fill",
    }
    p = HeatStoreParams(name="t", volume_m3=10)
    assert (p.height_m, p.u_value_w_m2k, p.initial_fill) == (2.0, 0.4, 0.5)
    assert (p.temp_hot_c, p.temp_cold_c, p.temp_room_c) == (80, 40, 15)


@pytest.mark.spec("BOIL-001")
@pytest.mark.parametrize(
    "bad",
    [
        {"volume_m3": -1},
        {"height_m": 0},
        {"u_value_w_m2k": 0},
        {"initial_fill": 1.1},
        {"initial_fill": -0.1},
        {"temp_hot_c": 40},  # not above cold
        {"temp_room_c": 45},  # not below cold
        {"volume_m3": float("nan")},
        {"extra": 1},
    ],
)
def test_params_reject(bad):
    with pytest.raises(ValidationError):
        HeatStoreParams(**({"name": "t", "volume_m3": 10} | bad))
    with pytest.raises(ValidationError):
        HeatStoreParams(name="t")  # type: ignore[call-arg]  # volume is required


@pytest.mark.spec("BOIL-002")
def test_inputs_required_and_non_negative():
    with pytest.raises(ValidationError):
        HeatStoreInputs(heat_kw=pd.Series(1.0, index=DAY))  # type: ignore[call-arg]
    for name in ("heat_kw", "heat_demand_kw"):
        bad = {"heat_kw": 1.0, "heat_demand_kw": 1.0} | {name: [-1.0] + [0.0] * 23}
        with pytest.raises(ValidationError, match=name):
            inputs(bad["heat_kw"], bad["heat_demand_kw"])


@pytest.mark.spec("BOIL-003")
def test_capacity():
    assert store().tank().capacity_kwh == pytest.approx(CAPACITY_KWH, rel=1e-9)
    assert store(volume_m3=0).tank().capacity_kwh == 0


@pytest.mark.spec("BOIL-004")
@pytest.mark.spec("BOIL-013")
def test_losses_match_published_equations():
    tank = store().tank(1.0)
    assert tank.loss_rate == pytest.approx(BETA, rel=1e-9)
    assert tank.fixed_relative == pytest.approx(GAMMA, rel=1e-9)
    assert tank.fixed_absolute_kwh == pytest.approx(DELTA_KWH, rel=1e-9)
    quarter = store().tank(0.25)  # losses scale with the step length
    assert quarter.loss_rate == pytest.approx(BETA / 4, rel=1e-9)
    assert quarter.fixed_absolute_kwh == pytest.approx(DELTA_KWH / 4, rel=1e-9)


@pytest.mark.spec("BOIL-004")
def test_loss_never_exceeds_content():
    out = store(initial_fill=0).simulate(inputs(0.0, 0.0))
    np.testing.assert_allclose(out.loss_kw, 0.0)
    np.testing.assert_allclose(out.stored_kwh, 0.0)


@pytest.mark.spec("BOIL-005")
def test_want_is_demand_plus_room():
    plant = store()
    t = DAY[0]
    tank = plant.tank(1.0)
    stored = 1000.0
    after_loss = stored - (BETA * stored + GAMMA * tank.capacity_kwh + DELTA_KWH)
    asked = plant.want(stored, t, {"heat_demand_kw": 120.0}, {}, 1.0)
    assert asked == {"heat_kw": pytest.approx(120.0 + tank.capacity_kwh - after_loss)}
    half = plant.want(stored, t, {"heat_demand_kw": 120.0}, {}, 0.5)  # room spread over 0.5 h
    assert half["heat_kw"] > asked["heat_kw"]


@pytest.mark.spec("BOIL-006")
def test_step_order_and_bounds():
    plant = store(initial_fill=0.9)
    heat = np.r_[np.full(8, 500.0), np.zeros(16)]  # charge hard, then nothing
    demand = np.full(24, 150.0)
    out = plant.simulate(inputs(heat, demand))
    cap = plant.tank().capacity_kwh
    assert (out.stored_kwh >= 0).all() and (out.stored_kwh <= cap + 1e-9).all()
    np.testing.assert_allclose(out.delivered_kw + out.unmet_kw, demand)
    assert out.dumped_kw.iloc[:8].sum() > 0  # full tank: the rest is dumped
    assert out.unmet_kw.iloc[-1] > 0  # empty tank: demand not met


@pytest.mark.spec("BOIL-006")
def test_heat_in_reaches_demand_even_when_full():
    out = store(initial_fill=1).simulate(inputs(200.0, 200.0))
    np.testing.assert_allclose(out.delivered_kw, 200.0)
    assert (out.unmet_kw == 0).all()


@pytest.mark.spec("BOIL-007")
def test_energy_balance_closes():
    plant = store()
    heat = np.full(len(WEEK), 210.0)
    out = plant.simulate(inputs(heat, daily_demand(WEEK), WEEK))
    start = plant.initial_state()
    lhs = start + heat.sum()
    rhs = out.stored_kwh.iloc[-1] + out.delivered_kw.sum() + out.loss_kw.sum() + out.dumped_kw.sum()
    assert rhs == pytest.approx(lhs, rel=1e-6)


@pytest.mark.spec("BOIL-008")
def test_initial_state_and_every_simulate_starts_there():
    plant = store(initial_fill=0.25)
    assert plant.initial_state() == pytest.approx(0.25 * CAPACITY_KWH)
    ts = inputs(0.0, 50.0)
    first, second = plant.simulate(ts), plant.simulate(ts)
    pd.testing.assert_series_equal(first.stored_kwh, second.stored_kwh)


@pytest.mark.spec("BOIL-009")
def test_no_tank_passes_heat_through():
    out = store(volume_m3=0).simulate(inputs([100.0, 300.0] * 12, 200.0))
    np.testing.assert_allclose(out.delivered_kw, [100.0, 200.0] * 12)
    np.testing.assert_allclose(out.dumped_kw, [0.0, 100.0] * 12)
    np.testing.assert_allclose(out.unmet_kw, [100.0, 0.0] * 12)
    assert (out.loss_kw == 0).all() and (out.stored_kwh == 0).all()


@pytest.mark.spec("BOIL-010")
def test_output_series_on_index_and_no_electricity():
    out = store().simulate(inputs(100.0, 80.0))
    assert isinstance(out, HeatStoreOutput)
    for name, s in out:
        assert isinstance(s, pd.Series) and s.index.equals(DAY) and s.name == name
    assert (out.power_kw == 0).all()
    assert REGISTRY["heat_store"] is HeatStorePlant


@pytest.mark.spec("BOIL-011")
def test_oemof_only_for_a_real_tank():
    code = (
        "import sys, pandas as pd\n"
        "sys.modules['oemof'] = None; sys.modules['oemof.thermal'] = None\n"
        "from kiozesim.plants.heat_store import HeatStoreInputs, HeatStoreParams, HeatStorePlant\n"
        "i = pd.date_range('2026-01-01', periods=2, freq='h', tz='UTC')\n"
        "p = HeatStorePlant(HeatStoreParams(name='t', volume_m3=0))\n"
        "p.simulate(HeatStoreInputs(heat_kw=pd.Series(1.0, index=i),"
        " heat_demand_kw=pd.Series(1.0, index=i)))\n"
        "assert 'oemof.thermal' not in sys.modules or sys.modules['oemof.thermal'] is None\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
    import kiozesim.plants.heat_store.plant as module

    assert "oemof" not in module.__dict__  # imported lazily, inside `tank`


@pytest.mark.spec("BOIL-014")
def test_full_tank_cools_step_by_step():
    out = store(initial_fill=1).simulate(inputs(0.0, 0.0))
    assert out.stored_kwh.iloc[-1] == pytest.approx(AFTER_24H_KWH, rel=1e-9)
