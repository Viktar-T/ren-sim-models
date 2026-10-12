# 0015 Gas engine (CHP): plan

How to build [spec.md](spec.md). Written 2026-10-12.

## Design in one paragraph
`CHPPlant` is a small pure-pandas plant in `kiozesim/plants/chp/plant.py`: five vectorised lines
of the spec's equations, no engine library. It replaces the `biogas` stub plant, whose package is
deleted (the digester half moves to `kiozesim/sources/digester/`, spec 0005).

## Modules touched

| File | Change |
|---|---|
| `kiozesim/src/kiozesim/plants/chp/{__init__,plant}.py` | **new**: `CHPDatasheet`, `CHPParams`, `CHPInputs`, `CHPOutput`, `CHPPlant` |
| `kiozesim/src/kiozesim/plants/biogas/` | **deleted** (stub) |
| `kiozesim/src/kiozesim/plants/__init__.py` | `REGISTRY["chp"] = CHPPlant`, `biogas` removed (CHP-008) |
| `kiozesim/src/kiozesim/datasheets/chp/*.yaml` | **new**: the three TEDOM units (CHP-009) |
| `kiozesim/tests/test_chp.py` | **new**: tests per CHP-001..010 |
| `kiozesim/tests/golden/chp/full_500kw_year/` | **new**: CHP-010 case (`golden/biogas/`, empty, removed) |
| `kiozesim/tests/test_harness.py` | CORE-008 plant list: `biogas` → `chp` |
| `kiozesim-tool/tests/test_sink.py` | prefix map: `BIO: biogas` → `CHP: chp` |
| `README.md`, `CLAUDE.md` | plant list wording |

## Models
- `CHPDatasheet(Datasheet)`: `shelf = "chp"`, `allow_inf_nan=False`; `rated_electrical_kw > 0`,
  `0 < electrical_efficiency < 1`, `0 <= thermal_efficiency < 1`; `after` validator: sum ≤ 1.
- `CHPParams(PlantParams)`: `datasheet`, `availability: float = Field(0.92, ge=0, le=1)`.
- `CHPInputs(TimeSeries)`: `fuel_kw: pd.Series`; validator rejects negatives naming `fuel_kw`.
- `CHPOutput(PlantOutput)`: `heat_kw`, `flared_kw` Series.

## Risks
- SINK-026 (spec 0011) requires every `implemented` plant type to work in the tool. The tool feeds
  plants from a weather file, which has no `fuel_kw`. Flipping 0015 to `implemented` makes that test
  fail until the tool spec says how a fuel-fed plant gets its input. Needs a user decision.
