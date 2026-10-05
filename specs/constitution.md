# Constitution

Project-wide rules. A spec may not contradict these; change them here, deliberately.

1. **Physics first.** Models are parameter-driven physics or energy balances. ML is an optional
   correction layer added later, never the foundation (it cannot extrapolate to new designs).
2. **One plug shape.** Every technology implements `Plant.simulate(ts=None) -> PlantOutput`. `ts` is that plant's own `TimeSeries` struct (series sharing one index) or absent; no technology-specific argument is part of the shared contract.
3. **One time grid.** UTC tz-aware index, regular spacing, period-start labels (`kioze_sim/timegrid.py`).
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
11. **One module per plant.** `kioze_sim/plants/<tech>/` holds that plant's pydantic params, its
    YAML datasheet model, bundled `datasheets/*.yaml` and the `Plant` subclass. Nothing shared lives there.
12. **Golden datasets.** Each plant is validated by golden cases in `tests/golden/<tech>/<case>/` from
    an independent reference, run by `tests/harness.py`.
