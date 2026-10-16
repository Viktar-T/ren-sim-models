"""Wiring sources and plants, shared by both apps: specs 0016 (SRC-020..024), 0019 (CHAIN-040)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import BaseModel, ConfigDict

from kiozesim.plants.combustion import CombustionDatasheet, CombustionParams, CombustionPlant
from kiozesim.plants.digester import DigesterParams, DigesterPlant, Substrate
from kiozesim.plants.heat_store import HeatStoreParams, HeatStorePlant
from kiozesim_tool.sources import ConstantParams, ConstantSource, Source
from kiozesim_tool.wiring import WiringError, chains, check, join, run

HOURS = pd.date_range("2026-06-21", periods=24, freq="h", tz="UTC")
SHEET = CombustionDatasheet(
    manufacturer="m",
    model="x",
    rated_electrical_kw=500,
    electrical_efficiency=0.4,
    thermal_efficiency=0.45,
)
BOILER = CombustionDatasheet(
    manufacturer="m",
    model="b",
    rated_thermal_kw=600,
    electrical_efficiency=0,
    thermal_efficiency=0.92,
)


def const(name: str, **values: float) -> ConstantSource:
    return ConstantSource(ConstantParams(name=name, values=values))


def engine(name: str = "engine", sheet: CombustionDatasheet = SHEET) -> CombustionPlant:
    return CombustionPlant(CombustionParams(name=name, datasheet=sheet))


def farm(name: str = "farm") -> DigesterPlant:
    sub = Substrate(
        name="maize silage",
        fresh_t_per_day=40,
        dry_matter_frac=0.33,
        organic_frac=0.95,
        formula="C6H10O5",
        biodegradability=0.8,
    )
    return DigesterPlant(DigesterParams(name=name, substrates=(sub,)))


def tank(name: str = "tank") -> HeatStorePlant:
    return HeatStorePlant(HeatStoreParams(name=name, volume_m3=20))


class CountParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str


class Halve(Source[CountParams]):
    """Takes `fuel_in`, gives `fuel_kw` = half of it; counts its runs."""

    params_model = CountParams
    runs = 0

    def _simulate(self, index, inputs):
        Halve.runs += 1
        return pd.DataFrame({"fuel_kw": self._require(inputs, ["fuel_in"])["fuel_in"] / 2})


@pytest.mark.spec("SRC-020")
@pytest.mark.parametrize(
    ("sources", "plants", "wires", "box", "text"),
    [
        (["a"], ["p"], {}, "p", "not wired"),
        (["a"], ["p"], {"p": ["b"]}, "p", "not a source or a plant"),
        (["a"], ["p"], {"a": ["p"], "p": ["a"]}, "a", "not a source"),
        (["a"], ["a"], {"a": [], "p": ["a"]}, "a", "more than one box"),
        (["a", "b"], ["p"], {"a": ["b"], "b": ["a"], "p": ["a"]}, "a", "loop"),
        (["a"], ["p"], {"a": ["a"], "p": ["a"]}, "a", "loop"),
        (["a"], ["p"], {"p": ["a", "a"]}, "p", "twice"),
    ],
)
def test_bad_wiring_rejected_naming_box(sources, plants, wires, box, text):
    with pytest.raises(WiringError, match=text) as e:
        check(sources, plants, wires)
    assert e.value.box == box


@pytest.mark.spec("SRC-020")
def test_order_puts_sources_after_what_feeds_them():
    order = check(["half", "feed", "w"], ["p"], {"half": ["feed"], "p": ["half", "w"]})
    assert order.index("feed") < order.index("half")


@pytest.mark.spec("SRC-021")
def test_each_source_runs_once_and_feeds_every_box():
    Halve.runs = 0
    half = Halve(CountParams(name="half"))
    out = run(
        [const("feed", fuel_in=2000), half],
        [engine("e1"), engine("e2")],
        {"half": ["feed"], "e1": ["half"], "e2": ["half"]},
        HOURS,
    ).power
    assert Halve.runs == 1
    np.testing.assert_allclose(out["e1"], 400.0)  # 1000 kW fuel x 0.4
    np.testing.assert_allclose(out["total"], 800.0)


@pytest.mark.spec("SRC-021")
def test_tables_of_several_sources_are_joined():
    t = join("p", {"a": pd.DataFrame({"x": [1.0]}), "b": pd.DataFrame({"y": [2.0]})})
    assert t is not None and list(t.columns) == ["x", "y"]
    assert join("p", {}) is None


@pytest.mark.spec("SRC-022")
def test_missing_column_becomes_wiring_error():
    with pytest.raises(WiringError, match=r"engine: wired to w, which give no fuel_kw") as e:
        run([const("w", ghi_w_m2=500)], [engine()], {"engine": ["w"]}, HOURS)
    assert e.value.box == "engine"
    with pytest.raises(WiringError, match=r"half: wired to no source, which give no fuel_in"):
        run([Halve(CountParams(name="half"))], [engine()], {"engine": ["half"]}, HOURS)


@pytest.mark.spec("SRC-024")
def test_same_column_from_two_sources_rejected():
    with pytest.raises(WiringError, match="'fuel_kw' comes from both a and b") as e:
        run(
            [const("a", fuel_kw=1), const("b", fuel_kw=2)],
            [engine()],
            {"engine": ["a", "b"]},
            HOURS,
        )
    assert e.value.box == "engine"


@pytest.mark.spec("CHAIN-040")
@pytest.mark.parametrize(
    ("plants", "wires", "box", "text"),
    [
        (["p", "q", "r"], {"p": ["a"], "q": ["a"], "r": ["p", "q"]}, "r", "two plants"),
        (["p", "q", "r"], {"p": ["a"], "q": ["p"], "r": ["p"]}, "p", "feeds two plants"),
        (["p", "q"], {"p": ["q"], "q": ["p"]}, "p", "loop"),
        (["farm"], {"farm": ["a"]}, "farm", "takes no input"),
    ],
)
def test_plant_wiring_rejected_naming_plant(plants, wires, box, text):
    with pytest.raises(WiringError, match=text) as e:
        check(["a"], plants, wires, no_input={"farm"})
    assert e.value.box == box


@pytest.mark.spec("CHAIN-040")
def test_plants_form_straight_chains():
    wires = {"engine": ["farm"], "boiler": ["engine"], "roof": ["w"]}
    check(["w"], ["boiler", "roof", "engine", "farm"], wires, no_input={"farm"})
    assert chains(["boiler", "roof", "engine", "farm"], wires) == [
        ["roof"],
        ["farm", "engine", "boiler"],
    ]


@pytest.mark.spec("CHAIN-040")
@pytest.mark.spec("SRC-023")
def test_chain_runs_with_library_chain_and_states_carry_on():
    plants = [farm(), engine("boiler", BOILER), tank()]
    sources = [const("demand", heat_demand_kw=150)]
    wires = {"boiler": ["farm"], "tank": ["boiler", "demand"]}
    whole = run(sources, plants, wires, HOURS)
    assert list(whole.power.columns) == ["farm", "boiler", "tank", "total"]
    assert (whole.power["total"] == 0).all()  # heat only: no electricity
    np.testing.assert_allclose(whole.outputs["tank"]["delivered_kw"], 150.0)
    a, b = HOURS[:12], HOURS[12:]
    first = run(sources, plants, wires, a)
    second = run(sources, plants, wires, b, first.states)
    joined = pd.concat([first.outputs["tank"], second.outputs["tank"]])
    pd.testing.assert_frame_equal(joined, whole.outputs["tank"])


@pytest.mark.spec("CHAIN-041")
def test_power_only_on_the_chart_and_total():
    res = run([], [farm(), engine()], {"engine": ["farm"]}, HOURS)
    np.testing.assert_allclose(res.power["engine"], 500.0)
    np.testing.assert_allclose(res.power["total"], 500.0)
    assert "heat_kw" in res.outputs["engine"] and "heat_kw" not in res.power


@pytest.mark.spec("SRC-022")
def test_missing_column_in_a_chain_becomes_wiring_error():
    with pytest.raises(WiringError, match=r"tank: wired to farm, which give no heat_kw") as e:
        run([], [farm(), tank()], {"tank": ["farm"]}, HOURS)
    assert e.value.box == "tank"
