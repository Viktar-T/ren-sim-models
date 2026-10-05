---
id: 0005
title: Biogas plant
prefix: BIO
status: draft
---

# 0005 Biogas plant

## Problem
Simulate biogas production and CHP electricity (and heat).

## Scope
In: ...
Out: ...

## Domain notes
Buswell-Boyle gives theoretical CH4/CO2 yield from substrate C,H,O,N,S; multiply by a biodegradability factor. CHP: electrical efficiency, minimum load. oemof.solph is optional; a plain Python balance may suffice.

## Requirements
- **BIO-001** TBD

## Acceptance
500 kW CHP at 90% availability gives about 3.9 GWh/year; stoichiometry matches textbook values.

## Open questions
- [ ] Heat output interface (see 0001 open question)
- [ ] Gasometer state / flexible dispatch in v1?
- [ ] First-order kinetics for gas timing?

## Changelog
- 2026-10-05 stub created
