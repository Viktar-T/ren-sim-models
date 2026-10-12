# Constitution

Project-wide rules. A spec may not contradict these; change them here, deliberately.

1. **Physics first.** Models are parameter-driven physics or energy balances. ML is an optional
   correction layer added later, never the foundation (it cannot extrapolate to new designs).
2. **One plug shape.** Every technology implements `Plant.simulate(ts=None) -> PlantOutput`. `ts` is that plant's own `TimeSeries` struct (series sharing one index) or absent; no technology-specific argument is part of the shared contract.
   A **source** (spec 0016: weather, a biogas digester, a fixed test value) is a box that makes time
   series, not necessarily power. It obeys rules 3–5, 9 and 10 like a plant and implements
   `Source.simulate(index, inputs=None) -> DataFrame`. It is not in a `Portfolio`. Wiring sources to
   plants is the apps' job: the library holds boxes only, never code that wires or runs several.
3. **One time grid.** UTC tz-aware index, regular spacing, period-start labels (`kiozesim/timegrid.py`).
   Plants never resample; mixed steps are rejected and resampled explicitly by the caller.
4. **Pure and testable.** Plants are functions of (params, weather). No file I/O, plotting, or global
   state inside models.
5. **Validated parameters.** Params are frozen pydantic models with `extra="forbid"`. Bad input fails
   at construction, not mid-simulation.
6. **Do not leak engines.** pvlib, windpowerlib, oemof and FMPy objects never appear in the public API.
   They are optional extras imported lazily inside adapters.
7. **Simplest model first.** Add an effect (part-load, ramp limits, dynamics) only when a spec
   requirement demands it. Each effect is switchable.
8. **Validate against reality.** Every model spec names a reference (datasheet, published curve,
   established library) and a tolerance used in a test.
9. **Units in names.** `power_kw`, `energy_kwh`, `temp_c`. Power is average over the period.
10. **Vectorise by default.** Loops only where state forces them; measure before optimising.
11. **One module per plant.** `kiozesim/plants/<tech>/` holds that plant's pydantic params, its
    YAML datasheet model and the `Plant` subclass. Nothing shared lives there.
    Sources live the same way in `kiozesim/sources/<tech>/`.
13. **Data apart from code.** Bundled datasheets live in one place, `kiozesim/datasheets/<tech>/*.yaml`,
    one sub-folder per plant type. Plant packages hold code only.
12. **Golden datasets.** Each plant is validated by golden cases in `kiozesim/tests/golden/<tech>/<case>/`
    from an independent reference, run by `kiozesim/tests/harness.py`.
14. **Two packages, one repo.** The repository is a uv workspace with two sibling packages: the
    library `kiozesim/` and the app `kiozesim-tool/` (spec 0009), which holds the command line,
    the web UI (`kiozesim_tool.ui`) and what they share that does not belong in the library
    (spec 0017, e.g. weather sources, wiring). The library never depends on the app. Package paths such as `kiozesim/datasheets/`
    mean inside the package (`kiozesim/src/kiozesim/datasheets/`); paths such as `kiozesim/tests/`
    mean the folder in the repository.
