# 0016 Sources and wiring: plan

How to build [spec.md](spec.md). Written 2026-10-12.

## Design in one paragraph
The library gets `kiozesim/sources/base.py` (`Source`, `MissingInputError`) and
`kiozesim/sources/constant.py`; the digester becomes a `Source`. A new workspace package
`kiozesim-utils` holds what both apps share: `FileWeatherSource`, the app-side source registry and
the wiring code (check names and loops, order, join tables, run). Wiring is app code shared through
`kiozesim-utils`, never in the library (SRC-006). Each app keeps only its own surface: config
parsing in the tool, boxes and form handling in the web app.

## Library (`kiozesim`)

| File | Change |
|---|---|
| `kiozesim/errors.py` | **new**: `MissingInputError(ValueError)` with `box` and `missing`; its own module so `plants/base.py` and `sources/base.py` both import it without a cycle |
| `kiozesim/sources/base.py` | **new**: `Source(ABC, Generic[P])`: `params_model`, `name`, `simulate(index, inputs=None)` wraps `_simulate`: checks index (time grid) and `inputs.index.equals(index)`, then the output is a DataFrame on `index`; helper `_require(inputs, columns)` raises `MissingInputError` |
| `kiozesim/sources/constant.py` | **new**: `ConstantParams(name, values: dict[str, float] min 1, finite)`, `ConstantSource` |
| `kiozesim/sources/digester/digester.py` | `Digester(Source)`, `_simulate` returns the two-column DataFrame; `DigesterOutput` removed |
| `kiozesim/sources/__init__.py` | exports `Source`, `MissingInputError`, `ConstantSource`, `ConstantParams` |
| `kiozesim/plants/base.py` | `TimeSeries.from_frame` raises `MissingInputError` for absent required fields (SRC-003) |
| `kiozesim/__init__.py` | export `MissingInputError`, `Source` |

## `kiozesim-utils`

| File | Change |
|---|---|
| `kiozesim-utils/pyproject.toml` | **new** package, depends on `kiozesim` (workspace) |
| `src/kiozesim_utils/weather.py` | `FileWeatherSource(Source)`, params `name`, `path: Path`; the tool's file logic (`_day_frame(start, end, step)`) unchanged |
| `src/kiozesim_utils/sources.py` | `SOURCES = {"weather_file": FileWeatherSource, "constant": ConstantSource, "digester": Digester}` |
| `src/kiozesim_utils/wiring.py` | `Box` (name, `from_` names), `WiringError(ValueError)`, `check(boxes)` (missing `from`, unknown names, duplicates, loops: SRC-020), `order(...)` (sources topologically), `join(tables, box)` (duplicate column → `WiringError`, SRC-024), `run(sources, plants, wires, index)` → `(Portfolio frame, per-plant inputs)`; `MissingInputError` re-raised as `WiringError` naming box, sources, columns (SRC-022) |
| `kiozesim-utils/tests/` | weather tests moved from the tool (SRC-011), wiring tests |

Root `pyproject.toml`: workspace member, ruff `src`, mypy `files`, pytest `testpaths`.

## Tool
- `config.py`: `Config.sources: list[dict]` (min 1), `weather` key rejected with a hint (SRC-030);
  `build_sources(entries, base)` via `SOURCES`, relative `Path` fields resolved against the config
  folder; plants keep `from` (str or list) out of their params.
- `cli.py`: `simulate_chunk` builds the index and calls `kiozesim_utils.wiring.run`.
- `weather.py` removed (SRC-012); `examples/*.yaml` use `sources:`; `sink.yaml` adds
  digester → `chp` (SRC-031).

## Web app
- `sample_weather.csv` becomes a dateless `HH:MM` day; the run covers 2026-06-21 (UI-011).
- `form.py`: a second box list, sources, posted as `s{i}.…` with count `ns`; source types
  `sample weather`, `constant`, `digester`. `from` tick boxes posted as `p{i}.from.{j}` = source name.
  Fields that are not number/bool/choice/datasheet/str (e.g. `values`, `substrates`) render as a YAML
  textarea and are parsed with `yaml.safe_load` (SRC-042).
- `app.py`/`page.html`: two columns (CSS grid `auto-fit`, columns at least one plant box wide, so sources drop below when both do not fit); stylesheet linked with a content hash so browsers do not keep a stale copy, source **+**/Remove/Apply
  actions `add_source`, `remove_source:i` (SRC-043); first page one PV box wired to one sample
  weather box (SRC-044); `OFFERED` gains `chp`.
- Wiring errors appear on the plant box (SRC-022).

## Risks
- Every existing tool and UI test posts plants without wiring; their helpers gain a default
  weather source and `from`.
