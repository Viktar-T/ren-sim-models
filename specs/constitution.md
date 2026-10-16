# Constitution

Project-wide rules. A spec may not contradict these; change them here, deliberately.

1. **Physics first.** Models are parameter-driven physics or energy balances. ML is an optional
   correction layer added later, never the foundation (it cannot extrapolate to new designs).
2. **One plug shape.** Every technology implements `Plant.simulate(ts=None) -> PlantOutput`. `ts` is that plant's own `TimeSeries` struct (series sharing one index) or absent; no technology-specific argument is part of the shared contract.
   Every plant also runs one step at a time (`step`, spec 0019): its memory is handed in and back,
   never kept in the plant. Plants chain front to back; the library's `Chain` runs a chain (requests
   back, supplies forward) and sizes it. A **source** (spec 0016: weather, a fixed test value) is
   the tool's word for what feeds a chain; sources and wiring sources to plants live in the tool
   (`kiozesim_tool`), never in the library.
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
10. **Vectorise by default.** Loops only where state forces them (a plant with memory, and the plants
    that answer its requests, spec 0019); measure before optimising.
11. **One module per plant.** `kiozesim/plants/<tech>/` holds that plant's pydantic params, its
    YAML datasheet model and the `Plant` subclass. Nothing shared lives there.
13. **Data apart from code.** Bundled datasheets live in one place, `kiozesim/datasheets/<tech>/*.yaml`,
    one sub-folder per plant type. Plant packages hold code only.
12. **Golden datasets.** Each plant is validated by golden cases in `kiozesim/tests/golden/<tech>/<case>/`
    from an independent reference, run by `kiozesim/tests/harness.py`.
14. **Two packages, one repo.** The repository is a uv workspace with two sibling packages: the
    library `kiozesim/` and the app `kiozesim-tool/` (spec 0009), which holds the command line,
    the web UI (`kiozesim_tool.ui`) and what they share that does not belong in the library
    (spec 0017, e.g. sources, wiring sources to plants). The library never depends on the app. Package paths such as `kiozesim/datasheets/`
    mean inside the package (`kiozesim/src/kiozesim/datasheets/`); paths such as `kiozesim/tests/`
    mean the folder in the repository.
