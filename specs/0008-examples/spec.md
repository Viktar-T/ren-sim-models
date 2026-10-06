---
id: 0008
title: Examples folder
prefix: EX
status: implemented
---

# 0008 Examples folder

## Problem
A new user should be able to see how the library is used in a minute, without reading tests or specs.
An `examples/` folder holds short, runnable scripts that show the typical flow: describe a plant,
give it weather, run `simulate`, look at the result. For now it has one script, for PV.

## Scope
In:
- A flat `examples/` folder at the repository root (plain scripts next to each other, no sub-folders,
  no package).
- One PV example script and the small weather CSV it reads.

Out:
- Examples for other plants (added when those plants are implemented).
- Notebooks, plotting, fetching real weather from the internet.

## Domain notes
- *GHI* (global horizontal irradiance): how much sunlight, in W/m², lands on flat ground. The PV
  plant needs it plus air temperature and wind speed (wind cools the panels).
- The example is a demonstration, not a validation: its numbers only need to look sensible. Accuracy
  is covered by the PV golden case (spec 0002).

## Requirements
- **EX-001** The `examples/` folder MUST be flat: only files, no sub-folders and no `__init__.py`.
- **EX-002** `examples/pv.py` MUST run to completion with `uv run python examples/pv.py` after
  `uv sync --all-extras`, without network access and without arguments.
- **EX-003** `examples/pv.py` MUST use only the public API (`kioze_sim`, `kioze_sim.plants.pv`), never
  modules whose name starts with `_`.
- **EX-004** `examples/pv.py` MUST load a real bundled module datasheet by name via
  `PVDatasheet.bundled(...)` (see 0007), not by building a file path.
- **EX-005** `examples/pv.py` MUST read its weather from `examples/pv_weather.csv`: one day of hourly
  rows with columns `time` (UTC, ISO 8601), `ghi_w_m2`, `temp_air_c`, `wind_speed_m_s`, found relative
  to the script so it runs from any working directory.
- **EX-006** `examples/pv.py` MUST print, as plain text only, the AC power per time step and the total
  energy in kWh.
- **EX-007** The example MUST be short enough to read top to bottom: at most 80 lines, with comments
  explaining each step in plain words.

## Acceptance
A test runs `examples/pv.py` in a subprocess, checks it exits with code 0 and that its output contains
a total in kWh; another test checks the folder is flat and the script imports no private module.

## Open questions
- [x] Weather source: a tiny CSV next to the script (EX-005).
- [x] Output: printed text only, no chart (EX-006).

## Changelog
- 2026-10-06 created
- 2026-10-06 open questions resolved (CSV weather, text output), approved
- 2026-10-06 implemented
- 2026-10-06 EX-004: load a real bundled datasheet by name via `PVDatasheet.bundled` (0007)
