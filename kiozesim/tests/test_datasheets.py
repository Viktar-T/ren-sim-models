import re
import subprocess
import sys
from pathlib import Path

import pytest

import kiozesim
from kiozesim.datasheet import Datasheet
from kiozesim.plants import REGISTRY
from kiozesim.plants.pv import PVDatasheet

PKG = Path(kiozesim.__file__).parent
DATASHEETS = [cls.params_model.model_fields["datasheet"].annotation for cls in REGISTRY.values()]


def _bundled():
    return [
        pytest.param(ds, name, id=f"{ds.shelf}/{name}")  # type: ignore[union-attr]
        for ds in DATASHEETS
        for name in ds.available()  # type: ignore[union-attr]
    ]


@pytest.mark.spec("CORE-006")
@pytest.mark.parametrize(("ds", "name"), _bundled())
def test_bundled_datasheets_validate(ds, name):
    assert ds.bundled(name).manufacturer


@pytest.mark.spec("CORE-006")
def test_datasheet_rejects_unknown_field(tmp_path):
    f = tmp_path / "d.yaml"
    f.write_text("manufacturer: a\nmodel: b\npdc0_w: 1\ngamma_pdc_per_k: 0\nbogus: 2\n")
    with pytest.raises(Exception, match="bogus"):
        PVDatasheet.from_yaml(f)


@pytest.mark.spec("DS-001")
def test_datasheets_live_in_central_folder():
    assert not list((PKG / "plants").rglob("*.yaml"))
    for f in (PKG / "datasheets").rglob("*.yaml"):
        assert f.parent.parent == PKG / "datasheets"
        assert f.parent.name in {ds.shelf for ds in DATASHEETS}  # type: ignore[union-attr]


@pytest.mark.spec("DS-002")
def test_available_lists_sorted_names():
    names = PVDatasheet.available()
    assert names == sorted(names)
    assert names == sorted(f.stem for f in (PKG / "datasheets" / "pv").glob("*.yaml"))


@pytest.mark.spec("DS-002")
def test_available_empty_shelf():
    class Empty(Datasheet):
        shelf = "no_such_shelf"

    assert Empty.available() == []


@pytest.mark.spec("DS-003")
@pytest.mark.spec("DS-006")
@pytest.mark.parametrize(("ds", "name"), _bundled())
def test_bundled_equals_from_yaml(ds, name):
    path = PKG / "datasheets" / ds.shelf / f"{name}.yaml"
    loaded = ds.bundled(name)
    assert isinstance(loaded, ds)
    assert loaded == ds.from_yaml(path)


@pytest.mark.spec("DS-004")
def test_unknown_name_lists_available():
    with pytest.raises(FileNotFoundError) as e:
        PVDatasheet.bundled("nope")
    for name in PVDatasheet.available():
        assert name in str(e.value)


@pytest.mark.spec("DS-005")
def test_bundled_lookup_from_wheel(tmp_path):
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=PKG.parent.parent,
    )
    if build.returncode != 0:
        pytest.skip(f"wheel build failed (offline?): {build.stderr[-300:]}")
    (wheel,) = tmp_path.glob("*.whl")
    code = (
        "import kiozesim, sys; from kiozesim.plants.pv import PVDatasheet;"
        f"assert kiozesim.__file__.startswith({str(wheel)!r}), kiozesim.__file__;"
        "print(PVDatasheet.bundled(PVDatasheet.available()[0]).model)"
    )
    # A wheel is a zip: on sys.path it is imported straight from the archive, not the source tree.
    run = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={"PYTHONPATH": str(wheel)},
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip()


@pytest.mark.spec("DS-007")
def test_subclasses_declare_only_shelf():
    for ds in DATASHEETS:
        assert ds.shelf  # type: ignore[union-attr]
        own = {"available", "bundled", "from_yaml"} & set(vars(ds))  # type: ignore[arg-type]
        assert not own, f"{ds} overrides file logic: {own}"


@pytest.mark.spec("DS-007")
def test_base_without_shelf_refuses():
    with pytest.raises(TypeError, match="shelf"):
        Datasheet.available()


@pytest.mark.spec("DS-008")
@pytest.mark.parametrize(("ds", "name"), _bundled())
def test_bundled_are_real_and_sourced(ds, name):
    src = ds.bundled(name).source
    assert src and "placeholder" not in src.lower()
    assert re.search(r"https?://\S+", src)


@pytest.mark.spec("DS-009")
@pytest.mark.parametrize(("ds", "name"), _bundled())
def test_bundled_name_follows_rule(ds, name):
    d = ds.bundled(name)
    assert name == re.sub(r"[^a-z0-9]+", "_", f"{d.manufacturer} {d.model}".lower()).strip("_")


@pytest.mark.spec("DS-010")
def test_pv_shelf_ships_spec_modules():
    expected = {
        "jinko_solar_jkm440n_54hl4r_b": (440, -0.0029),
        "longi_lr5_54hth_430m": (430, -0.0029),
        "rec_solar_rec430aa_pure_r": (430, -0.0024),
    }
    assert set(PVDatasheet.available()) == set(expected)
    for name, (pdc0_w, gamma) in expected.items():
        d = PVDatasheet.bundled(name)
        assert (d.pdc0_w, d.gamma_pdc_per_k) == (pdc0_w, gamma)
