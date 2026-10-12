"""Sources in the library, spec 0016 (SRC-001..006)."""

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

import kiozesim
from kiozesim import MissingInputError
from kiozesim.plants.chp import CHPInputs
from kiozesim.sources import ConstantParams, ConstantSource, Source
from kiozesim.sources.digester import Digester, DigesterParams, Substrate
from kiozesim.timegrid import TimeGridError

HOURS = pd.date_range("2026-06-21", periods=24, freq="h", tz="UTC")
LIB = Path(kiozesim.__file__).resolve().parent


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
    assert issubclass(ConstantSource, Source) and issubclass(Digester, Source)
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


@pytest.mark.spec("SRC-003")
def test_from_frame_names_missing_fields():
    with pytest.raises(MissingInputError, match="fuel_kw") as e:
        CHPInputs.from_frame(pd.DataFrame({"ghi_w_m2": 1.0}, index=HOURS))
    assert e.value.missing == ("fuel_kw",)


@pytest.mark.spec("SRC-004")
def test_digester_is_source_without_inputs():
    sub = Substrate(
        name="maize silage",
        fresh_t_per_day=40,
        dry_matter_frac=0.33,
        organic_frac=0.95,
        formula="C6H10O5",
        biodegradability=0.8,
    )
    out = Digester(DigesterParams(name="farm", substrates=(sub,))).simulate(HOURS)
    assert list(out.columns) == ["fuel_kw", "methane_nm3_per_h"]
    np.testing.assert_allclose(out["fuel_kw"], 1728.3, rtol=0.001)


@pytest.mark.spec("SRC-005")
def test_constant_source():
    out = constant(fuel_kw=1500, x=2).simulate(HOURS)
    assert list(out.columns) == ["fuel_kw", "x"] and out.index.equals(HOURS)
    assert (out["fuel_kw"] == 1500).all() and (out["x"] == 2).all()
    assert CHPInputs.from_frame(out).fuel_kw.eq(1500).all()  # a test fuel for a gas engine


@pytest.mark.spec("SRC-005")
@pytest.mark.parametrize("values", [{}, {"x": float("nan")}, {"x": float("inf")}])
def test_constant_rejects(values):
    with pytest.raises(ValidationError):
        ConstantParams(name="c", values=values)


@pytest.mark.spec("SRC-006")
def test_library_has_no_wiring_and_no_app_imports():
    forbidden = ("kiozesim_tool",)
    for py in LIB.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not any(n.split(".")[0] in forbidden for n in names), py
    assert not (LIB / "wiring.py").exists() and not (LIB / "sources" / "wiring.py").exists()
