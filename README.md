# kioze-sim

Simulate power generating installations from parameters and weather.

Planned plants: PV (pvlib), HAWT (windpowerlib), VAWT (custom DMST/Cp model), biogas (Buswell-Boyle + CHP),
boiler with heat store (oemof.thermal, optional FMU). See `specs/` for the status of each.

```python
ds = PVDatasheet.from_yaml("module.yaml")      # producer datasheet
plant = PVPlant(PVParams(name="roof", datasheet=ds, ...))
out = plant.simulate(PVInputs.from_frame(weather_df))   # one TimeSeries struct, or none
out.power_kw                                            # pd.Series (or float if no input)
```

Development is spec-driven; see [specs/README.md](specs/README.md).

```bash
uv sync
uv run pytest && uv run python scripts/spec_check.py
```

## Layout

```
src/kioze_sim/
  datasheet.py  timegrid.py  portfolio.py
  plants/
    base.py                       Plant interface
    pv/ hawt/ vawt/ biogas/ boiler/
      plant.py                    Params + Datasheet + Inputs (pydantic v2) + Plant
      datasheets/*.yaml           producer data
specs/                            specs + constitution
tests/golden/<plant>/<case>/      golden datasets; tests/harness.py runs them
```
