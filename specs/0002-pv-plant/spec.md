---
id: 0002
title: PV plant
prefix: PV
status: draft
---

# 0002 PV plant

## Problem
Simulate AC power of a PV system from weather.

## Scope
In: ...
Out: ...

## Domain notes
Engine: pvlib ModelChain (optional extra `pv`). Needs ghi, dni, dhi, temp_air, wind_speed.

## Requirements
- **PV-001** TBD

## Acceptance
Annual yield for a reference PVGIS location within a stated tolerance.

## Open questions
- [ ] PVWatts only, or single-diode too?
- [ ] Multiple arrays in v1?

## Changelog
- 2026-10-05 stub created
