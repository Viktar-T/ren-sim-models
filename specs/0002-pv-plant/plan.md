# 0002 PV plant: plan

How to build [spec.md](spec.md). Checked against pvlib 0.16.1 and the PVGIS 5.3 user manual on 2026-10-05.

## Design in one paragraph
`PVPlant` stays a thin pydantic shell in `plant.py`. The physics is pvlib's own `ModelChain`
(the "do everything" pipeline), configured as PVWatts in a private module `_engine.py`, the only
file that imports pvlib. Around it we add only what pvlib does not do for us: shift
timestamps to mid-period and back, estimate DNI/DHI with Erbs when missing, force 0 kW when
GHI is 0, and convert W to kW. Less of our own physics code means fewer places to get it wrong.

## Modules touched

| File | Change |
|---|---|
| `kiozesim/src/kiozesim/plants/pv/plant.py` | rewrite models per the spec's Interface tables; `PVOutput`; `_simulate` |
| `kiozesim/src/kiozesim/plants/pv/_engine.py` | **new**: builds and runs the pvlib `ModelChain` (only file importing pvlib) |
| `kiozesim/src/kiozesim/plants/pv/__init__.py` | also export `PVOutput` |
| `kiozesim/src/kiozesim/plants/pv/datasheets/example.yaml` | drop `area_m2` |
| `kiozesim/tests/test_pv.py` | **new**: one or more tests per PV-001..016, PV-018 |
| `kiozesim/tests/golden/pv/make_pvgis_case.py` | **new**: fetches PVGIS data and writes the PV-018 case (network, run by hand) |
| `kiozesim/tests/golden/pv/warsaw_pvgis_annual/` | **new**: the PV-018 golden case |
| `kiozesim/tests/harness.py`, `kiozesim/tests/test_harness.py`, `kiozesim/tests/golden/README.md` | optional `expected_energy_kwh` (total energy) check |
| `kiozesim/tests/test_datasheets.py` | drop `area_m2` from the unknown-field YAML |
| `kiozesim/tests/conftest.py` | `weather` fixture is unused; delete it |
| `pyproject.toml` | mypy override `pvlib.*` → `ignore_missing_imports` (pvlib ships no type info) |
| `specs/0001-core-plant-interface/spec.md` | changelog line for the harness extension (no requirement change; CORE-007 already says "expected values") |

## Public models (stub → spec)

- `PVDatasheet`: `pdc0_w: float = Field(gt=0)`, `gamma_pdc_per_k: float = Field(ge=-0.01, le=0)`;
  `area_m2` removed.
- `PVParams`: renames `latitude` → `latitude_deg`, `longitude` → `longitude_deg`;
  replaces `inverter_pdc0_w` with `inverter_ac_kw`; adds `inverter_efficiency`, `losses_pct`,
  `albedo`, `mounting: Literal[...4 SAPM presets]`. Ranges via `Field(ge/gt/le/lt)`.
- Both set `model_config = ConfigDict(allow_inf_nan=False)` (merged with the frozen/forbid base
  config) because pydantic accepts `inf` by default and `inf > 0` passes a `gt=0` check.
- `PVInputs`: `ghi_w_m2`, `temp_air_c`, `wind_speed_m_s: pd.Series`; `dni_w_m2`, `dhi_w_m2:
  pd.Series | None = None`. An `after` validator checks: both-or-neither (PV-003), no negatives in
  irradiance or wind with the series name in the message (PV-004), and finite `temp_air_c` (the base
  only rejects NaN, not `inf`). The base `TimeSeries` already skips `None` fields, and `from_frame`
  simply omits missing columns.
- `PVOutput(PlantOutput)`: adds `dc_kw`, `poa_w_m2`, `temp_cell_c: pd.Series`.
  `PVPlant.output_model = PVOutput`, generic `Plant[PVParams, PVInputs, PVOutput]`.

## Engine (`_engine.py`)

`build_modelchain(params) -> ModelChain` and `run(params, inputs) -> pd.DataFrame` (columns in
W, W/m², °C, on the input index). The `ModelChain` object stays inside this private module.

**Configuration** (PV-019). Every model is named explicitly, not taken from `with_pvwatts` defaults, so
a default changing in a future pvlib cannot silently change our results. Req column: the
behaviour each setting serves.

| Req | `ModelChain` / `PVSystem` / `Location` setting |
|---|---|
| PV-006 | `Location(latitude_deg, longitude_deg, tz="UTC", altitude=altitude_m)`, `solar_position_method="nrel_numpy"`, `airmass_model="kastenyoung1989"` |
| PV-008 | `transposition_model="perez"`, `PVSystem(surface_tilt, surface_azimuth, albedo=albedo)` |
| PV-009 | `aoi_model="physical"`, `spectral_model="no_loss"` |
| PV-010 | `temperature_model="sapm"`, `temperature_model_parameters=TEMPERATURE_MODEL_PARAMETERS["sapm"][mounting]` |
| PV-011 | `dc_model="pvwatts"`, `module_parameters={"pdc0": n_modules * pdc0_w, "gamma_pdc": gamma_pdc_per_k}` |
| PV-012 | `losses_model="pvwatts"`, `losses_parameters` with **all ten** components given: `soiling=losses_pct`, the other nine `0` (pvlib's defaults are non-zero and would add ~14 % on top) |
| PV-013 | `ac_model="pvwatts"`, `inverter_parameters={"pdc0": inverter_ac_kw * 1000 / inverter_efficiency, "eta_inv_nom": inverter_efficiency}`; pvlib caps AC at `eta_inv_nom × pdc0 = inverter_ac_kw` |

**Run steps** (`step = index[1] - index[0]`, `mid = index + step/2`):

| # | Req | Step |
|---|---|---|
| 0 | PV-005 | in `plant.py`: reject `step > 1 h` with `TimeGridError` |
| 1 | PV-006 | weather frame (`ghi`, `dni`, `dhi`, `temp_air`, `wind_speed`) on `mid` |
| 2 | PV-007 | if no DNI/DHI: `location.get_solarposition(mid, temperature=temp_air)`, then `irradiance.erbs(ghi, zenith, mid)` |
| 3 | – | `mc.run_model(weather)` |
| 4 | PV-014 | where `ghi == 0`: `ac = dc = poa = 0`; where `ghi == 0` or the sun is down: remaining NaNs → 0, cell temperature NaN → air temperature; any other NaN → raise |
| 5 | PV-006, PV-015 | `results.ac`, `results.dc` (after losses), `results.total_irrad["poa_global"]`, `results.cell_temperature` relabelled from `mid` back to the input index; W → kW in `plant.py` |

Lazy import (PV-016): `_simulate` does `from kiozesim.plants.pv import _engine` inside a
`try`. An `ImportError` whose `name` starts with `pvlib` is re-raised as
`ImportError("PV simulation needs pvlib: pip install 'kiozesim[pv]'")`. Nothing in
`kiozesim/__init__.py` or `plants/pv/__init__.py` imports `_engine`.

## Time labels
The output index is always the input index (CORE-004, PV-006). A label means "start of the
period", and the value is the average over the period. Mid-period timestamps exist only inside
`_engine.run`, so pvlib looks at the sun at 10:30 for the 10:00–11:00 hour. Data that are
snapshots, not averages, are relabelled by whoever prepares them (see the PVGIS case below),
never by the plant.

## Golden data (PV-018)

`kiozesim/tests/golden/pv/make_pvgis_case.py` runs once, by hand, with network access. It **must not
import `kiozesim`** (golden values come from an independent reference). It saves the raw PVGIS
responses under `kiozesim/tests/golden/pv/_source/`, so the case can be rebuilt offline. It records the
pvlib version, the PVGIS API URL and the fetch date in `case.yaml` `source:`.

- **Weather:** PVGIS TMY for Warsaw (52.23° N, 21.01° E, 100 m),
  `pvlib.iotools.get_pvgis_tmy(..., usehorizon=False, url=".../api/v5_3/")`, year coerced to 1990.
- **Timestamps:** PVGIS-SARAH values are snapshots at HH:mm, where mm is a site-specific minute
  (5–12 in Europe), but the TMY labels them HH:00. The TMY response states the offset itself
  (`inputs.location.irradiance_time_offset`, 0.1832 h ≈ 11 min for Warsaw). The script relabels the TMY to
  `HH:00 + mm − 30 min`. Each snapshot then sits mid-period, as our convention expects. The index stays regular, so the time grid accepts it.
- **System:** case-local `module.yaml` (400 W, γ = −0.0035 /K), 10 modules = 4 kWp, tilt 35°,
  azimuth 180° (PVGIS aspect 0), `mounting: open_rack_glass_polymer` (PVGIS "free-standing").
- **Loss mapping:** PVGIS's "system loss" **includes the inverter**. PVWatts' does not: its
  inverter is modelled separately at about 96 %. Feeding 14 % into both would make ours about
  4 % low for no real reason. The case therefore uses `losses_pct = 100 × (1 − 0.86 / 0.96) ≈ 10.42`
  with `inverter_efficiency = 0.96`, so the total chain loss matches PVGIS's 14 %. It also uses
  `inverter_ac_kw = 4.0` (DC/AC 1.0), because PVGIS has no clipping. The spec fixes only PVGIS's
  settings and our tilt, orientation and kWp, so this is within the spec.
- **Reference:** PVcalc on `https://re.jrc.ec.europa.eu/api/v5_3/PVcalc` with
  `lat, lon, peakpower=4, loss=14, angle=35, aspect=0, mountingplace=free, pvtechchoice=crystSi,
  usehorizon=0, raddatabase=PVGIS-SARAH3, outputformat=json`. `outputs.totals.fixed.E_y` (kWh/yr)
  becomes `expected_energy_kwh`, with `rtol: 0.05`.

## Harness extension
For PV-018 a time series comparison is the wrong check: we only claim agreement on the yearly
total. `case.yaml` may carry `expected_energy_kwh: <float>` instead of an `expected.csv`. The harness
then compares `sum(power_kw) × step_hours` to that number with the case's `rtol`/`atol`. This is
also what the biogas spec needs (its acceptance check is in GWh/year). It gets its own CORE-007 test in `test_harness.py`,
and the golden README documents it, along with the corrected example column names (`ghi_w_m2`, ...).

## Tests (`kiozesim/tests/test_pv.py`)
We test our code, not pvlib's physics: pvlib tests its own models, and the physics is checked end
to end only by PV-018 (PVGIS). Tests never re-run a pvlib step to compare. `_engine.run` is split
so each of our parts is testable on its own: `build_modelchain` (settings), `prepare_weather`
(weather in), `collect` (results out). pvlib is used in tests only to make clear-sky test weather.
Tests that need pvlib are skipped without it; dev and CI install all extras.

| Req | Test idea |
|---|---|
| PV-001 | field set equals the table; `pdc0_w=0`, `gamma=-0.35`, `gamma=+0.001`, `inf` rejected |
| PV-002 | field set and defaults equal the table; parametrised out-of-range values rejected; boundaries accepted |
| PV-003 | GHI-only struct accepted, `from_frame` without DNI/DHI works; only DNI or only DHI rejected |
| PV-004 | negative GHI/DNI/DHI/wind rejected with the series name; negative temperature accepted; `inf` rejected |
| PV-005 | 2 h step rejected; 1 h, 15 min and 1 min accepted |
| PV-006 | `prepare_weather` index = labels + step/2 (1 h, 15 min, labels at 10 past); `collect` and `simulate` return on the input labels |
| PV-007 | given DNI/DHI reach pvlib unchanged; without them, a stand-in `erbs` receives our GHI and period middles, and its output reaches pvlib |
| PV-020 | `build_modelchain` with non-default values: location, tilt, azimuth, albedo, module, inverter, temperature preset and all ten loss components (read from pvlib's `pvwatts_losses` signature) are as mapped; `prepare_weather` column mapping |
| PV-021 | stand-in `run` with made-up W values: `simulate` outputs kW etc.; `collect` fills missing values at night and at dawn without light (0 / air temperature), leaves daylight untouched, raises on a daylight NaN |
| PV-014 | `collect`: GHI = 0 forces AC and DC to 0 even when the engine claims power |
| PV-015 | returns `PVOutput`; the three extra Series are on the input index |
| PV-016 | subprocess: `import kiozesim` leaves `pvlib` out of `sys.modules`; with pvlib hidden, `simulate` raises `ImportError` mentioning `kiozesim[pv]` |
| PV-019 | the `ModelChain` reports the pinned model names; a GHI-only run calls Erbs |
| PV-018 | `run_case` on `warsaw_pvgis_annual` |

## Order of work
1. Reshape the models, the example datasheet and old tests (`area_m2`, conftest). `_simulate` still raises.
2. Write `kiozesim/tests/test_pv.py`; everything except the model tests passes, and the model tests fail.
3. Harness `expected_energy_kwh` plus its test and README.
4. Write and run `make_pvgis_case.py`; commit `_source/` and the case (xfail until step 5).
5. Implement `_engine.py` and `_simulate` until green.
6. `pytest`, `spec_check`, `ruff`, `mypy`; set the spec to `implemented`.

## Risks
- **PV-018 may miss ±5 %.** PVGIS models spectral effects, low-light efficiency and module
  temperature differently, and compares a TMY against a multi-year average. If the first run is
  outside ±5 %, stop and bring the numbers to the user. Do not tune parameters or loosen the
  tolerance without a spec change.
- **PV-018 is the only independent end-to-end check.** The per-step tests confirm the
  configuration, but not the wiring as a whole. A wrong label shift or unit slip that leaves the
  annual total within 5 % would go unnoticed. That is accepted for v1 (the user removed the
  separate pvlib comparison on 2026-10-05).
- **Timestamp alignment of PVGIS data** (handled by the minute-offset relabel above). A wrong offset
  mostly shifts the profile within the day; it changes the annual total by far less than 5 %.
- **NaNs from pvlib at night.** Handled in run step 4; a NaN anywhere else is a bug and fails
  loudly (`PlantOutput` also rejects it). Found in practice: PVGIS has 198 dawn/dusk hours with
  the sun just up but GHI = DHI = 0, where Perez divides 0 by 0 (test
  `test_no_nan_when_dawn_has_no_light`). Daylight with DHI = 0 and GHI > 0 would still raise; it
  does not occur in the PVGIS data and Erbs never produces it.
- **pvlib default drift.** Avoided by naming every `ModelChain` model explicitly.
- **Network dependency** is limited to `make_pvgis_case.py`; tests run offline from committed data
  (the full-year inputs CSV is a few hundred kB).
- **pvlib API drift**: `get_pvgis_tmy` changed its return shape in 0.13. Only the script uses it;
  the library code uses `ModelChain`, `erbs` and friends, which are stable since 0.11, the current lower bound.

## Outcome (2026-10-05)
- PV-018: 4136.8 kWh/yr vs PVGIS 4200.86 kWh/yr, **−1.5 %** (tolerance ±5 %). Sunlight on the panels
  from the TMY is 1251 kWh/m² vs PVGIS's 2005–2023 mean of 1312 kWh/m². The weather year
  explains most of the gap.
- Tests were written after the engine. To check they bite, eight deliberate bugs were injected
  (no mid-period shift, Hay-Davies sky model, pvlib default losses, no GHI = 0 rule, ASHRAE
  reflection, inverter limit = AC rating, fixed mounting preset, albedo ignored). Each one made a
  PV test fail.
- Revised the same day: tests that re-ran pvlib steps to compare (PV-006..010, inverter efficiency)
  were replaced by behaviour tests, and the spec reworded to match (see spec changelog). Bug
  injection again: every bug is caught. Swapping in a *similar* model (Hay-Davies for Perez,
  ASHRAE for physical reflection) is caught only by the PV-019 pin; that is the accepted trade-off.

- Revised again: the behaviour tests still re-checked pvlib's physics. Deleted them; PV-008..013
  retired. Tests now cover only our code: settings mapping (PV-020), weather in (PV-006/007),
  results out (PV-021, PV-014). Bug injection: 11/11 caught. A similar-model swap is caught only by
  the PV-019 pin, and a physics problem only by PVGIS (PV-018).
