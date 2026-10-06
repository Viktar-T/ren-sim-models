"""Golden-dataset validation harness shared by all plants."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from kiozesim.plants import REGISTRY
from kiozesim.plants.base import Plant

GOLDEN_DIR = Path(__file__).parent / "golden"


@dataclass(frozen=True)
class GoldenCase:
    plant: str
    path: Path

    @property
    def id(self) -> str:
        return f"{self.plant}/{self.path.name}"


def discover(root: Path = GOLDEN_DIR) -> list[GoldenCase]:
    return [GoldenCase(p.parent.parent.name, p.parent) for p in sorted(root.glob("*/*/case.yaml"))]


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, index_col="time", parse_dates=["time"]).tz_convert("UTC")


def build_plant(case: GoldenCase, registry: dict[str, type[Plant]] | None = None) -> Plant:  # type: ignore[type-arg]
    cls = (registry or REGISTRY)[case.plant]
    spec = yaml.safe_load((case.path / "case.yaml").read_text())
    ds_name = spec["datasheet"]
    ds_path = case.path / ds_name
    ds_model = cls.params_model.model_fields["datasheet"].annotation
    if ds_path.exists():
        datasheet = ds_model.from_yaml(ds_path)  # type: ignore[union-attr]
    else:  # a bundled datasheet name, e.g. "jinko_solar_jkm440n_54hl4r_b"
        datasheet = ds_model.bundled(ds_name)  # type: ignore[union-attr]
    return cls(cls.params_model(datasheet=datasheet, **spec["params"]))


def run_case(case: GoldenCase, registry: dict[str, type[Plant]] | None = None) -> None:  # type: ignore[type-arg]
    """Simulate the case and assert it matches expected.csv within tolerance."""
    spec = yaml.safe_load((case.path / "case.yaml").read_text())
    spec_inputs = spec.get("inputs", {})
    plant = build_plant(case, registry)
    if plant.inputs_model is None:  # steady-state plant: scalar expectation in case.yaml
        actual = plant.simulate().power_kw
        np.testing.assert_allclose(
            actual,
            spec["expected_power_kw"],
            rtol=spec.get("rtol", 0.02),
            atol=spec.get("atol", 0.1),
        )
        return
    frame = _read_csv(case.path / "inputs.csv")
    actual = plant.simulate(plant.inputs_model.from_frame(frame, **spec_inputs)).power_kw
    if "expected_energy_kwh" in spec:  # total-energy case (e.g. annual yield): no expected.csv
        step_h = (frame.index[1] - frame.index[0]) / pd.Timedelta(hours=1)
        np.testing.assert_allclose(
            float(np.sum(actual)) * step_h,
            spec["expected_energy_kwh"],
            rtol=spec.get("rtol", 0.02),
            atol=spec.get("atol", 0.1),
            err_msg=f"golden case {case.id} energy (source: {spec.get('source', 'n/a')})",
        )
        return
    expected = _read_csv(case.path / "expected.csv")["power_kw"]
    np.testing.assert_allclose(
        np.asarray(actual),
        expected.to_numpy(),
        rtol=spec.get("rtol", 0.02),
        atol=spec.get("atol", 0.1),
        err_msg=f"golden case {case.id} (source: {spec.get('source', 'n/a')})",
    )
