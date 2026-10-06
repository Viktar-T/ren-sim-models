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
Out: any concrete technology; weather fetching; resampling helpers; dispatch/optimisation (oemof layer).

## Requirements
- **CORE-001** `Plant` MUST be abstract and generic over its own params, time-series struct and output model; `simulate(ts=None)` MUST take at most one argument, a plant-specific `TimeSeries` struct, and nothing technology-specific (weather, demand) is part of the shared signature. Subclasses implement `_simulate` only.
- **CORE-002** A `TimeSeries` struct MUST hold `pd.Series` fields that all share ONE index, which MUST be tz-aware UTC, strictly increasing, regularly spaced and period-start labelled; series with different steps or any NaN MUST be rejected (resampling is the caller's explicit job).
- **CORE-003** Plant parameter models MUST be immutable and reject unknown fields.
- **CORE-004** A plant that declares a `TimeSeries` MUST return a `PlantOutput` whose `power_kw` is a Series named `power_kw`, finite, >= 0, on the input's index; a plant that declares none MUST be called without one and MUST return a scalar steady-state `power_kw`. Wrong or missing structs MUST raise.
- **CORE-005** `Portfolio.simulate` MUST take a TimeSeries per plant name (omitted for no-input plants) and return one column per plant plus `total`; it MUST reject duplicate names, plants on different time axes, and portfolios with no time-series plant. Scalar plants are broadcast onto the common axis.
- **CORE-006** Producer data MUST live in YAML under the plant's `datasheets/` and be loaded through a pydantic `Datasheet` subclass that rejects unknown fields.
- **CORE-007** The golden harness MUST discover `tests/golden/<plant>/<case>/` cases and fail when output differs from the expected values beyond the case tolerance.
- **CORE-008** Each technology MUST be its own package under `kioze_sim.plants` exposing a `Plant` subclass, a `PlantParams` subclass containing a `Datasheet`, and its own `TimeSeries` struct (or none), and be registered in `REGISTRY`.
## Acceptance
`tests/test_core.py` passes; `scripts/spec_check.py` is green.

## Open questions
- [ ] Heat output (CHP, boiler): extend `PlantOutput` with `heat_kw` in those plants. Confirm in 0005/0006, and decide what `power_kw` means for the boiler (thermal?).

## Changelog
- 2026-10-05 created and implemented
- 2026-10-05 added CORE-006..008 (datasheets, golden harness, per-plant modules)
- 2026-10-05 weather removed from the core contract; plants own their inputs models
- 2026-10-05 inputs = one plant-specific `TimeSeries` struct (shared index) or none; no-input plants return a scalar; CORE-009 (weather helper) dropped
- 2026-10-05 golden harness: optional `expected_energy_kwh` (total energy) check, needed by PV-018; covered by CORE-007
