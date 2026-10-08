# 0003 HAWT plant: plan

How to build [spec.md](spec.md). Checked against windpowerlib 0.2.2 and the Kelmarsh dataset
(Zenodo record 5841834, v0.0.3) on 2026-10-08.

## Design in one paragraph
`HAWTPlant` stays a thin pydantic shell in `plant.py`, like PV. The physics is windpowerlib's
`ModelChain`, used from a private `_engine.py`, the only module that imports windpowerlib's model
code. The turbine library is read by a second private module, `_library.py`, which reads
windpowerlib's three bundled CSV files directly with pandas (never windpowerlib's download
functions, so no network: WIND-015). Around the engine we add only what windpowerlib does not do:
unit conversion (°C → K, hPa → Pa, W → kW), `n_turbines` and `losses_pct`, and the input checks.

## Modules touched

| File | Change |
|---|---|
| `kiozesim/src/kiozesim/plants/hawt/plant.py` | rewrite models per the spec's Interface tables; `HAWTOutput`; `_simulate` |
| `kiozesim/src/kiozesim/plants/hawt/_engine.py` | **new**: builds the `WindTurbine` and `ModelChain`, runs them (only file importing windpowerlib models) |
| `kiozesim/src/kiozesim/plants/hawt/_library.py` | **new**: lists and loads turbines from windpowerlib's bundled `oedb/*.csv` |
| `kiozesim/src/kiozesim/plants/hawt/__init__.py` | also export `HAWTOutput` |
| `kiozesim/tests/test_hawt.py` | **new**: one or more tests per WIND-001..016 |
| `kiozesim/tests/golden/hawt/make_kelmarsh_case.py` | **new**: downloads and filters Kelmarsh, writes the WIND-014 case (network, run by hand) |
| `kiozesim/tests/golden/hawt/_source/` | **new**: the filtered Kelmarsh extract (turbine 1, 2020) |
| `kiozesim/tests/golden/hawt/kelmarsh1_2020/` | **new**: the WIND-014 golden case |
| `pyproject.toml` | mypy override `windpowerlib.*` → `ignore_missing_imports` |

The apps (specs 0010, 0011) get their own small plans after this one is implemented.

## Public models (stub → spec)

- `HAWTDatasheet`: fields renamed to the spec (`wind_speed_m_s`, `power_kw` unchanged;
  `rated_power_kw`, `rotor_diameter_m` get `gt=0`). An `after` validator checks the curve (WIND-001):
  equal lengths, ≥ 2 points, speeds ≥ 0 and strictly increasing, powers within
  [0, 1.05 × `rated_power_kw`]. `allow_inf_nan=False`, as in PV.
- `HAWTDatasheet.available()` / `bundled(name)` (WIND-013, WIND-016); built as a 0007 *catalogue*
  (DS-011, `Catalogue` in `kiozesim/datasheet.py`, `TurbineLibrary` in `_library.py`) instead of
  overrides, which DS-007 forbids. Behaviour:
  - `available()` = `super().available()` (YAML on the `hawt` shelf) + `_library.names()`, sorted;
    `_library.names()` returns `[]` when windpowerlib is not installed.
  - `bundled(name)`: a YAML file of that name wins (`super().bundled`); otherwise
    `_library.load(name)`. Without windpowerlib → `ImportError` with the `kiozesim[wind]` hint.
    With windpowerlib and an unknown name → `FileNotFoundError` listing `available()` (DS-004).
  - Library names contain `/` and capitals, so they never collide with YAML file names.
- `HAWTParams`: `hub_height_m: float = Field(gt=0)`, `n_turbines: int = Field(1, ge=1)`,
  `wind_height_m = 10`, `roughness_length_m = 0.1`, `temp_height_m = 2`,
  `density_correction: bool = True`, `losses_pct = 10` (`ge=0, lt=100`). A model validator checks
  `roughness_length_m < wind_height_m` and `roughness_length_m < hub_height_m` (the log profile
  divides by `ln(h / z0)`, which is 0 or negative otherwise).
- `HAWTInputs`: `wind_speed_m_s: pd.Series`; `temp_air_c`, `pressure_hpa: pd.Series | None = None`.
  Validator: wind ≥ 0 and pressure > 0 with the series name in the message; temperature finite.
- `HAWTOutput(PlantOutput)`: `wind_speed_hub_m_s: pd.Series`, `air_density_kg_m3: pd.Series | None`.
- `_simulate` checks (before the engine): step ≤ 1 h else `TimeGridError` (WIND-005); with
  `density_correction`, both `temp_air_c` and `pressure_hpa` present, else `ValueError` naming the
  missing one (WIND-004).

## Turbine library (`_library.py`)

Locates the folder with `importlib.util.find_spec("windpowerlib")` → `<package>/oedb/`, reads
`turbine_data.csv` and `power_curves.csv` once (`functools.cache`). Keeps rows with
`has_power_curve`. Maps per the spec table: `manufacturer`, `turbine_type` → `model`, `source`,
`nominal_power / 1000`, `rotor_diameter`, curve columns (wind speed headers, non-empty cells) with
values / 1000. Returns a validated `HAWTDatasheet`. Reading the files directly, instead of
`WindTurbine(turbine_type=...)`, also gives us `source`, which `WindTurbine` drops.

## Engine (`_engine.py`)

`build(params) -> ModelChain`, `prepare_weather(params, inputs) -> DataFrame`,
`run(params, inputs) -> DataFrame` with columns `power_w`, `wind_speed_hub_m_s`,
`air_density_kg_m3` on the input index.

**Configuration** (WIND-012), every choice named explicitly:

| Setting | Value |
|---|---|
| `WindTurbine` | `hub_height=hub_height_m`, `nominal_power=rated_power_kw × 1000`, `rotor_diameter=rotor_diameter_m`, `power_curve=DataFrame(wind_speed, value=power_kw × 1000)`, `path=None` (no library lookup inside windpowerlib) |
| `ModelChain` | `wind_speed_model="logarithmic"`, `temperature_model="linear_gradient"`, `density_model="barometric"`, `power_output_model="power_curve"`, `density_correction=density_correction`, `obstacle_height=0`, `hellman_exp=None` |

**Weather** (WIND-006): MultiIndex columns `(variable, height)` as in the spec's mapping table.
Without density correction only `wind_speed` and `roughness_length` are passed.

**Run**: `ModelChain.run_model` throws away hub wind speed and density, which we need as outputs
(WIND-010). So `run` calls the same public steps `run_model` calls, in the same order:
`data.check_weather_data` → `mc.wind_speed_hub(w)` → `mc.density_hub(w)` (only with density
correction) → `mc.calculate_power_output(v_hub, rho_hub)`. A test pins that this equals
`run_model(w).power_output`, so a windpowerlib change to `run_model` is noticed.

**Out** (WIND-007, in `plant.py`): `power_kw = n_turbines × power_w / 1000 × (1 − losses_pct / 100)`.

Lazy import (WIND-011): `_simulate` imports `_engine` inside a `try`; an `ImportError` whose `name`
starts with `windpowerlib` becomes `ImportError("HAWT simulation needs windpowerlib: pip install
'kiozesim[wind]'")`. Nothing in `kiozesim/__init__.py` or `plants/hawt/__init__.py` imports
`_engine` or `_library` at module level.

## Golden data (WIND-014)

`make_kelmarsh_case.py` runs once, by hand, with network access. It **must not import
`kiozesim`**. It downloads `Kelmarsh_SCADA_2020_3086.zip` (452 MB) and `Kelmarsh_WT_static.csv`
into a cache folder outside the repository (`--cache`, default `~/.cache/kiozesim-golden`),
then extracts turbine 1's 10-minute SCADA and status (event) files.

- **Turbine**: Kelmarsh 1, Senvion MM92, 2050 kW, hub 78.5 m, ground 145.6 m above sea level
  (from `Kelmarsh_WT_static.csv`). Library type `MM92/2050`.
- **Signals**: `Wind speed` (nacelle, at hub height), `Power`, `Nacelle ambient temperature`,
  `Turbine Power setpoint`. Exact column headers confirmed when the script is first run.
- **Normal operation** (same periods on both sides): keep a 10-minute period only if wind, power
  and temperature are present, the SCADA system books no lost production to downtime or
  curtailment (`Lost Production to Downtime and Curtailment Total (kWh)` = 0), and the turbine's
  `Available Capacity for Production (kW)` is the full 2050 kW. (Changed while building: the
  power setpoint follows the controller and is below rated 79 % of the time, so it is no
  curtailment flag; the lost-production columns are the operator's own classification of the
  status events, so the status file is not parsed separately.)
- **Gaps vs the time grid**: the core grid (CORE-002) forbids gaps and NaN, so the case keeps the
  full regular 2020 grid. In excluded periods the script writes wind speed 0 (the model then gives
  exactly 0 kW, below cut-in) and interpolated temperature; the measured energy
  `expected_energy_kwh` sums `Power × 1/6 h` over included periods only. Both sides therefore
  cover exactly the same periods, and the existing harness works unchanged.
- **Pressure**: the data has none. The script writes a constant surface pressure from the standard
  atmosphere at 145.6 m: `1013.25 × (1 − 2.25577e-5 × 145.6)^5.25588 ≈ 995.9 hPa`.
- **Time stamps**: the dataset's time zone and whether a stamp marks the start or end of the
  10 minutes are read from its documentation when the script is written; converted to UTC period
  start. A 10-minute shift barely changes annual energy.
- **case.yaml**: `datasheet: MM92/2050`, `hub_height_m: 78.5`, `wind_height_m: 78.5`,
  `temp_height_m: 78.5` (nacelle sensor), `losses_pct: 0`, `density_correction: true`,
  `rtol: 0.10`, `source:` dataset DOI, licence (CC-BY 4.0), fetch date, filter counts.
- **Size**: 52 704 rows × 3 columns ≈ 2 MB `inputs.csv`. Acceptable; the filtered extract with
  power and the include flag goes to `_source/` gzip-compressed for rebuilding offline.

## Tests (`kiozesim/tests/test_hawt.py`)
As in PV: test our code, not windpowerlib's physics; the physics is checked end to end only by
WIND-014. Tests needing windpowerlib are skipped without it; dev and CI install all extras.

| Req | Test idea |
|---|---|
| WIND-001 | field set equals the table; mismatched lengths, 1 point, negative or non-increasing speeds, negative power, power > 1.05 × rated, `inf` rejected |
| WIND-002 | field set and defaults equal the table; out-of-range values rejected; `roughness_length_m ≥ wind_height_m` rejected; boundaries accepted |
| WIND-003 | wind-only struct accepted; negative wind rejected naming `wind_speed_m_s`; negative temperature accepted; pressure ≤ 0 rejected |
| WIND-004 | density correction on: missing temperature, then missing pressure, each raises naming the series; off: wind-only runs, and given temperature/pressure do not change the result |
| WIND-005 | 2 h step rejected; 1 h, 10 min and 1 min accepted |
| WIND-006 | `build` with non-default values: turbine and `ModelChain` attributes as mapped; `prepare_weather` columns, heights and units (K, Pa) |
| WIND-007 | stand-in `run` with made-up W values: `simulate` applies kW, `n_turbines` and `losses_pct` |
| WIND-008 | `wind_height_m == hub_height_m`: `wind_speed_hub_m_s` equals the input |
| WIND-009 | winds below the first and above the last curve point give 0; random winds never exceed the cap |
| WIND-010 | returns `HAWTOutput`; extras on the input index; `air_density_kg_m3` is None without correction |
| WIND-011 | subprocess: `import kiozesim` leaves `windpowerlib` out of `sys.modules`; with windpowerlib hidden, `simulate` raises `ImportError` mentioning `kiozesim[wind]` |
| WIND-012 | `ModelChain` reports the pinned model names; our step-by-step `run` equals `run_model(...).power_output` |
| WIND-013 | `available()` contains the 67 library types, sorted; every one loads and validates; `bundled("MM92/2050")` field values match the CSV row |
| WIND-015 | loading all library turbines with sockets blocked (monkeypatched `socket.socket`) succeeds |
| WIND-016 | with windpowerlib hidden: `available()` is only the YAML names, `bundled("E-82/2300")` raises `ImportError` with the hint; with it, `bundled("nope")` raises `FileNotFoundError` listing names |
| WIND-014 | `run_case` on `kelmarsh1_2020` |

## Order of work
1. Reshape the models, `_library.py`, and the datasheet overrides. `_simulate` still raises.
2. Write `test_hawt.py`; model tests fail, the rest pass.
3. Write and run `make_kelmarsh_case.py`; commit `_source/` and the case (xfail until step 4).
4. Implement `_engine.py` and `_simulate` until green.
5. `pytest`, `spec_check`, `ruff`, `mypy`; set the spec to `implemented`.

## Risks
- **WIND-014 may miss ±10 %.** The nacelle anemometer sits behind the rotor; Senvion's controller
  may already correct its reading, or may not. The library curve is generic, not this site's.
  If the first run is outside ±10 %, stop and bring the numbers to the user; do not tune
  parameters or loosen the tolerance without a spec change.
- **Filtering decides the result.** Too loose (keeping stops) makes measured energy low; too strict
  could keep only "good" periods. The filter rules are written down above and the counts of kept
  and dropped periods go into `case.yaml` `source:`, so they can be reviewed.
- **Height extrapolation is not tested end to end**: Kelmarsh measures at hub height, so
  `wind_height_m = hub_height_m`. The log profile is windpowerlib's and checked only by the mapping
  test (WIND-006) and WIND-008. Accepted for v1.
- **windpowerlib internals**: `_library.py` depends on the layout of the bundled `oedb/*.csv`
  files, and `run` on the order of `run_model`'s steps. Both are pinned by tests (WIND-013,
  WIND-012), so an upgrade that changes them fails loudly.
- **windpowerlib download functions** (`fetch_turbine_data_from_oedb`) are never called;
  WIND-015 guards that.
- **Download size**: 452 MB, only for the by-hand script; tests run offline from committed files.

## Outcome (2026-10-08)
- WIND-014: 5 833 MWh modelled vs 6 215 MWh measured for Kelmarsh 1 in 2020, **−6.1 %**
  (tolerance ±10 %); without density correction −5.1 %. Kept 50 929 of 52 704 periods.
  The site's air (146 m + 78.5 m up, 12 °C average) is lighter than the curve's 1.225 kg/m³,
  so the correction lowers output, as it should.
- The library lists the MM92 rotor as 93 m; Kelmarsh says 92 m. Not used by the power-curve model.
- The datasheet spec's file rules (DS-007/008/009) clashed with library names; resolved with the
  user by adding catalogues to 0007 (DS-011). Four library turbines have no source and keep it empty.
- Bug injection (9 mutations: pressure and temperature units, wind height, density switch,
  Hellman instead of log profile, losses, `n_turbines`, library W → kW, roughness): every one
  makes a HAWT test fail.
- windpowerlib raises if `hub_height_m` ≤ half the rotor diameter (the blades would hit the
  ground). Our params do not check this; the error surfaces at `simulate`. Candidate for a spec
  addition.
