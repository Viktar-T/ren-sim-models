---
id: 0016
title: Sources and wiring
prefix: SRC
status: implemented
---

# 0016 Sources and wiring

## Problem
The apps feed every plant from one weather table. That works while every plant runs on weather, but
the gas engine (0015) runs on fuel made by a digester (0005), and later plants will run on other
plants' or sources' outputs (heat, stored gas). The apps must not learn plant types to handle this.

The idea: everything that produces time series is a **source**, a box with settings, optional
inputs and named outputs. Weather is a source, a fixed value is a source, the digester is a source.
In the apps, each plant (and each source that has inputs) is **wired** to a source by name. The app
runs that source and hands its output table to the plant. If a column the plant needs is missing,
the plant raises an error and the app reports "wrong source".

```
[weather: sample day] ──▶ [PV roof]     ──▶ power
[digester farm]       ──▶ [CHP engine]  ──▶ power, heat
[constant: fuel_kw 1500] ─▶ [CHP test]  ──▶ power, heat   (testing a plant without a real source)
```

## Scope
In:
- Library: a generic `Source` base class; the digester and a fixed-value test source as sources;
  clear missing-column errors from sources and plant inputs.
- A fourth workspace package, `kiozesim-utils`, holding what both apps share and the library
  should not hold; first content: the weather sources (the tool's file weather moves there).
- Tool and web app: named sources, explicit wiring of every plant and source with inputs, running
  sources in wiring order, reporting wrong wiring.
- The gas engine usable in both apps (unblocks marking 0015 `implemented`).

Out:
- Wiring or running logic in the library (constitution 2, 14): the library provides boxes only.
- Plants as sources (a plant's `heat_kw` feeding something); later, when a consumer exists.
- Weather from an online service; showing source outputs (gas) on the chart.

## Domain notes

### Boxes and wires
A **source** has settings (a frozen pydantic model, like plant params), may take an input table, and
returns an output table: a DataFrame whose columns are its outputs, on a requested time axis. It does
no wiring itself; it neither knows nor asks where its input comes from.

A **wire** exists only in an app: "box B takes its input from source A". The app keeps the list of
sources and boxes, looks up A, runs it on the time axis, and passes A's output table to B. A box
wired to the wrong source finds a column missing and raises `MissingInputError`; the app shows that
as a wiring error on B. Every plant is wired; there is no default source.

### Why sources get the time axis
A source without inputs (weather, a fixed value) still needs to know which time steps to fill. So
every source is asked for its output on an explicit time axis (`index`), with its input table, if
it has one, on that same axis. All boxes in one run share one time grid (constitution 3).

### Where things live
| Thing | Package | Why |
|---|---|---|
| `Source` base, `MissingInputError` | `kiozesim` (`kiozesim/sources/`) | the contract every box follows |
| `Digester`, `ConstantSource` | `kiozesim` | pure models, no I/O |
| `FileWeatherSource` | `kiozesim-tool` (`kiozesim_tool.weather`; was `kiozesim-utils`, spec 0017) | reads files; weather fetching is not the library's job (0001) |
| wiring, ordering, loop checks, error display | `kiozesim-tool` (command line and web UI) | app work |

Since spec 0017 the web UI and `kiozesim-utils` are part of `kiozesim-tool`; the library does not
depend on it.

## Interface

`kiozesim.sources.Source` (abstract, generic over its params model):

| Member | Meaning |
|---|---|
| `params_model: ClassVar[type[BaseModel]]` | its settings model |
| `__init__(params)`, `params`, `name` | as `Plant` |
| `simulate(index, inputs=None) -> pd.DataFrame` | output columns on `index`; `inputs` a DataFrame on `index`, or `None` |

`MissingInputError(ValueError)`: raised when a needed input column is absent; attribute
`missing: tuple[str, ...]`.

`ConstantSource` params: `name`, `values: dict[str, float]` (≥ 1 entry, finite). Output: one column
per entry, the value repeated on every step. It is for **testing** a plant without a real source,
e.g. a gas engine on `fuel_kw: 1500`; real models (feed, weather) do not use it.

`Digester` (0005) as a source with no inputs (its feed is a setting): output columns `fuel_kw`,
`methane_nm3_per_h`.

`kiozesim_tool.weather.FileWeatherSource`: today's tool file weather (one dateless day, `HH:MM` UTC,
tiled onto every date, averaged or interpolated to the requested step), as a `Source` with no inputs.

### Tool config
```yaml
sources:
  - {type: weather_file, name: weather, path: day_weather.csv}
  - {type: digester, name: farm, substrates: [{name: maize silage, fresh_t_per_day: 40, ...}]}
  - {type: constant, name: test fuel, values: {fuel_kw: 1500}}   # testing only
plants:
  - {type: pv, name: roof, from: weather, datasheet: ..., ...}     # one source: a name
  - {type: x, name: y, from: [weather, farm], ...}                  # several: a list
  - {type: chp, name: engine, from: farm, datasheet: tedom_flexi_530_biogas}
```
The top-level `weather:` key is removed; it becomes a `weather_file` source.

### Web page
Two columns: plant boxes on the left, as today, and source boxes on the right, handled the same way:
a type selector with **Apply**, a **Remove** button, and a **+** button below the last box. On a
narrow screen the source column moves below the plant column. Source types offered: `sample weather` (the UI's sample day),
`constant`, `digester`. Each plant box, and each source box with inputs, gets a **from** list of
tick boxes, one per source on the page. A digester's substrates are typed as YAML text, one list
entry per substrate with the `Substrate` fields. The chart and energy totals show plants only.

### Several sources into one box
A box may be wired to several sources, e.g. a future heat model needing both an engine's heat and
the weather's air temperature. The app joins their output tables side by side. If two of them give
a column with the same name, the app cannot know which one is meant, so that is a wiring error.

## Requirements

Library
- **SRC-001** `kiozesim.sources` MUST define an abstract `Source` with `params_model`, `name` and `simulate(index, inputs=None)` returning a DataFrame on exactly `index`; `index` MUST follow the time-grid rules (CORE-002), and `inputs`, when given, MUST be on `index`.
- **SRC-002** A source whose needed input columns are absent from `inputs` (or `inputs` is `None`) MUST raise `MissingInputError` naming the source and every missing column.
- **SRC-003** `TimeSeries.from_frame` MUST raise `MissingInputError` naming every required field the frame lacks.
- **SRC-004** `Digester` MUST be a `Source` with no inputs whose output columns are `fuel_kw` and `methane_nm3_per_h`, with the values of 0005.
- **SRC-005** `ConstantSource` MUST output one column per entry of `values`, holding that value on every step of `index`, and MUST reject an empty or non-finite `values`.
- **SRC-006** The library MUST NOT contain wiring, ordering or running of several boxes, and MUST NOT import the app (`kiozesim_tool`).

Weather package
SRC-010 is retired: the shared package was folded into `kiozesim-tool` (APP-001, spec 0017).
- **SRC-011** `kiozesim_tool.weather.FileWeatherSource` MUST be a `Source` with no inputs and MUST keep the file rules and resampling of SINK-041, SINK-042 and SINK-044.
- **SRC-012** The apps MUST get weather only through the `kiozesim_tool.weather` sources; no other app module MAY define a weather source.

Apps (both)
- **SRC-020** Every plant, and every source that takes inputs, MUST be wired to one or more sources by name; a missing wire, an unknown name, a duplicate name across sources and plants, or a wiring loop MUST be rejected before simulating, with a message naming the box.
- **SRC-021** The app MUST run each source at most once per run, after the sources it is wired to, and pass every box the output tables of its sources joined side by side.
- **SRC-024** When two sources wired into one box both output a column of the same name, the app MUST reject the wiring, naming the box, the column and both sources.
- **SRC-022** A `MissingInputError` from a box MUST be shown as a wiring error naming the box, its source and the missing columns, not as a crash.
- **SRC-023** The gas engine (`chp`) MUST be usable in both apps, wired to a digester or a constant source.

Tool
- **SRC-030** The config MUST have `sources:` (each with `type`, `name`, its settings and, if it takes inputs, `from`) and every `plants:` entry MUST have `from` (a source name or a list of names); source types MUST be `weather_file`, `open_meteo` (WX-030), `constant` and `digester`. The `weather:` key MUST be rejected with a message pointing to `sources:`.
- **SRC-031** `kiozesim-tool/examples/sink.yaml` MUST wire its weather plants to a `weather_file` source and MUST also contain a digester → `chp` chain, and MUST run at `speed: 0`.

Web app
- **SRC-043** Source boxes MUST sit in a column to the right of the plant boxes and MUST behave like plant boxes (UI-004, UI-005, UI-019): a type selector with **Apply**, a **Remove** button (not on the last source box), and a **+** button below the last source box that adds one, keeping everything typed in all boxes.
- **SRC-044** The first page MUST show one plant box and one `sample weather` source box, with that plant wired to it; boxes added later start unwired.
- **SRC-040** The page MUST offer source boxes of types `sample weather`, `online weather` (WX-040), `constant` and `digester`, and a **from** list of tick boxes on each plant box and each source box with inputs, one per source on the page.
- **SRC-042** A digester box MUST take its substrates as YAML text (a list of `Substrate` field mappings) and MUST show a substrate error (bad YAML, a field out of range, a bad formula) on that box.
- **SRC-041** `sample weather` MUST be a `FileWeatherSource` reading the UI's sample day.

## Acceptance
- Every SRC-xxx requirement has at least one test marked with its ID; `uv run pytest`,
  `uv run python scripts/spec_check.py`, `ruff` and `mypy` are green.
- Spec edits on approval: 0001 (sources in the library), 0005 (BIO-002: digester is a `Source`),
  0010 (UI-011 weather via `kiozesim_utils`), 0011 (SINK-020, SINK-021, SINK-040..046 moved or
  replaced by SRC-011/030/031), constitution 2 (fuel source → source) and 14 (four packages).
- After implementation 0015 can be set to `implemented`: UI-005 and SINK-026 pass with `chp`.

## Open questions
- [x] **Every plant wired explicitly**: yes, no default source (decided 2026-10-12).
- [x] **Weather location**: its own package used by both apps, not the library (decided 2026-10-12).
- [x] **Wiring in the library**: none; the library gives boxes, the apps wire (decided 2026-10-12).
- [x] **One source or several per box**: several; tables joined, a column given twice is a
      wiring error (SRC-020, SRC-024; decided 2026-10-12).
- [x] **Substrates in the web form**: YAML text box (SRC-042; decided 2026-10-12).
- [x] **Digester feed**: a setting of the digester, not an input; `ConstantSource` only for
      testing a plant without a real source (decided 2026-10-12).
- [x] **`ConstantSource` location**: the library (decided 2026-10-12).
- [x] **Package name**: `kiozesim-utils`, import `kiozesim_utils` (decided 2026-10-12).

## Changelog
- 2026-10-12 draft: generic `Source` box in the library, wiring only in the apps, weather in its own
  package, every plant wired explicitly
- 2026-10-12 digester feed is a setting (0005), so the digester has no inputs; `ConstantSource`
  kept for testing only
- 2026-10-12 open questions resolved: several sources per box (SRC-024), substrates as YAML
  (SRC-042), `ConstantSource` in the library, shared package named `kiozesim-utils`
- 2026-10-12 web page: sources in a right-hand column, same box handling as plants (SRC-043);
  first page one plant wired to one sample weather source (SRC-044)
- 2026-10-12 approved
- 2026-10-12 implemented (`kiozesim/sources/`, `kiozesim-utils`, tool and web app)
- 2026-10-12 one app package (0017): `kiozesim-utils` folded into `kiozesim-tool`; SRC-010
  retired, SRC-006, SRC-011, SRC-012 name `kiozesim_tool`
- 2026-10-13 real weather (0018): source type `open_meteo` (SRC-030) and page box `online weather`
  (SRC-040); `weather_file` also reads dated files (WX-020)
