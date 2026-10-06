# 0007 Bundled datasheets: plan

How to build [spec.md](spec.md).

## Design in one paragraph
`Datasheet` in `kiozesim/datasheet.py` gains a class attribute `shelf: ClassVar[str | None]` and two
class methods. `available()` lists `*.yaml` stems in `kiozesim/datasheets/<shelf>/`; `bundled(name)`
reads that file and validates it through `model_validate`, the same path `from_yaml` uses. Files are
reached with `importlib.resources.files("kiozesim")`, which works for a source checkout, an installed
wheel and a zipped wheel alike (DS-005). A class without `shelf` raises `TypeError`. Each plant's
datasheet subclass adds one line, `shelf = "<tech>"`. Hatch already ships every file under
`src/kiozesim`, so no packaging change is needed.

## Modules touched

| File | Change |
|---|---|
| `kiozesim/src/kiozesim/datasheet.py` | `shelf`, `available()`, `bundled(name)` |
| `kiozesim/src/kiozesim/plants/*/plant.py` | `shelf = "<tech>"` on each datasheet class; docstring points to `bundled` |
| `kiozesim/src/kiozesim/plants/*/datasheets/` | **deleted** (placeholders) |
| `kiozesim/src/kiozesim/datasheets/pv/*.yaml` | **new**: the three modules of DS-010 |
| `kiozesim/tests/test_datasheets.py` | DS-001..010 tests; CORE-006 bundled test uses `available()` |
| `kiozesim/tests/harness.py`, `kiozesim/tests/golden/README.md` | fallback: a non-file `datasheet:` is a bundled name |
| `kiozesim/examples/pv.py`, `kiozesim/tests/test_examples.py` | EX-004: `PVDatasheet.bundled("jinko_solar_jkm440n_54hl4r_b")`; 10 × 440 W = 4.4 kWp |
| `README.md` | layout shows `datasheets/<tech>/` |

## Risks
- The wheel test (DS-005) needs `uv build`, which needs hatchling; skip with a clear reason if the
  build fails offline rather than pass silently.
