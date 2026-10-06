---
id: 0002
title: PV plant
prefix: PV
status: implemented
---

# 0002 PV plant

## Problem
Estimate how much electricity a grid-connected solar (PV) installation delivers in each time step,
given where it is, how its panels are mounted, the module datasheet and the weather. The result is
AC power in kW, the same shape as every other plant, so PV can be compared and combined with wind,
biogas and boilers in a `Portfolio`.

## Scope
In:
- Panels at one fixed tilt and one compass direction per plant, feeding one (aggregate) inverter.
- The PVWatts v5 model chain: sun position, sky model, reflection loss, cell temperature, PVWatts DC
  power, lumped system losses, PVWatts inverter with clipping.
- Weather time steps from 1 minute up to 1 hour.
- DNI/DHI estimated from GHI when the weather source does not provide them.

Out (each may get its own spec later):
- Other module models: single-diode, ADR, PVWatts low-light correction `k` (see Domain notes).
- Sun-tracking mounts, bifacial modules, several panel orientations on one inverter.
- Shading by nearby objects or the horizon, snow cover, spectral effects (only the lumped loss % covers them).
- Module ageing over the years, batteries, grid export limits, inverter night consumption.
- Fetching weather data; resampling (caller's job, constitution 3).

## Domain notes

### Sunlight
- **Irradiance**: power of sunlight per square metre, W/m². Clear midday summer sun is about 1000 W/m².
- **GHI** (global horizontal irradiance): all sunlight landing on flat ground. Almost every weather
  source has it.
- **DNI** (direct normal irradiance): the direct beam from the sun's disc, measured facing the sun.
- **DHI** (diffuse horizontal irradiance): light scattered by sky and clouds, on flat ground.
  On an overcast day nearly all light is diffuse. `GHI = DNI × cos(sun zenith angle) + DHI`.
- **Decomposition**: estimating DNI and DHI from GHI alone. The **Erbs** model does this from how
  clear the sky is (measured GHI vs. the sunlight arriving at the top of the atmosphere).
- **POA** (plane-of-array) irradiance: sunlight landing on the tilted panel surface. It is the sum of
  direct beam, sky diffuse and light reflected off the ground.
- **Transposition / sky model**: converts horizontal light into POA. **Perez** is the standard
  choice; it accounts for the sky being brighter near the sun and near the horizon.
- **Albedo**: fraction of light the ground reflects (≈0.2 grass or soil, up to 0.8 fresh snow).
- **Reflection (AOI/IAM) loss**: the module glass reflects more light when the sun hits it at a
  shallow angle. The **physical** model computes this from the glass's optical properties.
- **Effective irradiance**: POA after reflection loss, i.e. light that actually reaches the cells.

### Module
- **STC** (standard test conditions): 1000 W/m², 25 °C cell temperature, standard spectrum.
  Datasheet ratings are at STC.
- **Rated power** `pdc0_w`: module output at STC ("Pmax", in Wp, watt-peak). System size in kWp is
  `n_modules × pdc0_w / 1000`.
- **Temperature coefficient** `gamma_pdc_per_k`: how much power changes per °C of cell temperature,
  as a fraction. Datasheets print it in %/°C: "−0.35 %/°C" is `-0.0035`. Hot panels make less power.
- **Cell temperature** is not air temperature: in full sun cells run 20–30 °C above air; wind cools
  them; air flowing behind the module cools them more. The **SAPM** temperature model (Sandia) has
  four standard presets for mounting and module construction:

  | `mounting` | Typical installation |
  |---|---|
  | `open_rack_glass_polymer` | standard module (glass front, plastic back) on a ground rack or a tilted roof rack with air behind |
  | `open_rack_glass_glass` | glass-glass module on a rack |
  | `close_mount_glass_glass` | glass-glass module close to the roof, small air gap |
  | `insulated_back_glass_polymer` | no air behind the module (built into the roof or facade); runs hottest |

  The model expects wind speed at 10 m height, the standard weather-station height.

### System
- Panels produce **DC**; the **inverter** converts it to grid **AC**, losing ~4 % (nominal
  efficiency 0.96) and somewhat more at low load.
- **Clipping**: the inverter cannot output more than its AC rating; any extra DC is lost. Designers
  often install more panel power than inverter power (DC/AC ratio 1.1–1.3) because clipping only
  happens on the sunniest hours.
- **System losses** `losses_pct`: one lumped percentage for dirt on panels, wiring, mismatch between
  modules, connectors, light-induced degradation, nameplate tolerance, minor shading and downtime.
  PVWatts and PVGIS both default to 14 %.
- **Orientation**: `tilt_deg` 0 = flat, 90 = vertical. `azimuth_deg` = compass direction the panels
  face, clockwise from north: 90 east, 180 south, 270 west (pvlib convention). PVGIS uses a
  different convention ("aspect": 0 south, −90 east, 90 west, i.e. aspect = azimuth − 180).

### The PVWatts formula
```
P_dc = n_modules × pdc0_w × (G_eff / 1000) × (1 + gamma_pdc_per_k × (T_cell − 25))
P_dc_net = P_dc × (1 − losses_pct / 100)
P_ac = PVWatts inverter(P_dc_net), capped at inverter_ac_kw
```
PVWatts treats efficiency as independent of light level. Real modules lose a few % relative
efficiency in weak light, so in cloudy climates PVWatts tends to overestimate slightly.
Considered and deferred on 2026-10-05: the **ADR** model (Driesse & Stein 2020,
`pvlib.pvarray.pvefficiency_adr`; 5 fitted parameters) and PVWatts' optional low-light correction
`k` (Marion 2008, `pvlib.pvsystem.pvwatts_dc(k=...)`; one datasheet number, power at 200 W/m²).

### Time convention
Inputs are averages over each period, labelled at the period start (core time grid). The sun moves
a lot within an hour, so its position MUST be taken at the middle of the period. Using the label
time would shift the hourly profile by 30 minutes and distort sunrise and sunset hours.
The output keeps exactly the input's labels: a row labelled 10:00 (1 h step) means "average over
10:00–11:00" on the way in and on the way out; 10:30 is only used internally for the sun.
Some sources (e.g. PVGIS) give snapshots taken at one instant instead of period averages. The
caller relabels those so the snapshot falls in the middle of its period (snapshot at 10:10 →
label 09:40); the plant never shifts labels itself.
Steps longer than 1 hour are rejected because PV output is not proportional to average sunlight
(e.g. a daily average hides both night and clipping).

### Engine and references
- Engine: pvlib (optional extra `pv`), its `ModelChain` configured as PVWatts:
  Perez transposition, physical AOI, no spectral loss, SAPM temperature, PVWatts DC, losses and
  inverter; Erbs to estimate DNI/DHI from GHI. Checked against pvlib 0.16.1.
- A. P. Dobos, *PVWatts Version 5 Manual*, NREL/TP-6A20-62641, 2014.
- D. L. King et al., *Photovoltaic Array Performance Model* (SAPM), SAND2004-3535, 2004.
- R. Perez et al., "Modeling daylight availability and irradiance components from direct and
  global irradiance", Solar Energy 44(5), 1990.
- D. G. Erbs et al., "Estimation of the diffuse radiation fraction for hourly, daily and
  monthly-average global radiation", Solar Energy 28(4), 1982.
- PVGIS, EU Joint Research Centre: https://re.jrc.ec.europa.eu/pvg_tools/

## Interface

`PVDatasheet` (module product data, YAML in `kioze_sim/datasheets/pv/`):

| Field | Unit | Allowed | Meaning |
|---|---|---|---|
| `manufacturer`, `model`, `source` | – | – | from `Datasheet` |
| `pdc0_w` | W | > 0 | rated module power at STC |
| `gamma_pdc_per_k` | 1/K | −0.01 … 0 | temperature coefficient of power, as a fraction |

`PVParams`:

| Field | Unit | Default | Allowed | Meaning |
|---|---|---|---|---|
| `name` | – | required | – | plant name (from `PlantParams`) |
| `datasheet` | – | required | – | a `PVDatasheet` |
| `latitude_deg` | ° | required | −90 … 90 | north positive |
| `longitude_deg` | ° | required | −180 … 180 | east positive |
| `altitude_m` | m | 0 | −500 … 9000 | height above sea level |
| `tilt_deg` | ° | required | 0 … 90 | 0 flat, 90 vertical |
| `azimuth_deg` | ° | required | 0 ≤ x < 360 | direction faced, clockwise from north |
| `n_modules` | – | required | ≥ 1 (integer) | number of modules |
| `inverter_ac_kw` | kW | required | > 0 | inverter AC nameplate (total) |
| `inverter_efficiency` | – | 0.96 | 0 < x ≤ 1 | nominal DC→AC efficiency |
| `losses_pct` | % | 14 | 0 ≤ x < 100 | lumped system losses |
| `albedo` | – | 0.2 | 0 … 1 | ground reflectance |
| `mounting` | – | `open_rack_glass_polymer` | the four SAPM presets | cell-temperature preset |

`PVInputs` (`TimeSeries`; every series is a period average on the shared index):

| Field | Unit | Required | Allowed |
|---|---|---|---|
| `ghi_w_m2` | W/m² | yes | ≥ 0 |
| `dni_w_m2` | W/m² | no, but together with `dhi_w_m2` | ≥ 0 |
| `dhi_w_m2` | W/m² | no, but together with `dni_w_m2` | ≥ 0 |
| `temp_air_c` | °C | yes | finite |
| `wind_speed_m_s` | m/s | yes | ≥ 0, at 10 m height |

`PVOutput` (`PlantOutput` subclass, all Series on the input index):

| Field | Unit | Meaning |
|---|---|---|
| `power_kw` | kW | AC power delivered, average over the period |
| `dc_kw` | kW | DC power into the inverter, after system losses |
| `poa_w_m2` | W/m² | sunlight on the panel surface |
| `temp_cell_c` | °C | modelled cell temperature |

### Engine mapping
What our code hands to pvlib and takes back. Everything between is pvlib's physics, configured as
listed under "Engine and references" (PV-019) and checked end to end against PVGIS (PV-018).

| Ours | pvlib |
|---|---|
| `latitude_deg`, `longitude_deg`, `altitude_m` | `Location(latitude, longitude, altitude)`, time zone UTC |
| `tilt_deg`, `azimuth_deg`, `albedo` | `surface_tilt`, `surface_azimuth`, `albedo` |
| `n_modules × pdc0_w` | module `pdc0` (W) |
| `gamma_pdc_per_k` | module `gamma_pdc` |
| `inverter_ac_kw × 1000 / inverter_efficiency` | inverter `pdc0` (W), so pvlib caps AC at `inverter_ac_kw` |
| `inverter_efficiency` | inverter `eta_inv_nom` |
| `mounting` | SAPM temperature preset of the same name |
| `losses_pct` | losses: `soiling = losses_pct`, the other nine components 0 |

| Weather (ours) | pvlib, stamped at period middles |
|---|---|
| `ghi_w_m2`, `dni_w_m2`, `dhi_w_m2` | `ghi`, `dni`, `dhi` (DNI/DHI from Erbs if absent) |
| `temp_air_c`, `wind_speed_m_s` | `temp_air`, `wind_speed` |

| pvlib result | Output (ours), on the input labels |
|---|---|
| `ac` (W) | `power_kw` = `ac / 1000` |
| `dc` (W, after losses) | `dc_kw` = `dc / 1000` |
| `total_irrad["poa_global"]` | `poa_w_m2` |
| `cell_temperature` | `temp_cell_c` |

## Requirements

Parameters and inputs
- **PV-001** `PVDatasheet` MUST have exactly the fields of the `PVDatasheet` table, MUST require `pdc0_w` > 0 and `gamma_pdc_per_k` within [−0.01, 0], so a coefficient entered in percent (e.g. −0.35) is rejected at load time.
- **PV-002** `PVParams` MUST have exactly the fields, units, defaults and allowed ranges of the `PVParams` table and MUST reject any value outside them at construction.
- **PV-003** `PVInputs` MUST require `ghi_w_m2`, `temp_air_c` and `wind_speed_m_s`, MUST accept `dni_w_m2` and `dhi_w_m2` only as a pair, and MUST reject a struct that has exactly one of them.
- **PV-004** `PVInputs` MUST reject negative values in any irradiance series or in `wind_speed_m_s`, with an error naming the series.
- **PV-005** `PVPlant.simulate` MUST reject inputs whose time step is longer than 1 hour.

Model chain
- **PV-006** The plant MUST hand the engine weather stamped at each period's middle (label + step/2) and MUST return every output on the input's labels.
- **PV-007** When `dni_w_m2` and `dhi_w_m2` are absent, the plant MUST estimate them from `ghi_w_m2` with the Erbs model before running the engine; when given, they MUST reach the engine unchanged.
- **PV-020** Every parameter and weather series MUST reach the engine as given in the "Engine mapping" tables.
- **PV-021** Engine results MUST become outputs as given in the "Engine mapping" results table. Where no light reaches the panel (GHI = 0 or the sun below the horizon), missing engine values MUST become 0 for light and power and the air temperature for the cell; a missing value in daylight MUST raise an error.
- **PV-014** `power_kw` MUST be 0 in every period where `ghi_w_m2` is 0, whatever the engine returns.
- **PV-015** `simulate` MUST return a `PVOutput` that also carries `dc_kw`, `poa_w_m2` and `temp_cell_c` as Series on the input index.

Engine
- **PV-016** pvlib MUST only be imported when a PV plant is simulated, not on `import kioze_sim`; if it is not installed, `simulate` MUST raise `ImportError` telling the user to install `kioze-sim[pv]`.
- **PV-019** The model choices listed under "Engine and references" MUST be set explicitly in the code, never taken from pvlib defaults, so a pvlib update cannot change them silently.

Validation
- **PV-018** Annual AC energy at the reference location Warsaw, PL (52.23° N, 21.01° E), driven by PVGIS TMY weather, MUST be within ±5 % of PVGIS's own estimate (PVcalc, crystalline silicon, free-standing, 14 % loss) for the same tilt, orientation and kWp.

## Acceptance
- Every PV-xxx requirement has at least one test marked with its ID; `uv run pytest`,
  `uv run python scripts/spec_check.py`, `ruff` and `mypy` are green.
- `tests/golden/pv/` holds the PV-018 case (PVGIS TMY input, the PVGIS annual figure, the request
  parameters and the script that fetched them).
- PV-018's ±5 % allows for PVGIS using its own module model (with low-light and spectral effects)
  and long-term average weather, so a few % difference is expected.

## Open questions
- [x] **One orientation per plant**: yes; an east+west roof is two plants in a `Portfolio`, each
      with its own inverter limit (confirmed 2026-10-05).
- [x] **Optional DNI/DHI**: yes; estimated from GHI with Erbs when missing (confirmed 2026-10-05).
- [x] **Fixed tilt only**: yes; sun-tracking mounts are out of scope for v1 (confirmed 2026-10-05).
- [x] **`area_m2`**: dropped from `PVDatasheet`; PVWatts does not use it (decided 2026-10-05).
- [x] **PV-018 tolerance**: ±5 % accepted (confirmed 2026-10-05).
- [x] **PV-018 location**: Warsaw, PL (confirmed 2026-10-05).

## Changelog
- 2026-10-05 stub created
- 2026-10-05 draft requirements PV-001..018; PVWatts chosen for v1 over single-diode and ADR
- 2026-10-05 `area_m2` dropped from `PVDatasheet`; PV-001 now pins the exact datasheet fields
- 2026-10-05 open questions resolved (one orientation, optional DNI/DHI, fixed tilt, ±5 %, Warsaw); approved
- 2026-10-05 PV-017 removed (ID retired): the plant wraps pvlib's `ModelChain`, so comparing against
  `ModelChain` would test pvlib against itself; PV-018 (PVGIS) is the independent check. Time
  convention note: output keeps input labels; snapshot data is relabelled by the caller
- 2026-10-05 implemented; PV-018: 4136.8 kWh/yr vs PVGIS 4200.86 kWh/yr (−1.5 %)
- 2026-10-05 PV-006..010 and PV-013 rewritten as behaviour checkable from outside (tests no longer
  re-run pvlib to compare); model names moved to Domain notes and pinned by new PV-019
- 2026-10-05 PV-008..013 retired: they restated pvlib's physics, which pvlib tests itself. Replaced
  by PV-020 (parameters and weather reach pvlib as mapped) and PV-021 (results come back as mapped);
  PV-006/007/014 reworded to our part. The physics is checked only end to end, by PV-018
- 2026-10-06 datasheet location updated to `kioze_sim/datasheets/pv/` (constitution 13)
