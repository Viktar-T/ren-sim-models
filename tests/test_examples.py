import re
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

import pandas as pd
import pytest

from kioze_sim.plants.pv import PVDatasheet

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
PV = EXAMPLES / "pv.py"
needs_pvlib = pytest.mark.skipif(find_spec("pvlib") is None, reason="needs the 'pv' extra")


@pytest.fixture(scope="module")
def pv_run(tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess[str]:
    # run from an unrelated directory: the script must find its CSV by itself (EX-005)
    cwd = tmp_path_factory.mktemp("cwd")
    return subprocess.run(
        [sys.executable, str(PV)], cwd=cwd, capture_output=True, text=True, timeout=120
    )


@pytest.mark.spec("EX-001")
def test_examples_folder_is_flat() -> None:
    entries = [p for p in EXAMPLES.iterdir() if p.name != "__pycache__"]
    assert entries
    assert all(p.is_file() for p in entries)
    assert not (EXAMPLES / "__init__.py").exists()


@needs_pvlib
@pytest.mark.spec("EX-002")
def test_pv_example_runs(pv_run: subprocess.CompletedProcess[str]) -> None:
    assert pv_run.returncode == 0, pv_run.stderr


@pytest.mark.spec("EX-003")
def test_pv_example_uses_public_api_only() -> None:
    imports = re.findall(r"^\s*(?:from|import)\s+([\w.]+)", PV.read_text(), re.M)
    ours = [m for m in imports if m.split(".")[0] == "kioze_sim"]
    assert ours
    assert all(m in {"kioze_sim", "kioze_sim.plants.pv"} for m in ours), ours


@pytest.mark.spec("EX-004")
def test_pv_example_loads_bundled_datasheet() -> None:
    src = PV.read_text()
    m = re.search(r'PVDatasheet\.bundled\("(\w+)"\)', src)
    assert m and m.group(1) in PVDatasheet.available()
    assert "from_yaml" not in src and '"datasheets"' not in src


@pytest.mark.spec("EX-005")
def test_pv_weather_csv_shape() -> None:
    assert "pv_weather.csv" in PV.read_text()
    df = pd.read_csv(EXAMPLES / "pv_weather.csv", index_col="time", parse_dates=True)
    assert list(df.columns) == ["ghi_w_m2", "temp_air_c", "wind_speed_m_s"]
    assert len(df) == 24
    assert str(df.index.tz) == "UTC"
    assert (df.index.to_series().diff().dropna() == pd.Timedelta(hours=1)).all()


@needs_pvlib
@pytest.mark.spec("EX-006")
def test_pv_example_prints_power_and_total(pv_run: subprocess.CompletedProcess[str]) -> None:
    out = pv_run.stdout
    assert out.count(" kW") >= 24
    total = re.search(r"Total.*?([\d.]+) kWh", out)
    assert total is not None
    assert 5 < float(total.group(1)) < 40  # ~4 kWp on a sunny June day: sensible, not validated


@pytest.mark.spec("EX-007")
def test_pv_example_is_short_and_commented() -> None:
    lines = PV.read_text().splitlines()
    assert len(lines) <= 80
    assert sum(line.lstrip().startswith("#") for line in lines) >= 5
