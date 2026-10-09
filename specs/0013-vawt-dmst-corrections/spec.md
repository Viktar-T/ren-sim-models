---
id: 0013
title: VAWT DMST corrections
prefix: VCOR
status: draft
---

# 0013 VAWT DMST corrections

## Problem
Plain DMST (spec 0004) is optimistic for small Darrieus rotors with wide blades: against the UNH
RM2 rotor it predicts about 20 % more peak Cp than measured, at a tip speed ratio about 1 higher.
Two effects it leaves out matter most for such rotors:
- **dynamic stall**: a blade whose angle to the air swings quickly lifts more, and stalls later,
  than the steady airfoil tables say;
- **flow curvature**: the blade moves on a circle, so the air it meets is curved, which acts like
  extra camber on a symmetric blade.
Add both as switchable corrections and bring VAWT-018 back towards ±15 %.

## Scope
In: ... (to be written)
Out: ...

## Domain notes
Candidate methods: Gormont dynamic stall with Berg's modification (used by Sandia's DMST codes),
Migliore's virtual-camber flow curvature correction. To be checked.

## Requirements
- **VCOR-001** TBD

## Acceptance
VAWT-018 within ±15 % / ±0.5 with the corrections on; VAWT-022 still within ±15 % / ±0.5.

## Open questions
- [ ] Which dynamic stall and flow curvature methods?
- [ ] On by default?

## Changelog
- 2026-10-09 stub created (spec 0004 decision G)
