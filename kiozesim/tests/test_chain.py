"""Plant chains: the step contract, the runner and sizing, spec 0019."""

from importlib.util import find_spec

import numpy as np
import pandas as pd
import pytest

from kiozesim import FLOWS, CannotBeAsked, Chain, MissingInputError, PlantOutput
from kiozesim.plants import REGISTRY
from kiozesim.plants.base import Plant
from kiozesim.plants.combustion import CombustionDatasheet, CombustionParams, CombustionPlant
from kiozesim.plants.digester import DigesterParams, DigesterPlant, Substrate
from kiozesim.plants.heat_store import HeatStoreParams, HeatStorePlant
from kiozesim.plants.vawt import VAWTDatasheet, VAWTParams, VAWTPlant

from .harness import _read_csv, build_plant, discover

DAY = pd.date_range("2026-01-15", periods=24, freq="h", tz="UTC")
WEEK = pd.date_range("2026-01-12", periods=24 * 7, freq="h", tz="UTC")
SILAGE = {
    "name": "maize silage",
    "fresh_t_per_day": 40,
    "dry_matter_frac": 0.33,
    "organic_frac": 0.95,
    "formula": "C6H10O5",
    "biodegradability": 0.8,
}
ENGINE = {
    "manufacturer": "m",
    "model": "engine",
    "rated_electrical_kw": 500,
    "electrical_efficiency": 0.40,
    "thermal_efficiency": 0.45,
}
BOILER = {
    "manufacturer": "m",
    "model": "boiler",
    "rated_thermal_kw": 300,
    "electrical_efficiency": 0,
    "thermal_efficiency": 0.92,
}


def digester(t_per_day: float = 40) -> DigesterPlant:
    sub = Substrate(**(SILAGE | {"fresh_t_per_day": t_per_day}))
    return DigesterPlant(DigesterParams(name="farm", substrates=(sub,)))


def combustion(name: str, sheet: dict, availability: float = 1.0) -> CombustionPlant:
    ds = CombustionDatasheet(**sheet)
    return CombustionPlant(CombustionParams(name=name, datasheet=ds, availability=availability))


def store(**kw: object) -> HeatStorePlant:
    return HeatStorePlant(HeatStoreParams(**({"name": "tank", "volume_m3": 20} | kw)))


def demand(index: pd.DatetimeIndex) -> pd.DataFrame:
    hours = index.hour.to_numpy()
    kw = np.where((hours >= 6) & (hours < 9), 300.0, np.where(hours >= 17, 400.0, 100.0))
    return pd.DataFrame({"heat_demand_kw": kw}, index=index)


def constant(index: pd.DatetimeIndex, **values: float) -> pd.DataFrame:
    return pd.DataFrame(values, index=index, dtype=float)


def stepped(plant: Plant, frame: pd.DataFrame | None, index: pd.DatetimeIndex) -> pd.DataFrame:  # type: ignore[type-arg]
    """Step a plant on its own through `index`, nothing wanted of it."""
    dt_h = (index[1] - index[0]) / pd.Timedelta(hours=1)
    state, rows = plant.initial_state(), []
    for k, t in enumerate(index):
        values = {} if frame is None else {c: float(frame[c].iloc[k]) for c in frame.columns}
        state, out = plant.step(state, t, values, {}, dt_h)
        rows.append(out)
    return pd.DataFrame(rows, index=index)


def registry_examples() -> dict[str, tuple[Plant, pd.DataFrame | None, pd.DatetimeIndex]]:  # type: ignore[type-arg]
    """One plant of every REGISTRY type with a short input table."""
    examples: dict[str, tuple[Plant, pd.DataFrame | None, pd.DatetimeIndex]] = {}  # type: ignore[type-arg]
    for case in discover():
        if case.plant in ("pv", "hawt") and case.plant not in examples:
            frame = _read_csv(case.path / "inputs.csv")
            frame = frame.iloc[4380:4392] if case.plant == "pv" else frame.iloc[:12]
            examples[case.plant] = (build_plant(case), frame, frame.index)
    vawt_sheet = VAWTDatasheet(
        manufacturer="m",
        model="v",
        rotor_type="darrieus",
        rotor_diameter_m=3,
        rotor_height_m=4,
        rated_power_kw=5,
        method="power_curve",
        wind_speed_m_s=[3, 6, 9, 12, 20],
        power_kw=[0, 1, 3, 5, 5],
    )
    vawt = VAWTPlant(VAWTParams(name="v", datasheet=vawt_sheet, hub_height_m=12))
    wind = pd.DataFrame(
        {"wind_speed_m_s": np.linspace(2, 22, 24), "temp_air_c": 5.0, "pressure_hpa": 1000.0},
        index=DAY,
    )
    fuel = pd.DataFrame({"fuel_kw": np.linspace(0, 2000, 24)}, index=DAY)
    heat = pd.DataFrame({"heat_kw": np.linspace(0, 500, 24)}, index=DAY).join(demand(DAY))
    examples |= {
        "vawt": (vawt, wind, DAY),
        "combustion": (combustion("e", ENGINE, 0.9), fuel, DAY),
        "digester": (digester(), None, DAY),
        "heat_store": (store(), heat, DAY),
    }
    return examples


# --- the contract --------------------------------------------------------------------------


@pytest.mark.spec("CHAIN-001")
def test_contract_defaults_for_plants_without_memory():
    plant = digester()
    assert plant.initial_state() is None
    assert plant.want(None, DAY[0], {}, {"fuel_kw": 1.0}, 1.0) == {}
    assert DigesterPlant.follows_requests is False
    with pytest.raises(CannotBeAsked):
        VAWTPlant.needs(registry_examples()["vawt"][0], {"power_kw": 1.0})


@pytest.mark.spec("CHAIN-001")
def test_plants_keep_no_state_between_calls():
    chain = Chain([combustion("boiler", BOILER), store()])
    inputs = {"boiler": constant(DAY, fuel_kw=400), "tank": demand(DAY)}
    first, second = chain.run(DAY, inputs), chain.run(DAY, inputs)
    pd.testing.assert_frame_equal(first.outputs["tank"], second.outputs["tank"])
    for p in chain.plants:
        assert set(vars(p)) == {"params"}


@pytest.mark.spec("CHAIN-002")
@pytest.mark.skipif(
    find_spec("pvlib") is None or find_spec("windpowerlib") is None, reason="needs pv, wind"
)
def test_stepping_equals_simulate_for_every_plant():
    examples = registry_examples()
    assert set(examples) == set(REGISTRY)
    for name, (plant, frame, index) in examples.items():
        ts = None if plant.inputs_model is None else plant.inputs_model.from_frame(frame)
        expected = (plant.simulate() if ts is None else plant.simulate(ts)).to_frame(index)
        got = stepped(plant, frame, index)[expected.columns]
        np.testing.assert_allclose(got, expected, rtol=1e-9, atol=1e-9, err_msg=name)


@pytest.mark.spec("CHAIN-003")
def test_followers_make_no_more_than_wanted_and_pass_spare_fuel_on():
    boiler = combustion("boiler", BOILER)
    _, out = boiler.step(None, DAY[0], {"fuel_kw": 400.0}, {"heat_kw": 50.0}, 1.0)
    assert out["heat_kw"] == pytest.approx(50.0)
    assert out["fuel_kw"] == pytest.approx(400.0 - 50.0 / 0.92)  # the rest passes on in full
    _, out = digester().step(None, DAY[0], {}, {"fuel_kw": 1.0}, 1.0)  # ignores requests
    assert out["fuel_kw"] == pytest.approx(1728.3, rel=1e-3)


@pytest.mark.spec("CHAIN-004")
def test_output_to_frame():
    out = digester().simulate()
    frame = out.to_frame(DAY)
    assert list(frame.columns) == ["power_kw", "fuel_kw", "methane_nm3_per_h"]
    assert frame.index.equals(DAY) and (frame["fuel_kw"] == out.fuel_kw).all()
    with pytest.raises(ValueError, match="index"):
        out.to_frame()
    series = PlantOutput(power_kw=pd.Series(1.0, index=DAY)).to_frame()
    assert series.index.equals(DAY) and list(series.columns) == ["power_kw"]


@pytest.mark.spec("CHAIN-005")
def test_naming_scheme():
    for name, cls in REGISTRY.items():
        flows_in = [n for n in cls.input_names() if n in FLOWS]
        assert set(flows_in) <= {"fuel_kw", "heat_kw"}, name
        assert "power_kw" in cls.output_names(), name
    # an output of the same kind as an input is what is left of it
    assert set(CombustionPlant.input_names()) & set(CombustionPlant.output_names()) == {"fuel_kw"}
    # the heat store takes heat_kw in and passes no heat on
    assert not set(HeatStorePlant.output_names()) & {"fuel_kw", "heat_kw"}
    out = combustion("e", ENGINE).step(None, DAY[0], {"fuel_kw": 2000.0}, {}, 1.0)[1]
    assert out["fuel_kw"] == pytest.approx(2000.0 - 500 / 0.40)


# --- the runner ----------------------------------------------------------------------------


@pytest.mark.spec("CHAIN-010")
def test_chain_rejects_and_finds_missing_inputs():
    with pytest.raises(ValueError, match="at least one"):
        Chain([])
    with pytest.raises(ValueError, match="unique"):
        Chain([store(), store()])
    with pytest.raises(MissingInputError, match="tank.*heat_kw") as e:
        Chain([store()]).run(DAY, {"tank": demand(DAY)})  # first plant: flows from the caller
    assert e.value.box == "tank"
    with pytest.raises(MissingInputError, match="tank.*heat_demand_kw"):
        Chain([combustion("boiler", BOILER), store()]).run(
            DAY, {"boiler": constant(DAY, fuel_kw=100)}
        )
    with pytest.raises(MissingInputError, match="tank.*heat_kw"):  # a digester gives no heat
        Chain([digester(), store()]).run(DAY, {"tank": demand(DAY).assign(heat_kw=1.0)})


@pytest.mark.spec("CHAIN-010")
def test_flows_come_from_the_plant_in_front():
    chain = Chain([combustion("boiler", BOILER | {"rated_thermal_kw": 620}), store(volume_m3=0)])
    tank_table = demand(DAY).assign(heat_kw=9999.0)  # ignored: heat comes from the boiler
    res = chain.run(DAY, {"boiler": constant(DAY, fuel_kw=1000), "tank": tank_table})
    np.testing.assert_allclose(res.outputs["tank"]["delivered_kw"], demand(DAY)["heat_demand_kw"])
    assert (res.outputs["tank"]["dumped_kw"] < 1e-9).all()


@pytest.mark.spec("CHAIN-011")
def test_two_halves_with_states_equal_one_run():
    chain = Chain([combustion("boiler", BOILER), store()])
    inputs = {"boiler": constant(WEEK, fuel_kw=250), "tank": demand(WEEK)}
    whole = chain.run(WEEK, inputs)
    cut = 24 * 3
    a, b = WEEK[:cut], WEEK[cut:]
    first = chain.run(a, {k: v.loc[a] for k, v in inputs.items()})
    second = chain.run(b, {k: v.loc[b] for k, v in inputs.items()}, first.states)
    joined = pd.concat([first.outputs["tank"], second.outputs["tank"]])
    pd.testing.assert_frame_equal(joined, whole.outputs["tank"])
    assert second.states["tank"] == pytest.approx(whole.states["tank"])
    assert whole.states["boiler"] is None


@pytest.mark.spec("CHAIN-012")
def test_plants_with_no_memory_behind_them_are_not_stepped():
    class NoStep(CombustionPlant):
        def step(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("stepped")

    sheet = CombustionDatasheet(**ENGINE)
    engine = NoStep(CombustionParams(name="engine", datasheet=sheet))
    res = Chain([digester(), engine]).run(DAY)
    np.testing.assert_allclose(res.outputs["engine"]["power_kw"], 500.0)
    with pytest.raises(AssertionError, match="stepped"):  # a tank behind it: stepped
        Chain([engine, store()]).run(
            DAY, {"engine": constant(DAY, fuel_kw=10), "tank": demand(DAY)}
        )


@pytest.mark.spec("CHAIN-013")
def test_result_holds_every_plant_and_flared_fuel():
    res = Chain([digester(), combustion("engine", ENGINE)]).run(DAY)
    assert list(res.outputs) == ["farm", "engine"]
    for table in res.outputs.values():
        assert table.index.equals(DAY)
    pd.testing.assert_series_equal(
        res.flared_kw, res.outputs["engine"]["fuel_kw"].rename("flared_kw")
    )
    tank = Chain([combustion("boiler", BOILER), store()]).run(
        DAY, {"boiler": constant(DAY, fuel_kw=100), "tank": demand(DAY)}
    )
    assert (tank.flared_kw == 0).all() and tank.flared_kw.index.equals(DAY)


# --- the plants ----------------------------------------------------------------------------


@pytest.mark.spec("CHAIN-020")
def test_digester_is_a_plant():
    assert REGISTRY["digester"] is DigesterPlant
    out = digester().simulate()
    assert out.power_kw == 0 and out.fuel_kw == pytest.approx(1728.3, rel=1e-3)


@pytest.mark.spec("CHAIN-021")
def test_one_combustion_plant_for_engines_and_boilers():
    assert REGISTRY["combustion"] is CombustionPlant and CombustionPlant.follows_requests
    assert CombustionParams.model_fields["availability"].default == 1.0
    names = CombustionDatasheet.available()
    assert {"tedom_flexi_530_biogas", "ici_caldaie_rex_62"} <= set(names)
    # heat-led: asked for heat, it burns no more than the heat needs; availability caps it
    engine = combustion("e", ENGINE, availability=0.9)
    _, out = engine.step(None, DAY[0], {"fuel_kw": 2000.0}, {"heat_kw": 100.0}, 1.0)
    assert out["heat_kw"] == pytest.approx(100.0)
    _, out = engine.step(None, DAY[0], {"fuel_kw": 2000.0}, {"heat_kw": 1e6}, 1.0)
    assert out["heat_kw"] == pytest.approx(0.9 * 1250 * 0.45)
    assert engine.want(None, DAY[0], {}, {"heat_kw": 90.0}, 1.0) == {
        "fuel_kw": pytest.approx(90 / 0.45 / 0.9)
    }


@pytest.mark.spec("CHAIN-022")
def test_heat_store_is_its_own_plant_with_memory():
    assert REGISTRY["heat_store"] is HeatStorePlant and HeatStorePlant.follows_requests
    assert store().initial_state() == pytest.approx(0.5 * store().tank().capacity_kwh)


@pytest.mark.spec("CHAIN-023")
def test_needs_invert_the_equations():
    boiler = combustion("boiler", BOILER)
    assert boiler.needs({"heat_kw": 92.0}).inputs == {"fuel_kw": pytest.approx(100.0)}
    engine = combustion("e", ENGINE, availability=0.8)
    assert engine.needs({"power_kw": 200.0}).inputs == {"fuel_kw": pytest.approx(500 / 0.8)}
    tank = store()
    s = tank.needs({"delivered_kw": 100.0})
    t = tank.tank(1.0)
    loss = t.loss_kwh(0.5 * t.capacity_kwh)
    assert s.inputs == {"heat_kw": pytest.approx(100.0 + loss)}
    two = DigesterPlant(
        DigesterParams(
            name="farm",
            substrates=(
                Substrate(**SILAGE),
                Substrate(**(SILAGE | {"name": "slurry", "fresh_t_per_day": 10})),
            ),
        )
    )
    made = two.simulate().fuel_kw
    feed = two.needs({"fuel_kw": made / 2}).feed_t_per_day
    assert feed == {"maize silage": pytest.approx(20.0), "slurry": pytest.approx(5.0)}


@pytest.mark.spec("CHAIN-024")
@pytest.mark.skipif(find_spec("pvlib") is None, reason="needs the 'pv' extra")
def test_weather_plants_cannot_be_asked():
    examples = registry_examples()
    for name in ("pv", "hawt", "vawt"):
        plant = examples[name][0]
        with pytest.raises(CannotBeAsked, match=plant.name):
            plant.needs({"power_kw": 1.0})


# --- sizing --------------------------------------------------------------------------------


@pytest.mark.spec("CHAIN-030")
def test_sizing_walks_back_to_the_feed():
    chain = Chain([digester(), combustion("boiler", BOILER), store()])
    res = chain.size({"delivered_kw": 100.0})
    assert [s.plant for s in res.steps] == ["tank", "boiler", "farm"]
    assert res.stopped_at is None
    assert res.steps[1].wanted == {"heat_kw": res.steps[0].needs["heat_kw"]}
    assert set(res.steps[-1].feed_t_per_day) == {"maize silage"}
    with pytest.raises(ValueError, match="tank cannot be asked for heat_kw; ask for delivered_kw"):
        chain.size({"heat_kw": 1.0})
    with pytest.raises(ValueError, match="ask for heat_kw, power_kw, fuel_kw"):
        Chain([combustion("c", BOILER)]).size({"energy_kwh": 100.0})


@pytest.mark.spec("CHAIN-030")
def test_sizing_stops_at_a_plant_that_cannot_be_asked():
    vawt = registry_examples()["vawt"][0]
    res = Chain([vawt]).size({"power_kw": 1.0})
    assert res.steps == [] and res.stopped_at == "v" and "cannot be asked" in res.reason


@pytest.mark.spec("CHAIN-031")
def test_sizing_reports_limit_and_shortfall():
    res = Chain([digester(), combustion("boiler", BOILER)]).size({"heat_kw": 500.0})
    boiler = res.steps[0]
    assert boiler.given == {"heat_kw": pytest.approx(300.0)}
    assert boiler.shortfall == {"heat_kw": pytest.approx(200.0)}
    assert res.steps[1].wanted == {"fuel_kw": pytest.approx(300 / 0.92)}


# --- validation ----------------------------------------------------------------------------


@pytest.mark.spec("CHAIN-050")
def test_sizing_100kw_heat_to_feed():
    res = Chain([digester(), combustion("boiler", BOILER)]).size({"heat_kw": 100.0})
    assert res.steps[-1].feed_t_per_day["maize silage"] == pytest.approx(2.516, rel=1e-3)


@pytest.mark.spec("CHAIN-051")
def test_boiler_and_store_balance_and_requests():
    boiler, tank = combustion("boiler", BOILER), store()
    inputs = {"boiler": constant(WEEK, fuel_kw=300), "tank": demand(WEEK)}
    res = Chain([boiler, tank]).run(WEEK, inputs)
    made, out = res.outputs["boiler"], res.outputs["tank"]
    start = tank.initial_state()
    lhs = start + made["heat_kw"].sum()
    rhs = out["stored_kwh"].iloc[-1] + out[["delivered_kw", "loss_kw", "dumped_kw"]].sum().sum()
    assert rhs == pytest.approx(lhs, rel=1e-6)
    before = np.r_[start, out["stored_kwh"].to_numpy()[:-1]]
    for k, t in enumerate(WEEK):
        asked = tank.want(before[k], t, {"heat_demand_kw": demand(WEEK).iloc[k, 0]}, {}, 1.0)
        assert made["heat_kw"].iloc[k] <= asked["heat_kw"] + 1e-9
    assert (out["dumped_kw"] < 1e-9).all()


@pytest.mark.spec("CHAIN-052")
def test_engine_leaves_gas_for_the_boiler():
    engine = combustion("engine", ENGINE, availability=0.9)
    boiler = combustion("boiler", BOILER)
    res = Chain([digester(), engine, boiler]).run(DAY)
    left = res.outputs["engine"]["fuel_kw"]
    burned = left - res.outputs["boiler"]["fuel_kw"]
    np.testing.assert_allclose(res.outputs["boiler"]["heat_kw"], burned * 0.92)
    np.testing.assert_allclose(burned, np.minimum(left, 300 / 0.92))
    pd.testing.assert_series_equal(
        res.flared_kw, res.outputs["boiler"]["fuel_kw"].rename("flared_kw")
    )
