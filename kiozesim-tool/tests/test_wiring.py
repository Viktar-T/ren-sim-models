"""Spec 0016: wiring sources to plants, shared by both apps (SRC-020..024)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import BaseModel, ConfigDict

from kiozesim import Source
from kiozesim.plants.chp import CHPDatasheet, CHPParams, CHPPlant
from kiozesim.sources import ConstantParams, ConstantSource
from kiozesim_tool.wiring import WiringError, check, join, run

HOURS = pd.date_range("2026-06-21", periods=24, freq="h", tz="UTC")
SHEET = CHPDatasheet(
    manufacturer="m",
    model="x",
    rated_electrical_kw=500,
    electrical_efficiency=0.4,
    thermal_efficiency=0.45,
)


def const(name: str, **values: float) -> ConstantSource:
    return ConstantSource(ConstantParams(name=name, values=values))


def engine(name: str = "engine") -> CHPPlant:
    return CHPPlant(CHPParams(name=name, datasheet=SHEET, availability=1))


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
        (["a"], ["p"], {"p": ["b"]}, "p", "not a source"),
        (["a"], ["a"], {"a": [], "p": ["a"]}, "a", "more than one box"),
        (["a", "b"], ["p"], {"a": ["b"], "b": ["a"], "p": ["a"]}, "a", "loop"),
        (["a"], ["p"], {"a": ["a"], "p": ["a"]}, "a", "loop"),
        (["a"], ["p", "q"], {"p": ["a"], "q": ["p"]}, "q", "not a source"),
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
    )
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
