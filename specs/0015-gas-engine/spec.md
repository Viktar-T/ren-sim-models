---
id: 0015
title: Gas engine (CHP)
prefix: CHP
status: implemented
---

# 0015 Gas engine (CHP)

## Problem
Estimate how much electricity and heat a gas engine delivers in each time step, given how much fuel
gas flows to it. The fuel can come from a biogas digester (spec 0005) or any other source the caller
describes as a fuel energy flow. The result is electric power in kW, the same shape as every other
plant, so it can go into a `Portfolio`; heat is reported next to it.

## Scope
In:
- One engine-generator unit, fed a fuel time series `fuel_kw`.
- Electrical and thermal efficiency at full load, size limit, availability.
- Fuel the engine cannot burn is reported as flared.
- Bundled datasheets of three real biogas CHP units.

Out (each may get its own spec later):
- Several units in one plant (use several plants in a `Portfolio`, each with its share of the fuel).
- Part-load efficiency, minimum load, start/stop limits, ramping.
- Gas store and running at chosen hours (dispatch).
- Fuel types: the engine sees only energy, not gas composition.
- The plant's own electricity use and digester heating: output is gross.
- Heat demand and heat use.

## Domain notes

### What a CHP is
A **CHP** (combined heat and power) unit is a gas engine, like a big car engine, driving a
generator. It turns part of the fuel's energy into electricity and recovers most of the rest as hot
water from the engine's cooling water and exhaust; that hot water heats the digester, buildings or
a district heating network. The remainder is lost with the exhaust.

### Fuel as energy
The engine's input is `fuel_kw`: the energy of the gas flowing in, per hour on average, measured by
its **lower heating value** (the usual basis on CHP datasheets). A digester gives this directly
(0005); for other gases, multiply the volume flow by the gas's heating value (natural gas
≈ 10 kWh/Nm³).

### The engine
- **Rated electrical power** `rated_electrical_kw`: the maximum electric output.
- **Electrical efficiency**: the fraction of fuel energy turned into electricity at full load
  (≈ 0.35–0.43 for biogas engines; bigger engines are more efficient).
- **Thermal efficiency**: the fraction recovered as useful heat at full load (≈ 0.40–0.50).
  The two sum to less than 1.
- At full load the engine burns `rated_electrical_kw / electrical_efficiency` kW of fuel; more fuel
  than that cannot be used and goes to the **flare** (a safety torch).
- **Availability**: the fraction of time the engine runs, the rest being maintenance and
  breakdowns. Well-run plants reach 0.90–0.95 (8000+ hours a year). v1 applies it as an average to
  every period (each period gets that fraction of full output), not as random outages. While the
  engine is down, its fuel is flared.

### Simplifications in v1
- The same efficiencies at every load. Real engines are a few points less efficient at part load.
- No minimum load. A real engine cannot run below about half load; with too little gas it runs in
  on/off cycles using a small gas buffer, which gives about the same average. This matters once a
  gas store and dispatch are modelled.

### Equations
In each period:

```
fuel_max_kw = rated_electrical_kw / electrical_efficiency
burned_kw   = availability × min(fuel_kw, fuel_max_kw)
power_kw    = burned_kw × electrical_efficiency
heat_kw     = burned_kw × thermal_efficiency
flared_kw   = fuel_kw − burned_kw
```

### Bundled datasheets
Three real biogas CHP units, small, medium and large (values read from the manufacturer documents;
gross electrical and thermal output at full load, lower heating value basis):

| Manufacturer | Model | `rated_electrical_kw` | `electrical_efficiency` | `thermal_efficiency` | Document |
|---|---|---|---|---|---|
| TEDOM | Cento 100 (biogas) | 106 | 0.366 | 0.490 | [1] |
| TEDOM | Cento 200 (biogas) | 200 | 0.391 | 0.479 | [1] |
| TEDOM | Flexi 530 (biogas) | 528 | 0.402 | 0.445 | [1] |

[1] TEDOM, *CHP Units – Overview of manufactured types*, 03/2025, table "Biogas – Basic Technical
Data", https://www.tedom.com/wp-content/uploads/2023/12/TEDOM-CHP-Units-50-Hz.pdf (read 2026-10-12).
One document for all three keeps the basis the same: biogas (also sewage and landfill gas), full
load, ISO 3046-1. Each efficiency checks against the document's output ÷ fuel input (e.g. Flexi 530:
528 / 1313 = 0.402). TEDOM's own Cento 100 datasheet (2018) confirms the lower heating value basis
(65 % methane biogas, 44.7 Nm³/h × 23.4 MJ/Nm³ = 290.6 kW fuel). File names follow DS-009, e.g.
`tedom_cento_100_biogas`.

### References
- ISO 3046-1, reciprocating internal combustion engines: performance (the rating basis of most CHP
  datasheets).

## Interface

`CHPDatasheet` (unit product data, YAML in `kiozesim/datasheets/chp/`):

| Field | Unit | Allowed | Meaning |
|---|---|---|---|
| `manufacturer`, `model`, `source` | – | – | from `Datasheet` |
| `rated_electrical_kw` | kW | > 0 | maximum electric output |
| `electrical_efficiency` | – | 0 < x < 1 | fuel energy → electricity, full load |
| `thermal_efficiency` | – | 0 ≤ x < 1 | fuel energy → useful heat, full load; the two together ≤ 1 |

`CHPParams`:

| Field | Unit | Default | Allowed | Meaning |
|---|---|---|---|---|
| `name` | – | required | – | plant name (from `PlantParams`) |
| `datasheet` | – | required | – | a `CHPDatasheet` |
| `availability` | – | 0.92 | 0 ≤ x ≤ 1 | fraction of time the engine runs |

`CHPInputs` (`TimeSeries`):

| Field | Unit | Required | Allowed |
|---|---|---|---|
| `fuel_kw` | kW | yes | ≥ 0, fuel energy flow (lower heating value), average over the period |

`CHPOutput` (`PlantOutput` subclass, all Series on the input index):

| Field | Unit | Meaning |
|---|---|---|
| `power_kw` | kW | electricity produced (gross), average over the period |
| `heat_kw` | kW | useful heat produced (gross), average over the period |
| `flared_kw` | kW | fuel not burned (engine full or down) |

## Requirements

Parameters and inputs
- **CHP-001** `CHPDatasheet` MUST have exactly the fields of the `CHPDatasheet` table and MUST reject values outside the allowed ranges, including efficiencies that sum to more than 1, at load time.
- **CHP-002** `CHPParams` MUST have exactly the fields, units, defaults and allowed ranges of the `CHPParams` table and MUST reject any value outside them at construction.
- **CHP-003** `CHPInputs` MUST require `fuel_kw` and MUST reject negative values with an error naming the series.

Model
- **CHP-004** In each period, `power_kw`, `heat_kw` and `flared_kw` MUST follow the equations in Domain notes, so the engine never burns more than `fuel_max_kw` and `fuel_kw = burned_kw + flared_kw`.
- **CHP-005** `simulate` MUST return a `CHPOutput` whose `power_kw`, `heat_kw` and `flared_kw` are Series on the input index.
- **CHP-006** A period with 0 `fuel_kw`, or a plant with `availability` 0, MUST give 0 `power_kw` and 0 `heat_kw`.
- **CHP-007** The gas engine MUST need no package beyond the library's core dependencies.
- **CHP-008** `CHPPlant` MUST be registered in `REGISTRY` as `chp`, replacing the `biogas` stub.

Datasheets
- **CHP-009** The `chp` shelf MUST ship the units in the "Bundled datasheets" table, with exactly those values.

Validation
- **CHP-010** A 500 kW unit with electrical efficiency 0.40 and availability 0.90, fed more fuel than it can burn for one year of hourly steps, MUST produce 3942 MWh of electricity (450 kW average) within ±0.1 %.

## Acceptance
- Every CHP-xxx requirement has at least one test marked with its ID; `uv run pytest`,
  `uv run python scripts/spec_check.py`, `ruff` and `mypy` are green.
- `kiozesim/tests/golden/chp/` holds the CHP-010 case.

## Open questions
- [x] Bundled units: TEDOM Cento 100, Cento 200 and Flexi 530 (biogas), all from one TEDOM document
      (chosen 2026-10-12). Backups if wanted: 2G agenitor 404/406/412, MWM TCG 3016 V08/V12.

## Changelog
- 2026-10-12 created: the CHP half of the former biogas spec 0005, fed by a fuel time series
  `fuel_kw` (from the digester or any other source); heat as `heat_kw` on `CHPOutput`
- 2026-10-12 bundled units chosen: TEDOM Cento 100, Cento 200, Flexi 530 (biogas)
- 2026-10-12 approved
- 2026-10-12 implemented; usable in both apps through sources and wiring (0016)
