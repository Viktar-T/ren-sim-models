---
id: 0003
title: HAWT plant
prefix: WIND
status: implemented
---

# 0003 HAWT plant

## Problem
Estimate how much electricity a horizontal-axis wind turbine (the familiar three-bladed kind, "HAWT")
or a small group of identical ones delivers in each time step, given the turbine's datasheet, its
hub height and the weather. The result is power in kW, the same shape as every other plant, so wind
can be compared and combined with PV, biogas and boilers in a `Portfolio`.

## Scope
In:
- One turbine type per plant, `n_turbines` identical turbines that all see the same wind.
- Converting wind measured at one height (e.g. a 10 m weather mast) to the hub height.
- Optional correction for air density (cold dense air carries more energy than warm thin air).
- The manufacturer's power curve as the turbine model.
- One lumped loss percentage for everything the power curve does not know about.
- Loading turbine datasheets by name from the turbine library shipped with windpowerlib
  (67 types, 500 kW to 9.5 MW), through the usual `HAWTDatasheet.available()` / `bundled(name)`.
- Weather time steps from 1 minute up to 1 hour.

Out (each may get its own spec later):
- Copying library turbines into our own YAML files; small turbines (< 500 kW, not in the library).
- Wake losses computed from turbine layout (turbines shading each other's wind); only the lumped
  loss % covers them.
- Vertical-axis turbines (spec 0004), power-coefficient (Cp) models, blade-level aerodynamics.
- Turbulence, gusts, wind direction, cut-out/restart hysteresis, icing, curtailment.
- Turbine ageing, availability schedules, grid limits.
- Fetching weather data; resampling (caller's job, constitution 3).

## Domain notes

### Wind and height
- **Wind speed** is measured in metres per second (m/s). 5 m/s is a gentle breeze, 12 m/s a strong
  wind, above 25 m/s a storm.
- **Wind grows with height**: the ground slows the air down (friction), so wind at 100 m is usually
  much stronger than at 10 m. Weather stations measure at 10 m; turbines sit at 60–160 m. The
  measured wind must be "lifted" to hub height before it is used.
- **Hub height**: height of the turbine's centre (where the blades attach) above the ground.
- **Roughness length** `roughness_length_m`: one number describing how much the ground slows the
  wind. Smooth ground (sea) barely slows it; forests and towns slow it a lot. Typical values:

  | Ground | `roughness_length_m` |
  |---|---|
  | open sea | 0.0002 |
  | open flat land, grass, few obstacles | 0.03 |
  | farmland with hedges, scattered buildings | 0.1 |
  | villages, small towns, many trees | 0.5 |
  | forest, city | 1.0 |

- **Logarithmic wind profile**: the standard formula that lifts wind speed from the measured height
  to hub height using the roughness length:
  `v_hub = v_meas × ln(h_hub / z0) / ln(h_meas / z0)`.
  Example: 5 m/s at 10 m over farmland (`z0 = 0.1`) becomes about 6.8 m/s at 100 m.
  When the wind is already measured at hub height (e.g. by the turbine's own anemometer), nothing
  is lifted.

### Air density
- **Air density**: how many kilograms one cubic metre of air weighs, about 1.225 kg/m³ at sea level
  and 15 °C. The energy in wind is proportional to density: in −10 °C winter air a turbine makes a
  few % more than in +30 °C summer air at the same wind speed, and less at high altitude.
- Power curves are published for 1.225 kg/m³. The **density correction** (IEC 61400-12) adjusts the
  wind speed fed into the curve so the curve also holds for other densities. It needs air
  temperature and air pressure. The pressure must be **surface pressure** (what a barometer on site
  reads), not the "sea-level pressure" weather maps show.
- Temperature and pressure are carried up to hub height with standard atmosphere rules (−6.5 °C
  per km; barometric formula). Over 100 m this changes density by about 1 %.

### Turbine
- **Rated power** `rated_power_kw`: the turbine's nameplate output, reached at the **rated wind
  speed** (typically 11–14 m/s). Above it the blades turn ("pitch") to spill wind and hold output
  at rated.
- **Power curve**: a table from the manufacturer: wind speed at hub height → electrical output,
  measured to the standard IEC 61400-12-1. It already includes the turbine's own losses (gearbox,
  generator, converter). Between table points the curve is interpolated linearly.
- **Cut-in speed**: below about 3 m/s the turbine does not turn; output is 0.
- **Cut-out speed**: above about 25 m/s (the last point of the curve) the turbine stops to protect
  itself; output is 0.
- **Rotor diameter**: tip-to-tip blade span. Not used by the power-curve model; kept for display and
  sanity checks.
- **Capacity factor**: annual energy ÷ (rated power × 8760 h). Onshore in Poland typically 25–35 %.

### Losses
- **Lumped losses** `losses_pct`: one percentage for wake losses inside a group of turbines,
  downtime for maintenance, cabling to the grid connection and transformer. Wind industry studies
  typically assume 10–15 % in total for a wind farm, less for a single turbine.

### Time convention
Inputs are averages over each period, labelled at the period start (core time grid); the output
keeps the input's labels. There is no sun position, so no mid-period shift is needed.
Steps longer than 1 hour are rejected: output is roughly proportional to the cube of wind speed, so
a daily average wind badly underestimates the energy of a gusty day.

### Formula
```
v_hub      = logarithmic profile(wind_speed_m_s, wind_height_m → hub_height_m, roughness_length_m)
v_curve    = v_hub × density correction (only if density_correction)
P_turbine  = power curve(v_curve), 0 outside the curve's wind speed range
power_kw   = n_turbines × P_turbine × (1 − losses_pct / 100)
```

### Engine and references
- Engine: windpowerlib (optional extra `wind`), its `ModelChain` configured with: logarithmic wind
  profile, linear-gradient temperature, barometric density, power-curve output, density correction
  on or off per `density_correction`, obstacle height 0. Checked against windpowerlib 0.2.2.
- Kelmarsh wind farm SCADA data, C. Plumley, Zenodo 2022, doi:10.5281/zenodo.5841834, CC-BY 4.0
  (validation, WIND-014).
- IEC 61400-12-1, *Power performance measurements of electricity producing wind turbines*.
- S. Sommer et al., *windpowerlib — a Python library to model wind power plants*, JOSS 2019.

## Interface

`HAWTDatasheet` (turbine product data, YAML in `kiozesim/datasheets/hawt/`):

| Field | Unit | Allowed | Meaning |
|---|---|---|---|
| `manufacturer`, `model`, `source` | – | – | from `Datasheet` |
| `rated_power_kw` | kW | > 0 | nameplate power |
| `rotor_diameter_m` | m | > 0 | rotor diameter |
| `wind_speed_m_s` | m/s | ≥ 2 points, ≥ 0, strictly increasing | power curve: wind speed at hub height |
| `power_kw` | kW | same length, each 0 … 1.05 × `rated_power_kw` | power curve: output at that speed |

(Some published curves peak up to 2.5 % above nameplate, hence the 1.05 margin.)

### Where turbine datasheets come from
windpowerlib ships a copy of the Open Energy Database (OEDB) turbine library: manufacturer power
curves of 67 turbine types (Enercon, Vestas, Nordex, Siemens, Senvion, GE, ...), 500 kW to 9.5 MW,
stored as files inside the installed windpowerlib package (no internet needed).
`HAWTDatasheet` declares this library as its *catalogue* (spec 0007, DS-011), so it is served
through the same calls as every other datasheet:

- `HAWTDatasheet.available()` lists YAML files on the `hawt` shelf (none yet) plus every library
  turbine, sorted. Library turbines are named by the library's own type code, e.g. `"E-82/2300"`,
  `"MM92/2050"`, `"V90/2000"`. These contain `/` and capitals, so they can never clash with YAML
  file names (lower-case, `_` only; spec 0007).
- `HAWTDatasheet.bundled("E-82/2300")` builds a validated datasheet from the library entry:

  | Library field | `HAWTDatasheet` |
  |---|---|
  | `manufacturer` | `manufacturer` |
  | turbine type code | `model` |
  | `source` | `source` (empty for the 4 types the library gives none: N100/2500, V112/3300, V117/3300, VS112/2500) |
  | `nominal_power` (W) / 1000 | `rated_power_kw` |
  | `rotor_diameter` | `rotor_diameter_m` |
  | power curve speeds / values (W) / 1000 | `wind_speed_m_s` / `power_kw` |

- Without windpowerlib installed, `available()` lists only the YAML files and `bundled()` of a
  library name raises `ImportError` with the install hint.

`HAWTParams`:

| Field | Unit | Default | Allowed | Meaning |
|---|---|---|---|---|
| `name` | – | required | – | plant name (from `PlantParams`) |
| `datasheet` | – | required | – | a `HAWTDatasheet` |
| `hub_height_m` | m | required | > 0 | hub height above ground |
| `n_turbines` | – | 1 | ≥ 1 (integer) | number of identical turbines |
| `wind_height_m` | m | 10 | > `roughness_length_m` | height at which the input wind was measured |
| `roughness_length_m` | m | 0.1 | > 0, < `hub_height_m` | ground roughness (table above) |
| `temp_height_m` | m | 2 | > 0 | height at which the input temperature was measured |
| `density_correction` | – | true | bool | apply the air-density correction |
| `losses_pct` | % | 10 | 0 ≤ x < 100 | lumped losses |

`HAWTInputs` (`TimeSeries`; every series is a period average on the shared index):

| Field | Unit | Required | Allowed |
|---|---|---|---|
| `wind_speed_m_s` | m/s | yes | ≥ 0, at `wind_height_m` |
| `temp_air_c` | °C | when `density_correction` | finite, at `temp_height_m` |
| `pressure_hpa` | hPa | when `density_correction` | > 0, surface pressure at ground level |

`HAWTOutput` (`PlantOutput` subclass, all Series on the input index):

| Field | Unit | Meaning |
|---|---|---|
| `power_kw` | kW | power delivered by all turbines after losses, average over the period |
| `wind_speed_hub_m_s` | m/s | wind speed lifted to hub height (before density correction) |
| `air_density_kg_m3` | kg/m³ | air density at hub height; absent (None) without density correction |

### Engine mapping

| Ours | windpowerlib |
|---|---|
| `hub_height_m` | `WindTurbine(hub_height=...)` |
| `rated_power_kw × 1000` | `nominal_power` (W) |
| `rotor_diameter_m` | `rotor_diameter` |
| `wind_speed_m_s`, `power_kw × 1000` | `power_curve` DataFrame (`wind_speed`, `value` in W) |
| `density_correction` | `ModelChain(density_correction=...)` |

| Weather (ours) | windpowerlib weather column `(variable, height)` |
|---|---|
| `wind_speed_m_s` | `("wind_speed", wind_height_m)` |
| `temp_air_c + 273.15` | `("temperature", temp_height_m)` (K) |
| `pressure_hpa × 100` | `("pressure", 0)` (Pa) |
| `roughness_length_m` (constant) | `("roughness_length", 0)` |

| windpowerlib result | Output (ours) |
|---|---|
| `power_output` (W) | `power_kw = n_turbines × power_output / 1000 × (1 − losses_pct / 100)` |
| hub-height wind speed | `wind_speed_hub_m_s` |
| hub-height density | `air_density_kg_m3` |

## Requirements

Parameters and inputs
- **WIND-001** `HAWTDatasheet` MUST have exactly the fields of the `HAWTDatasheet` table and MUST reject at load time a curve whose two lists differ in length, have fewer than 2 points, whose speeds are negative or not strictly increasing, or whose powers are negative or above 1.05 × `rated_power_kw`.
- **WIND-002** `HAWTParams` MUST have exactly the fields, units, defaults and allowed ranges of the `HAWTParams` table and MUST reject any value outside them at construction.
- **WIND-003** `HAWTInputs` MUST require `wind_speed_m_s` and MUST reject negative values in it with an error naming the series.
- **WIND-004** `HAWTPlant.simulate` MUST raise an error naming the missing series when `density_correction` is true and `temp_air_c` or `pressure_hpa` is absent; when it is false, both MAY be absent and MUST be ignored if given.
- **WIND-005** `HAWTPlant.simulate` MUST reject inputs whose time step is longer than 1 hour.

Model
- **WIND-006** Every parameter and weather series MUST reach the engine as given in the "Engine mapping" tables.
- **WIND-007** Engine results MUST become outputs as given in the "Engine mapping" results table, on the input's labels.
- **WIND-008** When `wind_height_m` equals `hub_height_m`, `wind_speed_hub_m_s` MUST equal the input `wind_speed_m_s`.
- **WIND-009** `power_kw` MUST be 0 wherever the hub-height wind speed fed into the curve is below its first or above its last wind speed point, and MUST never exceed `n_turbines × max(power_kw curve) × (1 − losses_pct / 100)`.
- **WIND-010** `simulate` MUST return a `HAWTOutput` carrying `wind_speed_hub_m_s` and, with density correction, `air_density_kg_m3` as Series on the input index.

Engine
- **WIND-011** windpowerlib MUST only be imported when a HAWT plant is simulated, not on `import kiozesim`; if it is not installed, `simulate` MUST raise `ImportError` telling the user to install `kiozesim[wind]`.
- **WIND-012** The model choices listed under "Engine and references" MUST be set explicitly in the code, never taken from windpowerlib defaults.

Datasheets
- **WIND-013** With windpowerlib installed, `HAWTDatasheet.available()` MUST list the YAML files on the `hawt` shelf plus every turbine with a power curve in windpowerlib's bundled library, by its type code, sorted; `bundled(code)` MUST return a datasheet mapped as in "Where turbine datasheets come from", and every listed library turbine MUST load and pass WIND-001.
- **WIND-015** Loading library turbines MUST NOT access the network.
- **WIND-016** Without windpowerlib, `available()` MUST list only the YAML files, and `bundled()` of a name that is not a YAML file MUST raise `ImportError` telling the user to install `kiozesim[wind]`; with windpowerlib, an unknown name MUST raise `FileNotFoundError` as in DS-004.

Validation
- **WIND-014** Annual energy of one Kelmarsh turbine (Senvion MM92, hub height 78.5 m, library type `MM92/2050`) over calendar year 2020, driven by its measured 10-minute nacelle wind speed (`wind_height_m = hub_height_m`) and nacelle temperature, with `losses_pct = 0`, counting only normal-operation periods (no downtime, curtailment or missing data; the same periods on both sides), MUST be within ±10 % of the measured energy for those periods.

## Acceptance
- Every WIND-xxx requirement has at least one test marked with its ID; `uv run pytest`,
  `uv run python scripts/spec_check.py`, `ruff` and `mypy` are green.
- `kiozesim/tests/golden/hawt/` holds the WIND-014 case: the filtered Kelmarsh extract, the measured
  energy, and the script that downloaded and filtered it.
- WIND-014's ±10 % allows for the nacelle anemometer sitting behind the rotor (it reads slightly
  off), turbulence and the generic library curve versus this turbine's real behaviour. If the
  dataset has no air pressure, the case uses a constant surface pressure for the site's altitude
  (standard atmosphere).

## Open questions
- [x] **1. Turbine datasheets**: load windpowerlib's 67 library turbines by name through
      `HAWTDatasheet`; copy nothing into YAML yet; no small turbines for now (confirmed 2026-10-08).
- [x] **2. Density correction**: on by default, switchable off (confirmed 2026-10-08).
- [x] **3. Default `losses_pct`**: 10 % (confirmed 2026-10-08).
- [x] **4. Validation reference**: Kelmarsh measured data, annual energy ±10 % (confirmed 2026-10-08).
- [x] **5. Wake losses**: none in v1 beyond lumped `losses_pct` (confirmed 2026-10-08).
- [x] **6. Wind profile**: logarithmic with `roughness_length_m` (confirmed 2026-10-08).
- [x] **7. Library names**: the library's own type code (`"E-82/2300"`), not the 0007 file-name
      rule (confirmed 2026-10-08).
- [x] **8. Without windpowerlib**: list shows no library turbines; loading one raises `ImportError`
      (confirmed 2026-10-08).

## Changelog
- 2026-10-05 stub created
- 2026-10-08 draft: domain notes, interface, WIND-001..012; open questions 1–6
- 2026-10-08 open questions 1–8 resolved; WIND-013..016 added (library datasheets, Kelmarsh)
- 2026-10-08 approved
- 2026-10-08 library served as a 0007 catalogue (DS-011); turbines without a library source keep an empty `source`
- 2026-10-08 implemented; WIND-014: 5 833 MWh modelled vs 6 215 MWh measured (−6.1 %)
