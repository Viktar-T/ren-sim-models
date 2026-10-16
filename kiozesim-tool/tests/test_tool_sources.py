"""Sources in the tool, specs 0016 (SRC-001, 002, 005) and 0019 (CHAIN-025)."""

import pandas as pd
import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from kiozesim import MissingInputError
from kiozesim.plants.combustion import CombustionInputs
from kiozesim.timegrid import TimeGridError
from kiozesim_tool.sources import ConstantParams, ConstantSource, Source

HOURS = pd.date_range("2026-06-21", periods=24, freq="h", tz="UTC")


class DoubleParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str


class Double(Source[DoubleParams]):
    """A source with one input column `x`, output `y = 2x`."""

    params_model = DoubleParams

    def _simulate(self, index, inputs):
        return pd.DataFrame({"y": 2 * self._require(inputs, ["x"])["x"]}, index=index)


def constant(**values: float) -> ConstantSource:
    return ConstantSource(ConstantParams(name="c", values=values))


@pytest.mark.spec("SRC-001")
def test_source_contract():
    assert issubclass(ConstantSource, Source)
    with pytest.raises(TypeError):
        Source(DoubleParams(name="s"))  # type: ignore[abstract]
    src = Double(DoubleParams(name="d"))
    assert src.name == "d" and Double.params_model is DoubleParams
    out = src.simulate(HOURS, pd.DataFrame({"x": 1.0}, index=HOURS))
    assert out.index.equals(HOURS) and (out["y"] == 2).all()


@pytest.mark.spec("SRC-001")
def test_source_checks_time_axis():
    src = Double(DoubleParams(name="d"))
    with pytest.raises(TimeGridError):
        src.simulate(pd.date_range("2026-06-21", periods=3, freq="h"))  # not UTC
    with pytest.raises(TimeGridError):
        src.simulate(HOURS, pd.DataFrame({"x": 1.0}, index=HOURS[:12]))  # inputs off the axis


@pytest.mark.spec("SRC-002")
def test_missing_input_names_source_and_columns():
    src = Double(DoubleParams(name="d"))
    for inputs in (None, pd.DataFrame({"z": 1.0}, index=HOURS)):
        with pytest.raises(MissingInputError, match="d.*x") as e:
            src.simulate(HOURS, inputs)
        assert e.value.box == "d"
    assert issubclass(MissingInputError, ValueError)


@pytest.mark.spec("SRC-005")
def test_constant_source():
    out = constant(fuel_kw=1500, x=2).simulate(HOURS)
    assert list(out.columns) == ["fuel_kw", "x"] and out.index.equals(HOURS)
    assert (out["fuel_kw"] == 1500).all() and (out["x"] == 2).all()
    assert CombustionInputs.from_frame(out).fuel_kw.eq(1500).all()  # test fuel for an engine


@pytest.mark.spec("SRC-005")
@pytest.mark.parametrize("values", [{}, {"x": float("nan")}, {"x": float("inf")}])
def test_constant_rejects(values):
    with pytest.raises(ValidationError):
        ConstantParams(name="c", values=values)
