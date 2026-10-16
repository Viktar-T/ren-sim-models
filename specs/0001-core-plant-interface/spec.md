---
id: 0001
title: Core plant interface
prefix: CORE
status: implemented
---

# 0001 Core plant interface

## Problem
Every technology (PV, wind, biogas, boiler) must be usable the same way so plants can be mixed in a portfolio.

## Scope
In: `Plant` ABC, params / `TimeSeries` / output base models, time-grid rule, `Portfolio`, datasheet loading, golden-dataset harness, per-plant module layout.
Out: any concrete technology; weather fetching; resampling helpers; dispatch/optimisation (oemof layer). Running plants one step at a time in chains: spec 0019.

## Requirements
- **CORE-001** `Plant` MUST be abstract and generic over its own params, time-series struct and output model; `simulate(ts=None)` MUST take at most one argument, a plant-specific `TimeSeries` struct, and nothing technology-specific (weather, demand) is part of the shared signature. Subclasses implement `_simulate` only.
- **CORE-002** A `TimeSeries` struct MUST hold `pd.Series` fields that all share ONE index, which MUST be tz-aware UTC, strictly increasing, regularly spaced and period-start labelled; series with different steps or any NaN MUST be rejected (resampling is the caller's explicit job).
- **CORE-003** Plant parameter models MUST be immutable and reject unknown fields.
- **CORE-004** A plant that declares a `TimeSeries` MUST return a `PlantOutput` whose `power_kw` is a Series named `power_kw`, finite, >= 0, on the input's index; a plant that declares none MUST be called without one and MUST return a scalar steady-state `power_kw`. Wrong or missing structs MUST raise.
- **CORE-005** `Portfolio.simulate` MUST take a TimeSeries per plant name (omitted for no-input plants) and return one column per plant plus `total`; it MUST reject duplicate names, plants on different time axes, and portfolios with no time-series plant. Scalar plants are broadcast onto the common axis.
- **CORE-006** Producer data MUST live in YAML under `kiozesim/datasheets/<tech>/` and be loaded through a pydantic `Datasheet` subclass that rejects unknown fields.
- **CORE-007** The golden harness MUST discover `kiozesim/tests/golden/<plant>/<case>/` cases and fail when output differs from the expected values beyond the case tolerance.
- **CORE-008** Each technology MUST be its own package under `kiozesim.plants` exposing a `Plant` subclass, a `PlantParams` subclass (containing a `Datasheet` where the technology has product data; the digester and the heat store are described by their settings), and its own `TimeSeries` struct (or none), and be registered in `REGISTRY`.
## Acceptance
`kiozesim/tests/test_core.py` passes; `scripts/spec_check.py` is green.

## Open questions
- [x] Heat output (CHP, boiler): extend `PlantOutput` with `heat_kw` in those plants. CHP: confirmed, `CHPOutput.heat_kw` (0015, 2026-10-12). `power_kw` always means electricity: 0 for boilers (combustion plants with electrical efficiency 0), the heat store and the digester (0006, 0019, 2026-10-15).

## Changelog
- 2026-10-05 created and implemented
- 2026-10-05 added CORE-006..008 (datasheets, golden harness, per-plant modules)
- 2026-10-05 weather removed from the core contract; plants own their inputs models
- 2026-10-05 inputs = one plant-specific `TimeSeries` struct (shared index) or none; no-input plants return a scalar; CORE-009 (weather helper) dropped
- 2026-10-05 golden harness: optional `expected_energy_kwh` (total energy) check, needed by PV-018; covered by CORE-007
- 2026-10-06 CORE-006: datasheets move to the central `kioze_sim/datasheets/<tech>/` (constitution 13); files move as part of 0007
- 2026-10-06 package renamed `kioze_sim` → `kiozesim`, golden cases under `kiozesim/tests/` (0009)
- 2026-10-12 heat output confirmed for the gas engine (`heat_kw` on `CHPOutput`, 0015); boiler still open
- 2026-10-12 `TimeSeries.from_frame` raises `MissingInputError` for absent columns (SRC-003); sources
  (`kiozesim.sources.Source`) sit next to plants as boxes that make time series (0016)
- 2026-10-15 plant chains (0019): `Plant` gains a one-step form (`initial_state`, `want`, `step`,
  `needs`, `follows_requests`) and `PlantOutput.to_frame`; sources leave the library for the tool;
  CORE-008: a datasheet only where the technology has product data; `power_kw` is electricity (0 for
  boilers, heat store, digester)
