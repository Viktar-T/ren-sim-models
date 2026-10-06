---
id: 0007
title: Bundled datasheets
prefix: DS
status: implemented
---

# 0007 Bundled datasheets

## Problem
Datasheet YAML files are scattered: each sits inside its plant's code package
(`plants/<tech>/datasheets/`). To see, review or add product data you must open every plant folder.
A library user also has no public way to reach these files; they must locate the install directory and
build a path by hand. And the shipped files are made-up placeholders, not real products.

## Scope
In: moving the shipped datasheets to one central folder; listing and loading them by name; replacing
placeholders with real, sourced PV module datasheets.
Out: user-supplied datasheet catalogues; vendor/product search; unit conversion; the OEDB turbine
library used by windpowerlib (separate loader, see 0003); real datasheets for HAWT, VAWT, biogas and
boiler (added when each plant's spec is approved and its datasheet fields are final).

## Domain notes
A datasheet is the manufacturer's data for one product (a solar module, a wind turbine, a CHP engine,
a boiler), stored as YAML and checked by that plant's `Datasheet` subclass (see CORE-006).

Layout (constitution 13): one central folder with one sub-folder ("shelf") per plant type. Data and
code live apart; each shelf holds only one kind of datasheet, so names never clash across types.

```
kiozesim/datasheets/
  pv/       jinko_solar_jkm440n_54hl4r_b.yaml, ...
```

All file logic (finding the folder, listing, loading) lives once in the base `Datasheet` class in
`kiozesim/datasheet.py`. A subclass only names its sub-folder, e.g. `PVDatasheet` sets `shelf = "pv"`,
and inherits `available()` and `bundled(name)` as class methods.

A datasheet's name is its file name without `.yaml`, built from the manufacturer and model:
lower-case, every run of characters other than letters and digits replaced by `_`
(`Jinko Solar` + `JKM440N-54HL4R-B` → `jinko_solar_jkm440n_54hl4r_b`).

Bundled PV modules (chosen to cover three cell technologies; values read from the manufacturer PDF,
2026-10-06). `pdc0_w` is the rated power at standard test conditions (STC: 1000 W/m², 25 °C cell);
`gamma_pdc_per_k` is how much power drops per degree of extra cell heat, as a fraction
(−0.29 %/°C → −0.0029).

| Manufacturer | Model | Cell type | `pdc0_w` | `gamma_pdc_per_k` | Document |
|---|---|---|---|---|---|
| Jinko Solar | JKM440N-54HL4R-B | n-type TOPCon | 440 | −0.0029 | JKM425-445N-54HL4R-B-F2-EN (2022) |
| LONGi | LR5-54HTH-430M | HPBC back-contact | 430 | −0.0029 | Hi-MO X6 LR5-54HTH 420~440M, 20230926V19 |
| REC Solar | REC430AA Pure-R | heterojunction | 430 | −0.0024 | REC Alpha Pure-R, IEC AU CEC 10.2025 V4.2 |

## Requirements
- **DS-001** Bundled datasheets MUST live under `kiozesim/datasheets/<tech>/`, one sub-folder per plant type; no YAML datasheet may remain inside `kiozesim/plants/`.
- **DS-002** Every `Datasheet` subclass MUST list the names of the datasheets on its shelf via the class method `available()`, sorted; a shelf with no files MUST give an empty list.
- **DS-003** Every `Datasheet` subclass MUST load a datasheet from its shelf by name via the class method `bundled(name)`, returning a validated instance.
- **DS-004** Loading an unknown name MUST raise `FileNotFoundError` whose message lists the available names.
- **DS-005** Lookup MUST work from an installed wheel, not only from a source checkout.
- **DS-006** The path-based `from_yaml` MUST remain available and unchanged.
- **DS-007** The file logic MUST live only in `kiozesim/datasheet.py`; a subclass MUST declare nothing but its sub-folder name (a class attribute `shelf`) to get bundled lookup.
- **DS-008** Every bundled datasheet MUST be a real product: its `source` MUST name the manufacturer document and give its URL; placeholder data MUST NOT be shipped.
- **DS-009** A bundled datasheet's name MUST follow the naming rule in Domain notes.
- **DS-010** The PV shelf MUST ship the three modules in the table above, with exactly those values.

## Acceptance
For each plant, a test lists the bundled names, loads each one by name, and checks the result equals
loading the same file via `from_yaml`. A test checks no YAML is left under `kiozesim/plants/`. A test
builds the wheel and loads a datasheet from it. The example (EX-004) and golden harness load bundled
datasheets by name.

## Open questions
- [x] Shelf naming: explicit class attribute `shelf` on each subclass (DS-007).
- [x] API shape: class methods `available()` and `bundled(name)` inherited from `Datasheet` (DS-002, DS-003).
- [x] Naming: plain file name, built from manufacturer + model (DS-009).
- [x] Placeholders: not shipped; only real, sourced datasheets (DS-008). Non-PV shelves stay empty for now.
- [x] `source` required for bundled files, citing the manufacturer document (DS-008).
- [x] Example and golden harness switch to the by-name loader (EX-004 updated).

## Changelog
- 2026-10-05 draft created
- 2026-10-06 datasheets move to one central folder `kioze_sim/datasheets/<tech>/` (constitution 13);
  DS-001 added, old DS-001..005 renumbered DS-002..006
- 2026-10-06 file logic only in `kioze_sim/datasheet.py`, subclasses set `shelf` (DS-007); API is
  class methods `available()` / `bundled(name)`
- 2026-10-06 open questions resolved: real sourced PV modules only (DS-008..010), naming rule; approved
- 2026-10-06 implemented
- 2026-10-06 package renamed `kioze_sim` → `kiozesim` (0009)
