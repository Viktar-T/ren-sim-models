"""What spec 0016 still asks of the library: input errors, no sources, no app imports."""

import ast
from pathlib import Path

import pandas as pd
import pytest

import kiozesim
from kiozesim import MissingInputError
from kiozesim.plants.combustion import CombustionInputs

HOURS = pd.date_range("2026-06-21", periods=24, freq="h", tz="UTC")
LIB = Path(kiozesim.__file__).resolve().parent


@pytest.mark.spec("SRC-003")
def test_from_frame_names_missing_fields():
    with pytest.raises(MissingInputError, match="fuel_kw") as e:
        CombustionInputs.from_frame(pd.DataFrame({"ghi_w_m2": 1.0}, index=HOURS))
    assert e.value.missing == ("fuel_kw",)
    assert issubclass(MissingInputError, ValueError)


@pytest.mark.spec("SRC-006")
@pytest.mark.spec("CHAIN-014")
@pytest.mark.spec("CHAIN-025")
def test_library_has_no_sources_and_no_app_imports():
    for py in LIB.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not any(n.split(".")[0] == "kiozesim_tool" for n in names), py
            # no file reading or fetching in the library's chain code (CHAIN-014)
            if py.name == "chain.py":
                assert not any(n.split(".")[0] in {"urllib", "requests", "httpx"} for n in names)
                if isinstance(node, ast.Call):
                    func = getattr(node.func, "id", getattr(node.func, "attr", ""))
                    assert func not in {"open", "read_csv", "read_text", "urlopen"}, py
    assert not (LIB / "sources").exists() and not (LIB / "wiring.py").exists()
    assert not hasattr(kiozesim, "Source")
