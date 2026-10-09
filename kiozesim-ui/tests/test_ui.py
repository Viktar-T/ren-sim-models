"""Specs 0010 and 0014: the server-side rendered web UI and its datasheet import, tested through
FastAPI's TestClient."""

from __future__ import annotations

import base64
import re
import tomllib
from pathlib import Path

import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

import kiozesim_ui
from kiozesim.plants.hawt import HAWTDatasheet
from kiozesim.plants.pv import PVDatasheet, PVInputs, PVParams, PVPlant
from kiozesim.plants.vawt import VAWTDatasheet
from kiozesim_ui import __main__ as cli
from kiozesim_ui import form
from kiozesim_ui.app import app

PKG = Path(kiozesim_ui.__file__).resolve().parent
ROOT = PKG.parents[2]
SPECS = ROOT / "specs"
# spec prefix -> plant type key in kiozesim.plants.REGISTRY
PREFIX_TO_TYPE = {"PV": "pv", "WIND": "hawt", "VAWT": "vawt", "BIO": "biogas", "BOIL": "boiler"}

client = TestClient(app)

PV_BOX = {
    "type": "pv",
    "shown_type": "pv",
    "datasheet": "jinko_solar_jkm440n_54hl4r_b",
    "latitude_deg": "52.23",
    "longitude_deg": "21.01",
    "altitude_m": "119",
    "tilt_deg": "35",
    "azimuth_deg": "180",
    "n_modules": "10",
    "inverter_ac_kw": "4.0",
    "inverter_efficiency": "0.96",
    "losses_pct": "14",
    "albedo": "0.2",
    "mounting": "open_rack_glass_polymer",
}


Upload = tuple[str, bytes, str]  # (file name, content, media type), as httpx posts a file

HAWT_BOX = {
    "type": "hawt",
    "shown_type": "hawt",
    "datasheet": "E-82/2300",
    "hub_height_m": "108",
    "n_turbines": "1",
    "wind_height_m": "10",
    "roughness_length_m": "0.1",
    "temp_height_m": "2",
    "density_correction": "true",
    "losses_pct": "10",
}


VAWT_BOX = HAWT_BOX | {
    "type": "vawt",
    "shown_type": "vawt",
    "datasheet": "mariah_power_windspire",
    "hub_height_m": "10",
}


def post(action: str, *boxes: dict[str, str], files: dict[str, Upload] | None = None) -> str:
    data = {"action": action, "n": str(len(boxes))}
    for i, box in enumerate(boxes):
        data |= {f"p{i}.{k}": v for k, v in box.items()}
    r = client.post("/", data=data, files=files)
    assert r.status_code == 200
    return r.text


def pv(name: str, **changes: str) -> dict[str, str]:
    return PV_BOX | {"name": name} | changes


def hawt(name: str, **changes: str) -> dict[str, str]:
    box = HAWT_BOX | {"name": name} | changes
    return {k: v for k, v in box.items() if v is not None}


def vawt(name: str, **changes: str) -> dict[str, str]:
    return VAWT_BOX | {"name": name} | changes


def checked(html: str, name: str) -> bool:
    el = tag(html, name)
    assert 'type="checkbox"' in el, el
    return " checked" in el


def boxes(html: str) -> int:
    return html.count('<fieldset class="plant"')


def tag(html: str, name: str) -> str:
    """The <input>/<select> element (with its options) named `name`."""
    m = re.search(rf'<(input|select)[^>]*name="{re.escape(name)}"[^>]*>(.*?</select>)?', html, re.S)
    assert m, f"no field {name}"
    return m.group(0)


def value(html: str, name: str) -> str:
    el = tag(html, name)
    if el.startswith("<select"):
        m = re.search(r'<option value="([^"]*)" selected', el)
        return m.group(1) if m else ""
    m = re.search(r'value="([^"]*)"', el)
    return m.group(1) if m else ""


def options(html: str, name: str) -> list[str]:
    return re.findall(r'<option value="([^"]*)"', tag(html, name))


def error(html: str, name: str) -> str:
    m = re.search(rf'<span class="error" data-for="{re.escape(name)}">([^<]*)</span>', html)
    return m.group(1) if m else ""


def energy(html: str, plant: str) -> float:
    m = re.search(rf'<td data-energy-kwh="{re.escape(plant)}">([\d.]+)</td>', html)
    assert m, f"no energy for {plant}"
    return float(m.group(1))


def library_kwh(name: str) -> float:
    w = pd.read_csv(PKG / "sample_weather.csv", index_col="time", parse_dates=True)
    params = PVParams(
        name=name,
        datasheet=PVDatasheet.bundled(PV_BOX["datasheet"]),
        latitude_deg=52.23,
        longitude_deg=21.01,
        altitude_m=119,
        tilt_deg=35,
        azimuth_deg=180,
        n_modules=10,
        inverter_ac_kw=4.0,
    )
    power = PVPlant(params).simulate(PVInputs.from_frame(w)).power_kw
    assert isinstance(power, pd.Series)
    return float(power.sum()) * 1.0  # hourly steps


def status(spec: Path) -> tuple[str, str]:
    front = spec.read_text().split("---")[1]
    fm = dict(line.split(":", 1) for line in front.strip().splitlines())
    return fm["prefix"].split("#")[0].strip(), fm["status"].split("#")[0].strip()


@pytest.fixture(scope="module")
def run_two() -> str:
    return post("run", pv("roof-a"), pv("roof-b", n_modules="20", inverter_ac_kw="8"))


# --- page -------------------------------------------------------------------------------------


@pytest.mark.spec("UI-001")
def test_server_renders_page_from_templates() -> None:
    assert (PKG / "templates" / "page.html").is_file()
    first = client.get("/")
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("text/html")
    assert '<form method="post" action="/" enctype="multipart/form-data">' in first.text
    # every button press is a form post answered with a whole new page
    assert "<html" in post("add", pv("pv-1"))


@pytest.mark.spec("UI-002")
def test_nothing_loaded_from_outside() -> None:
    files = [*(PKG / "templates").rglob("*"), *(PKG / "static").rglob("*")]
    for f in (f for f in files if f.is_file()):
        text = f.read_text()
        assert not re.search(r"(https?:)?//[\w.-]+\.\w", text), f
    page = client.get("/").text
    for ref in re.findall(r'(?:src|href)="([^"]*)"', page):
        assert ref.startswith("/static/"), ref
    assert client.get("/static/style.css").status_code == 200


@pytest.mark.spec("UI-003")
def test_plain_native_look() -> None:
    css = (PKG / "static" / "style.css").read_text()
    assert "system-ui" in css
    assert "animation" not in css and "transition" not in css
    page = client.get("/").text
    assert boxes(page) == 1
    assert "<img" not in page


# --- plants on the page ------------------------------------------------------------------------


@pytest.mark.spec("UI-004")
def test_plus_adds_a_box_and_keeps_values() -> None:
    assert boxes(client.get("/").text) == 1
    page = post("add", pv("mine", tilt_deg="12"))
    assert boxes(page) == 2
    assert value(page, "p0.name") == "mine"
    assert value(page, "p0.tilt_deg") == "12"
    assert value(page, "p0.mounting") == "open_rack_glass_polymer"
    assert "+</button>" in page


@pytest.mark.spec("UI-019")
def test_remove_drops_one_box_and_keeps_the_rest() -> None:
    assert 'value="remove:' not in client.get("/").text  # one box: nothing to remove
    page = post("remove:1", pv("a", tilt_deg="11"), pv("b"), hawt("c", hub_height_m="99"))
    assert boxes(page) == 2
    assert value(page, "p0.name") == "a" and value(page, "p0.tilt_deg") == "11"
    assert value(page, "p1.name") == "c" and value(page, "p1.hub_height_m") == "99"
    assert 'value="remove:0"' in page and 'value="remove:1"' in page
    last = post("remove:0", pv("a"), pv("b"))
    assert boxes(last) == 1 and value(last, "p0.name") == "b"
    assert 'value="remove:' not in last
    assert boxes(post("remove:0", pv("only"))) == 1  # the last box stays
    assert "data-energy-kwh" not in page


@pytest.mark.spec("UI-005")
def test_type_selector_lists_implemented_types() -> None:
    implemented = {
        PREFIX_TO_TYPE[prefix]
        for prefix, st in map(status, SPECS.glob("[0-9]*/spec.md"))
        if prefix in PREFIX_TO_TYPE and st == "implemented"
    }
    assert set(form.OFFERED) == implemented
    assert set(options(client.get("/").text, "p0.type")) == implemented
    assert 'value="apply"' in client.get("/").text


@pytest.mark.spec("UI-005")
def test_changed_type_is_redrawn_and_not_simulated() -> None:
    # the box was drawn for another type: its fields are redrawn with pv defaults, no run
    page = post("run", pv("x", shown_type="hawt", tilt_deg="33"))
    assert value(page, "p0.tilt_deg") == ""
    assert value(page, "p0.shown_type") == "pv"
    assert "data-energy-kwh" not in page


@pytest.mark.spec("UI-006")
def test_fields_come_from_params_model() -> None:
    page = client.get("/").text
    labels = set(re.findall(r'<label for="p0\.(\w+)">(\w+)</label>', page))
    shown = labels - {("type", "type"), ("upload", "import")}  # the import row is spec 0014
    assert shown == {(f, f) for f in PVParams.model_fields}
    assert value(page, "p0.altitude_m") == "0.0"
    assert value(page, "p0.losses_pct") == "14.0"
    assert value(page, "p0.inverter_efficiency") == "0.96"
    assert value(page, "p0.mounting") == "open_rack_glass_polymer"
    assert value(page, "p0.tilt_deg") == ""  # no default


@pytest.mark.spec("UI-007")
def test_ranges_and_choices() -> None:
    page = client.get("/").text
    tilt = tag(page, "p0.tilt_deg")
    assert 'type="number"' in tilt and 'min="0"' in tilt and 'max="90"' in tilt
    lat = tag(page, "p0.latitude_deg")
    assert 'min="-90"' in lat and 'max="90"' in lat
    assert 'step="1"' in tag(page, "p0.n_modules")
    assert options(page, "p0.mounting") == [
        "open_rack_glass_polymer",
        "open_rack_glass_glass",
        "close_mount_glass_glass",
        "insulated_back_glass_polymer",
    ]


@pytest.mark.spec("UI-007")
def test_yes_no_field_is_a_checkbox() -> None:
    page = post("apply", {"type": "hawt", "shown_type": "pv", "name": "t"})
    assert checked(page, "p0.density_correction")  # default true
    # an unticked box is not posted at all; it must stay unticked on the next page
    unticked = hawt("t")
    del unticked["density_correction"]
    page = post("add", unticked)
    assert not checked(page, "p0.density_correction")
    assert checked(post("add", hawt("t")), "p0.density_correction")


@pytest.mark.spec("UI-008")
def test_datasheet_dropdown() -> None:
    assert options(client.get("/").text, "p0.datasheet") == PVDatasheet.available()
    page = post("apply", {"type": "hawt", "shown_type": "pv", "name": "t"})
    assert options(page, "p0.datasheet") == HAWTDatasheet.available()
    page = post("apply", {"type": "vawt", "shown_type": "pv", "name": "v"})
    assert options(page, "p0.datasheet") == VAWTDatasheet.available()


@pytest.mark.spec("UI-009")
def test_new_box_gets_unused_name() -> None:
    assert value(client.get("/").text, "p0.name") == "pv-1"
    assert value(post("add", pv("pv-1")), "p1.name") == "pv-2"
    page = post("add", pv("pv-2"), pv("pv-1"))
    assert value(page, "p2.name") == "pv-3"


# --- running -----------------------------------------------------------------------------------


@pytest.mark.spec("UI-010")
def test_one_run_button_runs_all_plants(run_two: str) -> None:
    assert client.get("/").text.count('value="run"') == 1
    assert energy(run_two, "roof-a") > 0
    assert energy(run_two, "roof-b") > 0


@pytest.mark.spec("UI-011")
def test_sample_weather_has_every_column_and_a_breeze() -> None:
    w = pd.read_csv(PKG / "sample_weather.csv", index_col="time", parse_dates=True)
    assert {"ghi_w_m2", "temp_air_c", "wind_speed_m_s", "pressure_hpa"} <= set(w.columns)
    assert len(w) == 24 and (w.index[1] - w.index[0]) == pd.Timedelta("1h")
    assert w["wind_speed_m_s"].min() >= 3.5 and w["wind_speed_m_s"].max() <= 10.5
    assert w["wind_speed_m_s"].mean() >= 5


@pytest.mark.spec("UI-010")
@pytest.mark.spec("UI-011")
def test_pv_and_turbine_run_together() -> None:
    page = post("run", pv("roof"), hawt("turbine", n_turbines="2"))
    assert energy(page, "turbine") > 1000  # an E-82 on a breezy day, 2 of them
    assert energy(page, "total") == pytest.approx(
        energy(page, "roof") + energy(page, "turbine"), abs=0.01
    )


@pytest.mark.spec("UI-010")
@pytest.mark.parametrize("datasheet", VAWTDatasheet.available())
def test_pv_turbine_and_vawt_run_together(datasheet: str) -> None:
    page = post("run", pv("roof"), hawt("turbine"), vawt("vawt", datasheet=datasheet))
    assert energy(page, "vawt") > 0
    assert energy(page, "total") == pytest.approx(
        energy(page, "roof") + energy(page, "turbine") + energy(page, "vawt"), abs=0.01
    )


@pytest.mark.spec("UI-012")
def test_result_equals_library(run_two: str) -> None:
    assert energy(run_two, "roof-a") == pytest.approx(library_kwh("roof-a"), abs=0.01)
    for f in PKG.rglob("*.py"):
        assert "pvlib" not in f.read_text(), f


@pytest.mark.spec("UI-013")
def test_bad_value_shown_next_to_field() -> None:
    page = post("run", pv("a", tilt_deg="100"), pv("b", n_modules=""))
    assert error(page, "p0.tilt_deg")
    assert error(page, "p1.n_modules")
    assert not error(page, "p0.azimuth_deg")
    assert value(page, "p0.tilt_deg") == "100"
    assert value(page, "p1.azimuth_deg") == "180"
    assert "data-energy-kwh" not in page


@pytest.mark.spec("UI-018")
def test_box_level_error_at_top_of_box() -> None:
    page = post("run", pv("roof"), hawt("t", roughness_length_m="20"))
    m = re.search(r'<p class="error" data-for="p1">([^<]*)</p>', page)
    assert m and "roughness_length_m" in m.group(1)
    assert not error(page, "p1.name")
    assert '<p class="error" data-for="p0">' not in page
    assert value(page, "p1.roughness_length_m") == "20"
    assert "data-energy-kwh" not in page


@pytest.mark.spec("UI-013")
def test_duplicate_names_rejected() -> None:
    page = post("run", pv("same"), pv("same"))
    assert error(page, "p1.name")
    assert "data-energy-kwh" not in page


# --- result ------------------------------------------------------------------------------------


@pytest.mark.spec("UI-014")
def test_energy_per_plant_and_total(run_two: str) -> None:
    total = energy(run_two, "total")
    assert total == pytest.approx(energy(run_two, "roof-a") + energy(run_two, "roof-b"), abs=0.01)


@pytest.mark.spec("UI-015")
def test_chart_is_server_svg(run_two: str) -> None:
    m = re.search(r'<div class="chart">\s*(<svg.*?</svg>)', run_two, re.S)
    assert m
    svg = m.group(1)
    for name in ("roof-a", "roof-b", "total"):
        assert name in svg
    assert "<script" not in run_two


# --- server ------------------------------------------------------------------------------------


@pytest.mark.spec("UI-016")
def test_command_starts_server(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tomllib.loads((ROOT / "kiozesim-ui" / "pyproject.toml").read_text())
    assert cfg["project"]["scripts"]["kiozesim-ui"] == "kiozesim_ui.__main__:main"
    calls: list[tuple[object, str, int]] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda a, host, port: calls.append((a, host, port)))
    cli.main([])
    cli.main(["--host", "0.0.0.0", "--port", "9000"])
    assert calls == [(app, "127.0.0.1", 8000), (app, "0.0.0.0", 9000)]


@pytest.mark.spec("UI-017")
def test_only_public_library_api() -> None:
    for f in PKG.rglob("*.py"):
        for mod in re.findall(r"^\s*(?:from|import) (kiozesim[\w.]*)", f.read_text(), re.M):
            assert not any(part.startswith("_") for part in mod.split(".")), (f, mod)


# --- datasheet import (spec 0014) --------------------------------------------------------------

# Same values as the bundled jinko_solar_jkm440n_54hl4r_b, under another name and with no source.
PV_SHEET = "manufacturer: Acme\nmodel: X-440\npdc0_w: 440\ngamma_pdc_per_k: -0.0029\n"


def upload(content: str | bytes, box: int = 0, filename: str = "sheet.yaml") -> dict[str, Upload]:
    data = content.encode() if isinstance(content, str) else content
    return {f"p{box}.upload": (filename, data, "application/x-yaml")}


def imported(page: str, box: int = 0) -> dict[str, str]:
    """What the browser posts back for a box holding an import: the hidden field, entry selected."""
    return {"imported": value(page, f"p{box}.imported"), "datasheet": form.UPLOADED}


def label(page: str, name: str) -> str:
    m = re.search(r"<option [^>]*selected>([^<]*)</option>", tag(page, name))
    return m.group(1) if m else ""


def copy_of(sheet: type[HAWTDatasheet | VAWTDatasheet], name: str) -> str:
    """A bundled datasheet as a user's YAML file, renamed."""
    return yaml.safe_dump(sheet.bundled(name).model_dump(exclude_none=True) | {"model": "copy"})


@pytest.mark.spec("IMP-001")
def test_each_box_has_file_picker_and_import_button() -> None:
    page = post("add", pv("a"))
    assert '<form method="post" action="/" enctype="multipart/form-data">' in page
    for i in (0, 1):
        picker = tag(page, f"p{i}.upload")
        assert 'type="file"' in picker and 'accept=".yaml,.yml"' in picker
        assert f'<button type="submit" name="action" value="import:{i}">Import</button>' in page
    page = post("import:0", pv("a"), files=upload(PV_SHEET))
    assert value(page, "p0.datasheet") == form.UPLOADED
    assert "data-energy-kwh" not in page  # importing runs nothing


@pytest.mark.spec("IMP-002")
def test_file_checked_with_the_selected_types_model() -> None:
    page = post("import:0", pv("a"), files=upload(PV_SHEET))  # no `source`: fine
    assert not error(page, "p0.upload")
    assert label(page, "p0.datasheet") == "uploaded: Acme X-440"
    page = post("import:0", hawt("t"), files=upload(PV_SHEET))  # a PV module is no turbine
    assert "rated_power_kw: Field required" in error(page, "p0.upload")
    assert form.UPLOADED not in options(page, "p0.datasheet")


@pytest.mark.spec("IMP-003")
def test_imported_entry_first_and_selected_in_its_box_only() -> None:
    page = post("import:1", pv("a"), pv("b"), files=upload(PV_SHEET, box=1))
    assert options(page, "p1.datasheet") == [form.UPLOADED, *PVDatasheet.available()]
    assert value(page, "p1.datasheet") == form.UPLOADED
    assert label(page, "p1.datasheet") == "uploaded: Acme X-440"
    assert options(page, "p0.datasheet") == PVDatasheet.available()
    assert value(page, "p0.datasheet") == PV_BOX["datasheet"]


@pytest.mark.spec("IMP-004")
def test_new_import_replaces_the_old_one() -> None:
    first = post("import:0", pv("a"), files=upload(PV_SHEET))
    again = post(
        "import:0", pv("a", **imported(first)), files=upload(PV_SHEET.replace("X-440", "X-999"))
    )
    assert options(again, "p0.datasheet").count(form.UPLOADED) == 1
    assert label(again, "p0.datasheet") == "uploaded: Acme X-999"
    assert "X-440" not in again


@pytest.mark.spec("IMP-005")
def test_import_stays_with_its_box_until_reload() -> None:
    first = post("import:1", pv("a"), pv("b"), files=upload(PV_SHEET, box=1))
    assert base64.b64decode(value(first, "p1.imported")).decode() == PV_SHEET
    b = pv("b", **imported(first, box=1))
    other = upload(PV_SHEET.replace("X-440", "Y-1"), box=0)
    for page, i in [
        (post("add", pv("a"), b), 1),
        (post("apply", pv("a"), b), 1),
        (post("remove:0", pv("a"), b), 0),
        (post("import:0", pv("a"), b, files=other), 1),
    ]:
        assert value(page, f"p{i}.datasheet") == form.UPLOADED
        assert label(page, f"p{i}.datasheet") == "uploaded: Acme X-440"
    assert label(page, "p0.datasheet") == "uploaded: Acme Y-1"  # the other box got its own
    assert "uploaded:" not in client.get("/").text  # the server kept nothing


@pytest.mark.spec("IMP-005")
def test_carried_import_is_checked_again() -> None:
    bad = PV_SHEET.replace("pdc0_w: 440", "pdc0_w: -1")  # e.g. edited in the browser
    carried = base64.b64encode(bad.encode()).decode()
    page = post("run", pv("a", imported=carried, datasheet=form.UPLOADED))
    assert "pdc0_w: Input should be greater than 0" in error(page, "p0.upload")
    assert form.UPLOADED not in options(page, "p0.datasheet")
    assert "data-energy-kwh" not in page
    page = post("add", pv("a", imported="not base64!", datasheet=form.UPLOADED))
    assert error(page, "p0.upload") and 'name="p0.imported"' not in page


@pytest.mark.spec("IMP-006")
def test_type_change_drops_the_import() -> None:
    first = post("import:0", pv("a"), files=upload(PV_SHEET))
    page = post("apply", pv("a", type="hawt", **imported(first)))
    assert form.UPLOADED not in options(page, "p0.datasheet")
    assert 'name="p0.imported"' not in page
    assert not error(page, "p0.upload")


@pytest.mark.spec("IMP-007")
def test_run_with_import_equals_bundled_values() -> None:
    first = post("import:0", pv("mine"), pv("bundled"), files=upload(PV_SHEET))
    page = post("run", pv("mine", **imported(first)), pv("bundled"))
    assert energy(page, "mine") > 0
    assert energy(page, "mine") == pytest.approx(energy(page, "bundled"), abs=0.01)


@pytest.mark.spec("IMP-007")
@pytest.mark.parametrize(
    ("box", "sheet"),
    [
        (HAWT_BOX | {"name": "t"}, copy_of(HAWTDatasheet, "E-82/2300")),
        (VAWT_BOX | {"name": "t"}, copy_of(VAWTDatasheet, "mariah_power_windspire")),
    ],
    ids=["hawt", "vawt"],
)
def test_run_with_imported_turbine(box: dict[str, str], sheet: str) -> None:
    first = post("import:0", box, files=upload(sheet))
    assert label(first, "p0.datasheet") == f"uploaded: {yaml.safe_load(sheet)['manufacturer']} copy"
    assert energy(post("run", box | imported(first)), "t") > 0


@pytest.mark.spec("IMP-007")
def test_run_with_uploaded_entry_but_no_import() -> None:
    page = post("run", pv("a", datasheet=form.UPLOADED))
    assert "import a file first" in error(page, "p0.datasheet")
    assert "data-energy-kwh" not in page


@pytest.mark.spec("IMP-008")
@pytest.mark.parametrize(
    ("files", "message"),
    [
        (None, "choose a file first"),
        (upload(b"", filename=""), "choose a file first"),  # what a browser sends for no file
        (upload(PV_SHEET + "#" * (100 * 1024)), "larger than 100 kB"),
        (upload(b"\xff\xfe\x00\x01"), "not a text file"),
        (upload("manufacturer: [Acme\n"), "not a YAML file"),
        (upload("- a list\n- of things\n"), "`name: value`"),
        (upload(""), "`name: value`"),
        (upload(PV_SHEET.replace("440\n", "0\n")), "pdc0_w: Input should be greater than 0"),
    ],
    ids=["none", "empty-name", "too-big", "binary", "bad-yaml", "list", "empty", "bad-value"],
)
def test_unusable_file_shows_error_and_keeps_values(
    files: dict[str, Upload] | None, message: str
) -> None:
    first = post("import:0", pv("a"), files=upload(PV_SHEET))
    page = post("import:0", pv("a", tilt_deg="12", **imported(first)), files=files)
    assert message in error(page, "p0.upload")
    assert value(page, "p0.tilt_deg") == "12"
    assert label(page, "p0.datasheet") == "uploaded: Acme X-440"  # the earlier import stays
    assert "data-energy-kwh" not in page


@pytest.mark.spec("IMP-008")
def test_error_without_a_field_shows_its_message_alone() -> None:
    sheet = yaml.safe_load(copy_of(HAWTDatasheet, "E-82/2300"))
    sheet["power_kw"] = sheet["power_kw"][:-1]
    page = post("import:0", hawt("t"), files=upload(yaml.safe_dump(sheet)))
    msg = error(page, "p0.upload")
    assert "wind_speed_m_s and power_kw must have the same length" in msg
    assert not msg.startswith(":")


@pytest.mark.spec("IMP-009")
def test_file_cannot_run_code_or_add_html() -> None:
    page = post("import:0", pv("a"), files=upload("!!python/object/apply:os.getcwd []\n"))
    assert "not a YAML file" in error(page, "p0.upload")  # the safe reader refuses the tag
    hostile = PV_SHEET.replace("Acme", "<script>alert(1)</script>")
    page = post("import:0", pv("a"), files=upload(hostile))
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in tag(page, "p0.datasheet")
    page = post("add", pv("a", **imported(page)))  # carried back: still escaped
    assert "&lt;script&gt;" in tag(page, "p0.datasheet")
    page = post("import:0", pv("a"), files=upload("model: <script>alert(1)</script>: x\n"))
    assert "&lt;script&gt;" in error(page, "p0.upload")
    assert "<script" not in page
