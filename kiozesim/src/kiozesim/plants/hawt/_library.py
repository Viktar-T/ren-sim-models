"""windpowerlib's bundled turbine library (OEDB copy) as HAWT datasheets. Spec 0003.

Reads the CSV files shipped inside the installed windpowerlib package with pandas. windpowerlib's
own download functions are never called, and its modules are not imported, so this needs no
network and `import kiozesim` stays light.
"""

from __future__ import annotations

from functools import cache
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import pandas as pd

from kiozesim.datasheet import Catalogue

WIND_HINT = "pip install 'kiozesim[wind]'"


def _folder() -> Path | None:
    spec = find_spec("windpowerlib")
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations))) / "oedb"


def installed() -> bool:
    return _folder() is not None


@cache
def _turbines() -> dict[str, dict[str, Any]]:
    """Type code -> datasheet fields, for every library turbine with a power curve."""
    folder = _folder()
    if folder is None:
        return {}
    data = pd.read_csv(folder / "turbine_data.csv")
    data = data[data["has_power_curve"].fillna(False).astype(bool)]
    data = data.drop_duplicates("turbine_type").set_index("turbine_type")
    curves = pd.read_csv(folder / "power_curves.csv").set_index("turbine_type")
    out: dict[str, dict[str, Any]] = {}
    for code, row in data.iterrows():
        if code not in curves.index:
            continue
        curve = curves.loc[str(code)].dropna()
        source = row["source"]
        out[str(code)] = {
            "manufacturer": str(row["manufacturer"]),
            "model": str(code),
            "source": None if pd.isna(source) else str(source),
            "rated_power_kw": float(row["nominal_power"]) / 1000,
            "rotor_diameter_m": float(row["rotor_diameter"]),
            "wind_speed_m_s": [float(v) for v in curve.index],
            "power_kw": [float(w) / 1000 for w in curve.to_numpy()],
        }
    return out


def names() -> list[str]:
    """Type codes of the library turbines; empty without windpowerlib."""
    return sorted(_turbines())


def load(code: str) -> dict[str, Any] | None:
    """Datasheet fields for a type code, or None if the library has no such turbine."""
    return _turbines().get(code)


class TurbineLibrary(Catalogue):
    """The library as `HAWTDatasheet.catalogue` (spec 0007, DS-011)."""

    install_hint = WIND_HINT

    def installed(self) -> bool:
        return installed()

    def names(self) -> list[str]:
        return names()

    def load(self, name: str) -> dict[str, Any] | None:
        return load(name)
