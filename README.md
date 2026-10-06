# kiozesim

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
uv sync --all-packages --all-extras
uv run pytest && uv run python scripts/spec_check.py
```

## Layout

One repository, three packages (a uv workspace, spec 0009):

```
pyproject.toml                    workspace: lists the packages + shared dev tools
kiozesim/                         the library
  src/kiozesim/
    datasheet.py  timegrid.py  portfolio.py
    datasheets/<tech>/*.yaml      producer data, one folder per plant type (Datasheet.bundled)
    plants/
      base.py                     Plant interface
      pv/ hawt/ vawt/ biogas/ boiler/
        plant.py                  Params + Datasheet + Inputs (pydantic v2) + Plant
  tests/golden/<plant>/<case>/    golden datasets; tests/harness.py runs them
  examples/                       runnable scripts, e.g. uv run python kiozesim/examples/pv.py
kiozesim-tool/src/kiozesim_tool/  command-line tool (skeleton)
kiozesim-ui/src/kiozesim_ui/      web app (skeleton)
specs/                            specs + constitution, for all packages
scripts/                          spec_check.py
```
