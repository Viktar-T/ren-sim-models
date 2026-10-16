"""Spec 0017: one app package, `kiozesim-tool ui`, one shared type list and builder."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import uvicorn

import kiozesim_tool
from kiozesim.plants.pv import PVDatasheet, PVPlant
from kiozesim_tool import boxes, cli, config
from kiozesim_tool.sources import ConstantSource
from kiozesim_tool.ui import form
from kiozesim_tool.ui.app import app

PKG = Path(kiozesim_tool.__file__).resolve().parent
ROOT = PKG.parents[2]
PV = {
    "name": "roof",
    "datasheet": "jinko_solar_jkm440n_54hl4r_b",
    "latitude_deg": 52.23,
    "longitude_deg": 21.01,
    "tilt_deg": 35,
    "azimuth_deg": 180,
    "n_modules": 10,
    "inverter_ac_kw": 4.0,
}


@pytest.mark.spec("APP-001")
def test_two_packages_and_no_old_imports() -> None:
    root = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert root["tool"]["uv"]["workspace"]["members"] == ["kiozesim", "kiozesim-tool"]
    assert not (ROOT / "kiozesim-ui").exists() and not (ROOT / "kiozesim-utils").exists()
    for folder in ("kiozesim", "kiozesim-tool", "scripts"):
        for py in (ROOT / folder).rglob("*.py"):
            imports = re.findall(r"^\s*(?:from|import) ([\w.]+)", py.read_text(), re.M)
            assert not {m.split(".")[0] for m in imports} & {"kiozesim_ui", "kiozesim_utils"}, py


@pytest.mark.spec("APP-002")
def test_layout_inside_the_tool() -> None:
    for name in ("wiring.py", "weather.py", "boxes.py", "ui/app.py", "ui/form.py", "ui/chart.py"):
        assert (PKG / name).is_file(), name
    for name in ("templates/page.html", "static/style.css", "sample_weather.csv"):
        assert (PKG / "ui" / name).is_file(), name


@pytest.mark.spec("APP-003")
def test_ui_subcommand_starts_server(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, str, int]] = []
    monkeypatch.setattr(uvicorn, "run", lambda a, host, port: calls.append((a, host, port)))
    assert cli.main(["ui"]) == 0
    assert cli.main(["ui", "--host", "0.0.0.0", "--port", "9000"]) == 0
    assert calls == [(app, "127.0.0.1", 8000), (app, "0.0.0.0", 9000)]
    cfg = tomllib.loads((ROOT / "kiozesim-tool" / "pyproject.toml").read_text())
    assert cfg["project"]["scripts"] == {"kiozesim-tool": "kiozesim_tool.cli:main"}


@pytest.mark.spec("APP-004")
def test_web_dependencies_always_installed() -> None:
    cfg = tomllib.loads((ROOT / "kiozesim-tool" / "pyproject.toml").read_text())
    deps = {re.split(r"[<>=\[]", d)[0] for d in cfg["project"]["dependencies"]}
    assert {"fastapi", "uvicorn", "jinja2", "python-multipart", "matplotlib"} <= deps
    assert "optional-dependencies" not in cfg["project"]


@pytest.mark.spec("APP-005")
def test_config_and_form_share_the_type_lists() -> None:
    assert form.OFFERED == tuple(boxes.PLANTS)
    assert {t for t, _ in form.SOURCE_TYPES.values()} == set(boxes.SOURCES)
    for module in (config, form):
        text = Path(module.__file__ or "").read_text()
        assert "REGISTRY" not in text and ".bundled(" not in text, module


@pytest.mark.spec("APP-005")
def test_build_plant_loads_bundled_datasheet() -> None:
    plant = boxes.build_plant("pv", PV)
    assert isinstance(plant, PVPlant) and isinstance(plant.params.datasheet, PVDatasheet)
    with pytest.raises(ValueError, match="no bundled datasheet 'nope'"):
        boxes.build_plant("pv", {**PV, "datasheet": "nope"})
    with pytest.raises(ValueError, match="unknown plant type"):
        boxes.build_plant("boiler", PV)  # a boiler is a combustion plant (0019)


@pytest.mark.spec("APP-005")
def test_resolve_reports_errors_per_field() -> None:
    model = boxes.PLANTS["pv"].params_model
    data, errors = boxes.resolve(model, {**PV, "datasheet": "nope"})
    assert "datasheet" not in data and errors == {"datasheet": "no bundled datasheet 'nope'"}


@pytest.mark.spec("APP-005")
def test_build_source_by_type() -> None:
    src = boxes.build_source("constant", {"name": "fuel", "values": {"fuel_kw": 1500}})
    assert isinstance(src, ConstantSource)
    with pytest.raises(ValueError, match="unknown source type"):
        boxes.build_source("nope", {"name": "x"})


@pytest.mark.spec("APP-006")
def test_moved_tests_run_with_the_tool() -> None:
    """The UI and utils tests moved here unchanged apart from imports and paths; they pass in
    the same run as this one."""
    tests = ROOT / "kiozesim-tool" / "tests"
    for name in ("test_ui.py", "test_weather.py", "test_wiring.py", "test_sink.py", "test_mqtt.py"):
        assert (tests / name).is_file(), name
    assert not (tests / "__init__.py").exists()  # REPO-010
