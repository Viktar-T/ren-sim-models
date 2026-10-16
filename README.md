# kiozesim

Simulate power generating installations from parameters and weather.

Plants: PV (pvlib), HAWT (windpowerlib), VAWT (custom DMST/Cp model), biogas digester (Buswell-Boyle),
combustion plant (gas engines/CHP and boilers), heat store (oemof.thermal). Plants chain front to back,
e.g. digester -> engine -> heat store, run step by step by `kiozesim.Chain` (spec 0019). See `specs/`.

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

One repository, two packages (a uv workspace, specs 0009 and 0017):

```
pyproject.toml                    workspace: lists the packages + shared dev tools
kiozesim/                         the library
  src/kiozesim/
    datasheet.py  timegrid.py  portfolio.py  chain.py (plant chains, sizing)
    datasheets/<tech>/*.yaml      producer data, one folder per plant type (Datasheet.bundled)
    plants/
      base.py                     Plant interface (simulate, and one step at a time)
      pv/ hawt/ vawt/ combustion/ digester/ heat_store/
        plant.py                  Params + Datasheet + Inputs (pydantic v2) + Plant
  tests/golden/<plant>/<case>/    golden datasets; tests/harness.py runs them
  examples/                       runnable scripts, e.g. uv run python kiozesim/examples/pv.py
kiozesim-tool/src/kiozesim_tool/  the app: `kiozesim-tool sink`, `size` and `ui`
  boxes.py  wiring.py  sources.py plant/source types, wiring, sources (constant)
  weather.py  sizing.py           weather sources, sizing a chain
  ui/                             web app (`kiozesim-tool ui`)
specs/                            specs + constitution, for all packages
scripts/                          spec_check.py
```
