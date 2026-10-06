from pathlib import Path

import pytest

from kioze_sim.plants import REGISTRY


def _bundled():
    out = []
    for name, cls in REGISTRY.items():
        pkg_dir = Path(__import__(cls.__module__.rsplit(".", 1)[0], fromlist=["x"]).__file__).parent
        for f in sorted((pkg_dir / "datasheets").glob("*.yaml")):
            out.append(pytest.param(cls, f, id=f"{name}/{f.name}"))
    return out


@pytest.mark.spec("CORE-006")
@pytest.mark.parametrize(("cls", "path"), _bundled())
def test_bundled_datasheets_validate(cls, path):
    ds_model = cls.params_model.model_fields["datasheet"].annotation
    assert ds_model.from_yaml(path).manufacturer


@pytest.mark.spec("CORE-006")
def test_datasheet_rejects_unknown_field(tmp_path):
    from kioze_sim.plants.pv import PVDatasheet

    f = tmp_path / "d.yaml"
    f.write_text("manufacturer: a\nmodel: b\npdc0_w: 1\ngamma_pdc_per_k: 0\nbogus: 2\n")
    with pytest.raises(Exception, match="bogus"):
        PVDatasheet.from_yaml(f)
