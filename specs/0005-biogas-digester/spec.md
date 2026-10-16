---
id: 0005
title: Biogas digester
prefix: BIO
status: implemented
---

# 0005 Biogas digester

## Problem
A biogas plant is two machines joined by a pipe: a **digester** that turns farm and food waste into
gas, and a **gas engine** that burns the gas to make electricity and heat. This spec covers the
digester: given its steady daily feed, how much burnable gas does it make? Its output is a fuel
time series that plugs straight into the gas engine (spec 0015):

```
feed (t/day) ──▶ [Digester, 0005] ──fuel_kw──▶ [Gas engine, 0015] ──▶ power_kw, heat_kw
```

## Scope
In:
- One digester (or several treated as one), fed one or more substrates at a steady daily rate,
  set in its settings.
- Methane yield of each substrate from its chemical formula (Buswell–Boyle) and how much of it the
  bacteria actually break down.
- Output as methane volume and as fuel energy in kW, ready for the gas engine.

Out (each may get its own spec later):
- **Feed that changes over time** (a feed schedule) and **gas timing** (kinetics): the days-long
  delay between feeding and gas. v1 assumes steady feeding, so gas output is constant (see Domain
  notes, "Steady feeding").
- **Gas store** (gasometer) between digester and engine.
- The full bacteria model (ADM1), pH, inhibition, digester temperature and its heating.
- Tables of typical substrates and measured (lab) yields; users give the formula.
- CO₂, H₂S and NH₃ amounts; gas upgrading to biomethane.
- Web UI and tool support (their own specs).

## Domain notes

### How a digester works
A **digester** is a heated, airtight tank, like a stomach. It is fed organic material (manure,
maize silage, food waste), and bacteria digest it, giving off **biogas**: mostly **methane** (CH₄,
the part that burns, typically 50–60 %) and **carbon dioxide** (CO₂, which does not burn).

The digester is a **plant** (since spec 0019; it was a source before): a physical installation at
the front of a chain. It makes gas, not electricity, so its `power_kw` is 0. Its `fuel_kw` flows to
the combustion plant behind it (gas engine or boiler, 0015).

### Substrates
A **substrate** is one kind of feed. Its amount is given in **fresh mass**, tonnes per day, as
weighed when loaded. Only part of it can become gas:
- **Dry matter** (DM, also TS for "total solids"): what is left after drying, as a fraction of
  fresh mass. Cattle slurry ≈ 0.08, maize silage ≈ 0.33.
- **Organic dry matter** (oDM, also VS for "volatile solids"): the organic part of the dry matter,
  as a fraction of dry matter (the rest is ash and minerals). Typically 0.80–0.95.
- **Biodegradability**: the fraction of organic dry matter the bacteria actually break down in
  practice. Some of it (lignin, the woody part of plants) hardly breaks down at all, and the
  bacteria use a little for their own growth. Typically 0.5–0.9.

### Buswell–Boyle: methane from chemistry
If the organic matter has the average chemical formula CₐHᵦO꜀N_dSₑ (counts of carbon, hydrogen,
oxygen, nitrogen and sulphur atoms; they need not be whole numbers), complete digestion gives

```
CH4 per formula unit = a/2 + b/8 − c/4 − 3d/8 − e/4   (mol)
```

One mole of gas at normal conditions (0 °C, 1.01325 bar) fills 22.414 litres; a cubic metre at
these conditions is written **Nm³** ("normal cubic metre"). The maximum methane yield per kg of
organic dry matter is

```
yield_nm3_per_kg = CH4 per formula unit × 22.414 / molar mass (g/mol)
molar mass = 12.011 a + 1.008 b + 15.999 c + 14.007 d + 32.06 e
```

Textbook examples (Angelidaki & Sanders 2004, table 1; also VDI 4630):

| Substance | Formula | Nm³ CH₄ per kg |
|---|---|---|
| carbohydrate (cellulose, starch) | C6H10O5 | 0.415 |
| protein | C5H7NO2 | 0.496 |
| fat (triolein) | C57H104O6 | 1.014 |

### From feed to fuel
For each substrate:

```
methane_nm3_per_day = fresh_t_per_day × 1000 × dry_matter_frac × organic_frac
                      × biodegradability × yield_nm3_per_kg
```

Summed over substrates, then converted to energy with methane's lower heating value,
**9.97 kWh per Nm³** (DIN EN ISO 6976), spread evenly over the day:

```
methane_nm3_per_h = Σ methane_nm3_per_day / 24
fuel_kw           = methane_nm3_per_h × 9.97
```

`fuel_kw` is a fuel energy flow: how much energy flows into the engine as gas, per hour on average.

**Worked example.** 40 t/day of a substrate with dry matter 0.33, organic fraction 0.95, formula
C6H10O5 and biodegradability 0.8: 40 000 × 0.33 × 0.95 × 0.8 = 10 032 kg organic matter digested
per day × 0.41471 Nm³/kg = 4160.4 Nm³ CH₄/day = 173.35 Nm³/h → **1728.3 kW** of fuel. A 500 kW
engine at 40 % electrical efficiency burns 1250 kW at full load, so this digester would keep it
full with gas to spare.

### Steady feeding (v1 simplification)
Real plants are fed the same mix every day, and the digester holds weeks of feed, so its gas output
is nearly constant: small swings after each feeding are smoothed out by the gas store on top of the
tank. v1 takes that as exact: the feed rate is a setting, and the output is the same on every time
step asked for. A feed that changes over time needs a delay model too (bacteria take days to weeks
to react), so both are left to a later spec.

### References
- A. M. Buswell, H. F. Mueller, "Mechanism of methane fermentation", Ind. Eng. Chem. 44(3), 1952.
- I. Angelidaki, W. Sanders, "Assessment of the anaerobic biodegradability of macropollutants",
  Rev. Environ. Sci. Biotechnol. 3, 2004. The table's values as reproduced in Kim et al.,
  Appl. Biol. Chem., https://applbiolchem.springeropen.com/articles/10.1186/s13765-020-00546-6/tables/4
  (checked 2026-10-12; the original paper itself not read).
- VDI 4630 (2016), *Fermentation of organic materials*.
- DIN EN ISO 6976, calorific value of natural gas components.

## Interface

`Substrate`:

| Field | Unit | Default | Allowed | Meaning |
|---|---|---|---|---|
| `name` | – | required | non-empty | label, e.g. `maize silage` |
| `fresh_t_per_day` | t/day | required | ≥ 0 | fresh mass fed per day |
| `dry_matter_frac` | – | required | 0 < x ≤ 1 | dry matter / fresh mass |
| `organic_frac` | – | required | 0 < x ≤ 1 | organic dry matter / dry matter |
| `formula` | – | required | see BIO-003 | average formula of the organic matter, e.g. `C6H10O5` |
| `biodegradability` | – | required | 0 < x ≤ 1 | fraction of organic matter actually digested |

`DigesterParams`:

| Field | Unit | Default | Allowed | Meaning |
|---|---|---|---|---|
| `name` | – | required | non-empty | digester name |
| `substrates` | – | required | ≥ 1, unique names | what it can be fed |

`DigesterPlant` is a plant without input (CORE-004): `simulate()` takes nothing and returns a
`DigesterOutput` of single values (the same on every step; a chain spreads them over its time axis):

| Field | Unit | Meaning |
|---|---|---|
| `power_kw` | kW | always 0: it makes no electricity |
| `fuel_kw` | kW | methane energy made, average over the period; the combustion plant's input |
| `methane_nm3_per_h` | Nm³/h | methane volume made, average over the period |

## Requirements

Parameters and inputs
- **BIO-001** `Substrate` and `DigesterParams` MUST have exactly the fields, units, defaults and allowed ranges of their tables and MUST reject any value outside them at construction; `substrates` MUST be non-empty with unique names.
- **BIO-003** `formula` MUST accept the elements C, H, O, N and S, each at most once, each followed by an optional positive count (whole or decimal, missing means 1), with C and H required; anything else, or a formula giving no methane by Buswell–Boyle, MUST be rejected with an error naming the substrate.
- **BIO-004** `DigesterPlant.simulate()` MUST take no input and MUST reject being given one (CORE-004).

Model
- **BIO-002** `DigesterPlant` MUST be a plant without input (0019 CHAIN-020), registered in `REGISTRY` as `digester`, returning a `DigesterOutput` with exactly the fields `power_kw` (0), `fuel_kw` and `methane_nm3_per_h`.
- **BIO-005** The methane yield of a formula MUST be computed by the Buswell–Boyle equation, molar masses and 22.414 l/mol given in Domain notes.
- **BIO-006** `methane_nm3_per_h` and `fuel_kw` MUST follow the equations under "From feed to fuel" and MUST be the same on every step.
- **BIO-007** In a chain, the digester's `fuel_kw` MUST be usable unchanged as the combustion plant's input (`CombustionInputs`, 0015; `Chain`, 0019).
- **BIO-008** A digester whose substrates all have `fresh_t_per_day` 0 MUST give 0 `fuel_kw` and 0 `methane_nm3_per_h`.
- **BIO-009** The digester MUST need no package beyond the library's core dependencies.

Validation
- **BIO-010** The Buswell–Boyle yield MUST be within ±1 % of the textbook values in Domain notes for C6H10O5, C5H7NO2 and C57H104O6.
- **BIO-011** The worked example in Domain notes MUST give 1728.3 kW `fuel_kw` within ±0.1 %.

## Acceptance
- Every BIO-xxx requirement has at least one test marked with its ID; `uv run pytest`,
  `uv run python scripts/spec_check.py`, `ruff` and `mypy` are green.
- A test runs the worked example's digester for one year of daily steps into a TEDOM Flexi 530
  gas engine (0015) and gets its annual electricity.

## Open questions
- [x] **Heat output**: the gas engine reports `heat_kw` (0015) (decided 2026-10-12).
- [x] **Gas store / flexible running in v1**: no; later spec, to sit between digester and engine
      (decided 2026-10-12).
- [x] **Gas timing (first-order kinetics)**: no; steady feeding, documented under "Steady
      feeding" (decided 2026-10-12).
- [x] **Feed as a setting or an input**: a setting (`fresh_t_per_day` per substrate); the digester
      takes no input table (decided 2026-10-12).
- [x] **Split digester and engine**: yes; the digester is a fuel source whose `fuel_kw` feeds a
      separate gas engine plant, spec 0015 (decided 2026-10-12).
- [x] **Describing substrates**: by formula only; no substrate tables or measured yields in v1
      (decided 2026-10-12).

## Changelog
- 2026-10-05 stub created
- 2026-10-12 split: this spec is now the digester only (fuel source, constitution 2); the CHP engine
  moves to 0015. Requirements BIO-001..011: Buswell–Boyle yield, feed time series per substrate,
  `fuel_kw` output, no delay. oemof.solph dropped (an optimiser, not needed for an energy balance)
- 2026-10-12 textbook yields checked against a secondary source; approved
- 2026-10-12 implemented (`kiozesim/sources/digester/`)
- 2026-10-12 feed moves into the settings (`Substrate.fresh_t_per_day`); `DigesterInputs` removed,
  `simulate(index)` takes only the time axis (BIO-002, BIO-004, BIO-006, BIO-008); output constant
- 2026-10-12 digester is a `Source` (0016): output is a DataFrame, `DigesterOutput` removed (BIO-002,
  BIO-004, BIO-007)
- 2026-10-15 plant chains (0019): the digester is a plant again, `DigesterPlant` (`digester`),
  output `DigesterOutput` of single values with `power_kw` 0; moves to `kiozesim/plants/digester/`
  (BIO-002, BIO-004, BIO-007)
