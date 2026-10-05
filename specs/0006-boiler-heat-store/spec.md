---
id: 0006
title: Boiler with heat store
prefix: BOIL
status: draft
---

# 0006 Boiler with heat store

## Problem
Simulate a boiler and a buffer tank.

## Scope
In: ...
Out: ...

## Domain notes
Simple: heat = fuel x efficiency. Tank losses via oemof.thermal parameters. FMU (FMI 2.0, co-simulation, FMPy) only if dynamics are required, wrapped as an adapter behind the same interface.

## Requirements
- **BOIL-001** TBD

## Acceptance
Energy balance closes: fuel in = heat out + losses.

## Open questions
- [ ] Is the FMU actually needed?
- [ ] Time-step mismatch strategy (sub-stepping)?

## Changelog
- 2026-10-05 stub created
