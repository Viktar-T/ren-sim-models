---
id: 0020
title: Charts of every output
prefix: PLOT
status: implemented
---

# 0020 Charts of every output

## Problem
The web page charts electricity only (UI-015, CHAIN-041). Since plant chains (0019) many plants
report other things too: a boiler's heat, the gas an engine leaves, a tank's content, heat
delivered and demand not met. A heat-only chain shows a flat zero line and nothing else, although
all those numbers are worked out. Show them.

## Scope
In:
- After a run, one extra chart per output field, below the power chart, one line per plant.

Out:
- Totals or energy sums for the new fields (the energy table stays electricity only, UI-014).
- Sending the new fields to sinks (the stream stays `power_kw`, CHAIN-041).
- Choosing which charts to show; showing source tables (weather, demand).

## Domain notes
Every plant output has its unit in its name (constitution 9): `heat_kw` is an average power in
kW, `stored_kwh` an amount in kWh at the end of each step, `methane_nm3_per_h` a gas flow. A chart
per field keeps one unit per chart, so lines on one chart can be compared. The field name is the
chart's title and the y-axis label.

The data is the per-plant output table the tool already gets from a run (`RunResult.outputs`,
0019); nothing is simulated again.

## Requirements
- **PLOT-001** After a run the page MUST show, below the power chart (UI-015), one chart per output field other than `power_kw` that at least one plant reports, titled with the field name, with one line per plant reporting it, labelled with the plant name.
- **PLOT-002** The extra charts MUST come in the order the fields first appear going through the plants top to bottom and, within a plant, in its output order.
- **PLOT-003** The extra charts MUST be drawn like the power chart (UI-015): on the server with matplotlib, as SVG inside the page, with no JavaScript.
- **PLOT-004** The values charted MUST be the run's per-plant outputs (`RunResult.outputs`) unchanged; single values (e.g. a digester's) are drawn as flat lines.

## Acceptance
- Every PLOT-xxx requirement has at least one test marked with its ID; `uv run pytest`,
  `uv run python scripts/spec_check.py`, `ruff` and `mypy` are green.
- Spec edit on approval: CHAIN-041 reads "The power chart, the stream and the electricity total
  MUST use every plant's `power_kw` only".

## Open questions
None.

## Changelog
- 2026-10-15 draft
- 2026-10-15 approved
- 2026-10-15 implemented (`kiozesim_tool/ui/chart.py` `output_svgs`, page template)
