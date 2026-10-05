---
id: 0004
title: VAWT plant
prefix: VAWT
status: draft
---

# 0004 VAWT plant

## Problem
Simulate Darrieus/Savonius turbines with a custom model.

## Scope
In: ...
Out: ...

## Domain notes
Darrieus: DMST (double multiple streamtube) BEM. Savonius: empirical Cp(TSR). Precompute Cp(TSR) once per rotor, then look up at runtime. Cp must not exceed the Betz limit 0.593.

## Requirements
- **VAWT-001** TBD

## Acceptance
Cp(TSR) curve matches a published reference within tolerance.

## Open questions
- [ ] Airfoil data source for Darrieus?
- [ ] Savonius Cp curve source?

## Changelog
- 2026-10-05 stub created
