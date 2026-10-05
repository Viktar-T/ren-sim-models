"""The harness itself, exercised with a throwaway plant and a generated golden case."""

import pandas as pd
import pytest
import yaml
from pydantic import BaseModel

from kioze_sim.datasheet import Datasheet
from kioze_sim.plants.base import Plant, PlantOutput, PlantParams, TimeSeries
from tests.harness import discover, run_case


class DS(Datasheet):
    rated_kw: float


class Params(PlantParams):
    datasheet: DS
    scale: float


class DInputs(TimeSeries):
    wind_speed: pd.Series


class Doubler(Plant[Params, DInputs, PlantOutput]):
    params_model = Params
    inputs_model = DInputs

    def _simulate(self, ts):
        return PlantOutput(power_kw=ts.wind_speed * self.params.scale)


def _make_case(root, expected_factor):
    d = root / "doubler" / "c1"
    d.mkdir(parents=True)
    idx = pd.date_range("2025-01-01", periods=4, freq="h", tz="UTC", name="time")
    pd.DataFrame({"wind_speed": [1.0, 2.0, 3.0, 4.0]}, index=idx).to_csv(d / "inputs.csv")
    pd.DataFrame({"power_kw": [2.0, 4.0, 6.0, 8.0]}, index=idx).mul(expected_factor).to_csv(
        d / "expected.csv"
    )
    (d / "ds.yaml").write_text("manufacturer: m\nmodel: x\nrated_kw: 1\n")
    (d / "case.yaml").write_text(
        yaml.safe_dump(
            {"params": {"name": "d", "scale": 2.0}, "datasheet": "ds.yaml", "rtol": 0.01}
        )
    )
    return d


@pytest.mark.spec("CORE-007")
def test_harness_passes_and_fails(tmp_path):
    _make_case(tmp_path, 1.0)
    (case,) = discover(tmp_path)
    reg = {"doubler": Doubler}
    run_case(case, reg)
    _make_case(tmp_path / "bad", 1.5)
    (bad,) = discover(tmp_path / "bad")
    with pytest.raises(AssertionError):
        run_case(bad, reg)


@pytest.mark.spec("CORE-007")
def test_discover_empty(tmp_path):
    assert discover(tmp_path) == []


@pytest.mark.spec("CORE-008")
@pytest.mark.parametrize("name", ["pv", "hawt", "vawt", "biogas", "boiler"])
def test_every_plant_has_module_with_contract(name):
    from kioze_sim.plants import REGISTRY

    cls = REGISTRY[name]
    assert issubclass(cls, Plant) and issubclass(cls.params_model, PlantParams)
    assert issubclass(cls.params_model.model_fields["datasheet"].annotation, Datasheet)
    assert issubclass(cls.params_model, BaseModel)


class Steady(Plant[Params, None, PlantOutput]):
    params_model = Params

    def _simulate(self, ts):
        return PlantOutput(power_kw=self.params.scale * 10)


@pytest.mark.spec("CORE-007")
def test_harness_steady_state_case(tmp_path):
    d = tmp_path / "steady" / "c1"
    d.mkdir(parents=True)
    (d / "ds.yaml").write_text("manufacturer: m\nmodel: x\nrated_kw: 1\n")
    (d / "case.yaml").write_text(
        yaml.safe_dump(
            {
                "params": {"name": "s", "scale": 2.0},
                "datasheet": "ds.yaml",
                "expected_power_kw": 20.0,
            }
        )
    )
    (case,) = discover(tmp_path)
    run_case(case, {"steady": Steady})
    (d / "case.yaml").write_text(
        yaml.safe_dump(
            {
                "params": {"name": "s", "scale": 2.0},
                "datasheet": "ds.yaml",
                "expected_power_kw": 99.0,
            }
        )
    )
    with pytest.raises(AssertionError):
        run_case(case, {"steady": Steady})
