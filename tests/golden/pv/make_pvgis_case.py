"""Build the PV-018 golden case `warsaw_pvgis_annual` from PVGIS (EU JRC). Spec 0002, plan.md.

Run by hand:  uv run python tests/golden/pv/make_pvgis_case.py [--refresh]

Downloads (or, without --refresh, reuses from _source/) the PVGIS 5.3 TMY weather and the PVcalc
annual yield, then writes the case.
Must not import kioze_sim: golden values come from an independent reference.
"""

from __future__ import annotations

import argparse
import gzip
import json
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

API = "https://re.jrc.ec.europa.eu/api/v5_3/"
HERE = Path(__file__).parent
SOURCE = HERE / "_source"
CASE = HERE / "warsaw_pvgis_annual"

LAT, LON = 52.23, 21.01
KWP, TILT, ASPECT = 4.0, 35, 0  # PVGIS aspect 0 = south = our azimuth 180
PVGIS_LOSS_PCT = 14.0
INVERTER_EFF = 0.96
# PVGIS's system loss includes the inverter, PVWatts' does not: (1 - L) * 0.96 = 1 - 0.14
LOSSES_PCT = round(100 * (1 - (1 - PVGIS_LOSS_PCT / 100) / INVERTER_EFF), 4)


def _get(endpoint: str, **params: object) -> dict[str, Any]:
    url = API + endpoint + "?" + urllib.parse.urlencode(params | {"outputformat": "json"})
    with urllib.request.urlopen(url, timeout=120) as r:
        data: dict[str, Any] = json.load(r)
    return data


def fetch() -> None:
    SOURCE.mkdir(exist_ok=True)
    common = {"lat": LAT, "lon": LON, "usehorizon": 0}
    tmy = _get("tmy", **common)
    with gzip.open(SOURCE / "tmy.json.gz", "wt") as f:
        json.dump(tmy, f)
    pvcalc = _get(
        "PVcalc",
        **common,
        peakpower=KWP,
        loss=PVGIS_LOSS_PCT,
        angle=TILT,
        aspect=ASPECT,
        mountingplace="free",
        pvtechchoice="crystSi",
        raddatabase="PVGIS-SARAH3",
    )
    pvcalc["fetched"] = date.today().isoformat()
    (SOURCE / "pvcalc.json").write_text(json.dumps(pvcalc, indent=1))


def build() -> None:
    with gzip.open(SOURCE / "tmy.json.gz", "rt") as f:
        tmy = json.load(f)
    pvcalc = json.loads((SOURCE / "pvcalc.json").read_text())

    # PVGIS-SARAH values are snapshots taken `irradiance_time_offset` hours after the HH:00
    # label. Relabel so each snapshot sits in the middle of its 1 h period (labels = period start).
    minute = round(tmy["inputs"]["location"]["irradiance_time_offset"] * 60)
    rows = pd.DataFrame(tmy["outputs"]["tmy_hourly"])
    t = pd.to_datetime(rows["time(UTC)"], format="%Y%m%d:%H%M", utc=True)
    t = t.map(lambda x: x.replace(year=1990))  # TMY months come from different years
    index = pd.DatetimeIndex(t) + pd.Timedelta(minutes=minute - 30)
    weather = pd.DataFrame(
        {
            "ghi_w_m2": rows["G(h)"].to_numpy(),
            "dni_w_m2": rows["Gb(n)"].to_numpy(),
            "dhi_w_m2": rows["Gd(h)"].to_numpy(),
            "temp_air_c": rows["T2m"].to_numpy(),
            "wind_speed_m_s": rows["WS10m"].to_numpy(),
        },
        index=index.rename("time"),
    ).sort_index()

    CASE.mkdir(exist_ok=True)
    weather.to_csv(CASE / "inputs.csv", date_format="%Y-%m-%dT%H:%M:%SZ")
    (CASE / "module.yaml").write_text(
        yaml.safe_dump(
            {
                "manufacturer": "Generic",
                "model": "c-Si 400 W",
                "source": "typical crystalline-silicon values for the PV-018 case "
                "(PVGIS uses its own generic c-Si model)",
                "pdc0_w": 400,
                "gamma_pdc_per_k": -0.0035,
            },
            sort_keys=False,
        )
    )
    inputs = pvcalc["inputs"]
    e_y = pvcalc["outputs"]["totals"]["fixed"]["E_y"]
    meteo = inputs["meteo_data"]
    case = {
        "params": {
            "name": "warsaw_4kwp",
            "latitude_deg": LAT,
            "longitude_deg": LON,
            "altitude_m": inputs["location"]["elevation"],
            "tilt_deg": TILT,
            "azimuth_deg": 180 + ASPECT,
            "n_modules": int(KWP * 1000 / 400),
            "inverter_ac_kw": KWP,  # DC/AC 1.0: PVGIS has no clipping
            "inverter_efficiency": INVERTER_EFF,
            "losses_pct": LOSSES_PCT,
            "mounting": "open_rack_glass_polymer",  # PVGIS "free-standing"
        },
        "datasheet": "module.yaml",
        "expected_energy_kwh": e_y,
        "rtol": 0.05,
        "atol": 0.0,
        "source": (
            f"PVGIS 5.3 ({API}) PVcalc E_y and TMY, {meteo['radiation_db']} "
            f"{meteo['year_min']}-{meteo['year_max']}, no horizon, fetched {pvcalc['fetched']}; "
            f"TMY relabelled by {minute - 30} min (PVGIS snapshot minute {minute}). "
            "Built by make_pvgis_case.py from _source/."
        ),
    }
    (CASE / "case.yaml").write_text(yaml.safe_dump(case, sort_keys=False, width=100))
    print(f"wrote {CASE}: E_y = {e_y} kWh, snapshot minute {minute}, {len(weather)} rows")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="download again from PVGIS")
    if ap.parse_args().refresh or not (SOURCE / "pvcalc.json").exists():
        fetch()
    build()
