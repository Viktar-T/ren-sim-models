"""Build the WIND-014 golden case `kelmarsh1_2020` from measured Kelmarsh data. Spec 0003, plan.md.

Run by hand:
  uv run python kiozesim/tests/golden/hawt/make_kelmarsh_case.py [--refresh] [--cache DIR]

With --refresh (or when _source/ is empty) downloads the 2020 SCADA zip (452 MB) and the turbine
list from Zenodo into the cache folder and writes the filtered extract to _source/. Then writes the
case from _source/. Must not import kiozesim: golden values come from an independent reference.

Data: C. Plumley, "Kelmarsh wind farm data", Zenodo 2022, doi:10.5281/zenodo.5841834, CC-BY 4.0.
"""

from __future__ import annotations

import argparse
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

RECORD = "https://zenodo.org/records/5841834/files/"
SCADA_ZIP = "Kelmarsh_SCADA_2020_3086.zip"
STATIC_CSV = "Kelmarsh_WT_static.csv"
TURBINE = "Kelmarsh 1"
HERE = Path(__file__).parent
SOURCE = HERE / "_source" / "kelmarsh1_2020.csv.gz"
CASE = HERE / "kelmarsh1_2020"
STEP_H = 1 / 6  # 10-minute periods

# SCADA columns (Greenbyte export; time stamps are UTC period starts)
WIND = "Wind speed (m/s)"  # nacelle anemometer, at hub height
POWER = "Power (kW)"
TEMP = "Nacelle ambient temperature (°C)"
LOST = "Lost Production to Downtime and Curtailment Total (kWh)"
AVAILABLE = "Available Capacity for Production (kW)"


def _download(name: str, cache: Path) -> Path:
    path = cache / name
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        print(f"downloading {name} ...")
        urllib.request.urlretrieve(RECORD + name + "?download=1", path)
    return path


def fetch(cache: Path) -> None:
    """Download, keep turbine 1's needed columns, write the extract to _source/."""
    static = pd.read_csv(_download(STATIC_CSV, cache)).set_index("Title").loc[TURBINE]
    with zipfile.ZipFile(_download(SCADA_ZIP, cache)) as z:
        (name,) = [n for n in z.namelist() if n.startswith("Turbine_Data_Kelmarsh_1_")]
        with z.open(name) as f:
            d = pd.read_csv(
                f,
                skiprows=9,
                index_col=0,
                parse_dates=True,
                usecols=["# Date and time", WIND, POWER, TEMP, LOST, AVAILABLE],
            )
    d.index = d.index.tz_localize("UTC").rename("time")
    rated = float(static["Rated power (kW)"])
    included = d[[WIND, POWER, TEMP, LOST, AVAILABLE]].notna().all(axis=1)
    included &= (d[LOST] == 0) & (d[AVAILABLE] == rated)
    out = pd.DataFrame(
        {
            "wind_speed_m_s": d[WIND],
            "temp_air_c": d[TEMP],
            "power_kw": d[POWER],
            "included": included,
        }
    )
    SOURCE.parent.mkdir(exist_ok=True)
    out.to_csv(SOURCE)
    meta = {
        "hub_height_m": float(static["Hub Height (m)"]),
        "elevation_m": float(static["Elevation (m)"]),
        "rated_power_kw": rated,
        "fetched": date.today().isoformat(),
    }
    (SOURCE.parent / "kelmarsh1_static.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))


def surface_pressure_hpa(elevation_m: float) -> float:
    """Standard atmosphere surface pressure at that height above sea level."""
    return 1013.25 * (1 - 2.25577e-5 * elevation_m) ** 5.25588


def build() -> None:
    src = pd.read_csv(SOURCE, index_col="time", parse_dates=True)
    meta = yaml.safe_load((SOURCE.parent / "kelmarsh1_static.yaml").read_text())
    grid = pd.date_range("2020-01-01", "2021-01-01", freq="10min", tz="UTC", inclusive="left")
    src = src.reindex(grid)
    ok = src["included"].fillna(False).astype(bool)
    pressure = round(surface_pressure_hpa(meta["elevation_m"]), 1)

    inputs = pd.DataFrame(
        {
            # excluded periods: wind 0, so the model gives 0 kW there (below cut-in)
            "wind_speed_m_s": src["wind_speed_m_s"].where(ok, 0.0).round(3),
            "temp_air_c": src["temp_air_c"].interpolate(limit_direction="both").round(2),
            "pressure_hpa": pressure,
        },
        index=grid.rename("time"),
    )
    measured_kwh = float(src.loc[ok, "power_kw"].sum() * STEP_H)
    CASE.mkdir(exist_ok=True)
    inputs.to_csv(CASE / "inputs.csv", date_format="%Y-%m-%dT%H:%M:%SZ")
    hub = meta["hub_height_m"]
    case = {
        "params": {
            "name": "kelmarsh_1",
            "hub_height_m": hub,
            "wind_height_m": hub,  # nacelle anemometer
            "temp_height_m": hub,  # nacelle temperature sensor
            "density_correction": True,
            "losses_pct": 0.0,
        },
        "datasheet": "MM92/2050",
        "expected_energy_kwh": round(measured_kwh, 1),
        "rtol": 0.10,
        "atol": 0.0,
        "source": (
            f"Kelmarsh wind farm data (C. Plumley, Zenodo 2022, doi:10.5281/zenodo.5841834, "
            f"CC-BY 4.0), {TURBINE} (Senvion MM92), 2020, fetched {meta['fetched']}. "
            f"Kept {int(ok.sum())} of {len(grid)} 10-min periods (wind, power, temperature "
            f"present; no downtime or curtailment loss; full available capacity). Measured "
            f"energy = sum of Power over kept periods; excluded periods have wind 0 in "
            f"inputs.csv. Constant "
            f"pressure {pressure} hPa (standard atmosphere at {meta['elevation_m']} m). "
            f"Built by make_kelmarsh_case.py from _source/."
        ),
    }
    (CASE / "case.yaml").write_text(yaml.safe_dump(case, sort_keys=False, width=100))
    print(f"kept {int(ok.sum())}/{len(grid)} periods, measured {measured_kwh:.0f} kWh")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="download again and rebuild _source/")
    ap.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "kiozesim-golden")
    args = ap.parse_args()
    if args.refresh or not SOURCE.exists():
        fetch(args.cache)
    build()


if __name__ == "__main__":
    main()
