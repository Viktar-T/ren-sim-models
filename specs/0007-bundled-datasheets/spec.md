---
id: 0007
title: Bundled datasheets
prefix: DS
status: draft
---

# 0007 Bundled datasheets

## Problem
Datasheet YAML files ship inside each plant package (`plants/<tech>/datasheets/`) and are included in the
wheel, but a library user has no public way to reach them. They would have to locate the install
directory and build a path by hand.

## Scope
In: listing and loading the datasheets shipped with a plant package, by name.
Out: user-supplied datasheet catalogues; vendor/product search; unit conversion; the OEDB turbine
library used by windpowerlib (separate loader, see 0003).

## Domain notes
A datasheet is manufacturer data for one product (module, turbine, CHP engine, boiler), stored as YAML
and validated by that plant's `Datasheet` subclass (see CORE-006). Today only a path-based loader
exists: `Datasheet.from_yaml(path)`. Bundled files are currently placeholders marked
`source: placeholder`.

## Requirements
- **DS-001** Every `Datasheet` subclass MUST be able to list the names of the datasheets shipped in its plant package.
- **DS-002** Every `Datasheet` subclass MUST be able to load a shipped datasheet by name, returning a validated instance.
- **DS-003** Loading an unknown name MUST raise `FileNotFoundError` whose message lists the available names.
- **DS-004** Lookup MUST work from an installed wheel, not only from a source checkout.
- **DS-005** The path-based `from_yaml` MUST remain available and unchanged.

## Acceptance
For each plant, a test lists the bundled names, loads each one by name, and checks the result equals
loading the same file via `from_yaml`. A test builds the wheel and loads a datasheet from it.

## Open questions
- [ ] API shape: classmethods on `Datasheet` (`PVDatasheet.bundled("name")`, `.available()`), or a
      separate module-level function?
- [ ] Naming: bare file stem (`"example"`), or product ids such as `"vendor/model"`?
- [ ] Should placeholder datasheets be shipped at all, or only real, sourced ones?
- [ ] Should `source` be required for bundled files, so unsourced data cannot ship?

## Changelog
- 2026-10-05 draft created
