---
id: 0019
title: Plant chains
prefix: CHAIN
status: implemented
---

# 0019 Plant chains

## Problem
Real installations are machines in a row: a digester makes gas, an engine or boiler burns it, a tank
stores the heat, buildings use it. Today each plant runs on its own: the apps feed plants from
sources (weather, a constant, spec 0016) but never one plant from another. So the gas engine's heat
cannot reach a tank, and a boiler cannot turn down when the tank behind it is full.

This spec lets plants be chained, front to back, and run **one time step at a time**, so a machine
can react to what the machine behind it needs. It also adds the reverse question for planning:
"the end of the chain needs 100 kW on average; how much feed does the front need?"

```
[digester] ─fuel_kw─▶ [engine] ─fuel_kw (spare)─▶ [boiler] ─heat_kw─▶ [tank] ─▶ heat delivered
                         ▲                            ▲                  │
                         └──── requests flow back ────┴── "send me 420" ─┘
```

## Scope
In:
- A one-step form of every plant, with its memory (state) passed in and handed back.
- Requests: per step, each plant says how much input it wants, given how much output is wanted
  from it (backward pass); then supplies flow forward.
- A chain runner in the library, used by both apps; the result keeps every plant's outputs.
- A naming scheme for columns, so an input is filled from the upstream output of the same name.
- `PlantOutput.to_frame()`.
- The digester becomes a plant.
- One combustion plant for gas engines and boilers (a boiler is an engine without electricity);
  the tank becomes its own plant (0006).
- The engine follows requests ("heat-led").
- `Source` and `ConstantSource` move from the library into the tool.
- Sizing: from a wanted average output at the end of a chain back to the feed at the front, in the
  library and in both apps.

Out (each may get its own spec later):
- Merges and splits as wiring: two plants feeding one (engine and boiler into one tank), one plant
  feeding two side by side. v1 chains are straight lines; gas left over by one plant can still go
  on to the next (naming scheme).
- Loops (a plant feeding something in front of it) and solving by trial and repeat.
- Digester delay: feed today gives gas over weeks (0005, "Steady feeding"). Hourly requests stop at
  the digester; only sizing (on averages) reaches the feed.
- Renaming columns on a wire.
- Optimisation (the cheapest way to run or size things): oemof.solph territory.
- Curtailing weather plants (asking PV or wind for less).

## Domain notes

### Co-simulation
Running several machine models side by side, one time step at a time, passing values between them
after each step, is called **co-simulation**. Each model keeps its own memory (a tank's content);
a runner moves all of them forward together. Until now every plant computed its whole period in
one call, which is fast but means no plant can react to a plant behind it: when the boiler computes
hour 5, the tank has not run yet.

### Two passes per step
In each step:

```
1. requests, back to front:  tank   → boiler: "send me up to 300 demand + 200 of room = 500"
                             boiler → engine: "send me up to 500 / 0.92 = 543 kW of gas"
2. supplies, front to back:  engine burns what heat is wanted of it, passes the spare gas on
                             boiler burns up to 543 → makes up to 500 → tank → demand
```

A plant that **follows requests** (engine, boiler) makes no more than is asked. A plant that does
not (the digester within the hour, PV, wind) ignores requests and passes on what it makes; what the
next plant cannot take is reported there (a full tank dumps heat, an engine's last spare gas is
flared). Requests use only what is known at the start of the step (a tank's content from the end
of the last step, this step's demand), so one pass back and one pass forward settle the step: no
repeating, no guessing.

This works for straight chains (and later for trees). A loop would need guessing and repeating until
values settle; v1 forbids loops.

### Memory as a value
A plant does not keep memory in itself between calls. The runner holds each plant's **state** (for
a tank: the heat it holds) and hands it in with each step; the plant hands back the new state. So a
plant stays a pure function (constitution 4) and the same plant can run twice in parallel.

### Fast where possible
Plants without memory that nothing asks anything of (PV, wind, an engine at the end of a chain)
need no stepping: the runner computes their whole period at once with `simulate`, as today
(constitution 10), and hands out one step at a time. Stepping a plant must give the same numbers as
`simulate`.

### Naming scheme
Columns that flow from plant to plant are named by **what kind of energy they carry**:

| Name | Carries |
|---|---|
| `fuel_kw` | burnable gas, lower heating value |
| `heat_kw` | useful heat (hot water) |
| `power_kw` | electricity |

Rules:
1. An input is filled from the upstream plant's output of the same name.
2. A plant's output of the same kind as one of its inputs is **what is left of that input**, passed
   on. The engine takes `fuel_kw` and outputs the gas it did not burn as `fuel_kw`, so a boiler
   behind it burns the rest. The engine's `flared_kw` disappears: gas left at the end of a chain is
   reported as flared by the runner.
3. Everything else a plant reports (losses, demand not met, tank content) has a name that is not a
   flow kind (`loss_kw`, `unmet_kw`, `stored_kwh`, ...) and is never passed on.
4. Inputs that come from sources, not plants, have their own names (`heat_demand_kw`, weather
   columns).

The result table keeps every plant's outputs under its own name, so two plants both giving
`heat_kw` never clash. The chart and the electricity total use `power_kw` only.

In a straight chain each plant passes on only flows the next plant takes: in
digester → engine → boiler → tank, the engine's own `heat_kw` has no taker (the boiler takes
`fuel_kw`) and is reported but not used. Using both engine and boiler heat in one tank is a merge
(out of v1).

### One combustion plant
A gas engine and a boiler do the same thing to fuel: burn it, cap it at a size, split it by fixed
efficiencies. The engine gives electricity and heat, the boiler heat only (electrical efficiency 0).
So both are one **combustion plant** (the EU's word for any installation that burns fuel to make
energy), and "TEDOM Flexi 530" and "ICI REX 62" are two of its datasheets. Following requests:

```
fuel_max_kw = the most fuel it can burn (from the datasheet's size)
burned_kw   = min(availability × min(fuel_kw, fuel_max_kw), fuel for the heat wanted, fuel for the power wanted)
power_kw    = burned_kw × electrical_efficiency
heat_kw     = burned_kw × thermal_efficiency
fuel_kw out = fuel_kw − burned_kw
```

with "fuel for the heat wanted" = wanted `heat_kw` ÷ `thermal_efficiency` (no limit when nothing is
wanted or the efficiency is 0), and likewise for power. Availability caps what the machine can burn
on average; a request below that cap is met in full. Asked for heat, the plant asks the plant in
front for the fuel that heat needs (÷ availability), plus any spare fuel the plant behind it asked
for; asked for nothing, it asks for no limit.

Each datasheet gives its size the way its document does: engines by electrical output
(`rated_electrical_kw`, TEDOM), boilers by heat output (`rated_thermal_kw`, ICI REX); exactly one
of the two. `fuel_max_kw` is that size divided by the matching efficiency. All combustion
datasheets live in one folder, `kiozesim/datasheets/combustion/`.

**Availability** (the share of time the machine is not down for maintenance) is a plant setting,
default 1 (never down). Typical values to set: gas engines 0.90–0.95, boilers about 0.98. The gas
engine's old default of 0.92 (0015) goes, since one default must suit both. Running an engine only as hard as its heat
is needed is called **heat-led** operation; it is how many farm and district-heating engines run.

### The tank as its own plant
The tank of 0006 becomes a plant behind any heat maker: input `heat_kw` and `heat_demand_kw`, its
request upstream is `heat_demand_kw + room`, outputs heat delivered, unmet demand, dumped heat,
losses and content. It keeps 0006's oemof.thermal losses.

### Sizing: running the chain backwards
For planning, each machine can be turned around, because each is a fixed ratio:

```
100 kW heat ← boiler, efficiency 0.92 ← 108.7 kW gas ← digester ← feed
```

The digester's gas is proportional to its feed, so the feed needed is the current feed scaled by
(gas wanted ÷ gas made), every substrate by the same factor. Example: the substrate of 0005's worked
example (40 t/day → 1728.3 kW) needs 2.516 t/day to give 108.7 kW. Sizing works on **averages**
only (the digester's weeks-long delay makes hourly answers meaningless) and stops at machines that
cannot be asked (PV, wind). If a machine's limit is hit, sizing reports how much it can give and the
shortfall. A tank adds nothing on average except its losses.

### Digester as a plant
The digester (0005) is a physical installation, so it becomes a plant like the others: no input
(its feed is a setting), output `fuel_kw` and `methane_nm3_per_h`, and `power_kw` 0 (it makes no
electricity). With no time-series input it returns single values (CORE-004), which the runner
spreads over the time axis.

### Where things live
| Thing | Package |
|---|---|
| plant contract (step, state, requests, sizing), chain runner, sizing walk | library `kiozesim` |
| plants: PV, HAWT, VAWT, combustion, tank, digester | library |
| sources (weather, constant), wiring sources into plants, config, chart | tool `kiozesim-tool` |

The library now runs plants together (constitution 2 changes). It still never fetches or reads
anything: a chain gets its source tables from the caller.

## Interface

`Plant` gains (defaults given for plants without memory):

| Member | Meaning |
|---|---|
| `initial_state() -> State` | the plant's memory at the start of a run (default: none) |
| `want(state, t, inputs, wanted, dt_h) -> dict[str, float]` | backward pass: input wanted per flow name for the step starting at `t`, given this step's inputs from sources and the outputs `wanted` from it; a name left out = no limit; default: no limit |
| `step(state, t, inputs, wanted, dt_h) -> (State, dict[str, float])` | forward pass: one step of length `dt_h` hours starting at `t`; returns the new state and one value per output field |
| `needs(wanted) -> Sizing` | sizing: average inputs needed for an average output (`Sizing.inputs`), what the plant can give (`Sizing.given`) and, for a digester, `Sizing.feed_t_per_day`; raises `CannotBeAsked` for plants driven by weather |
| `follows_requests: ClassVar[bool]` | whether `step` limits its output to `wanted` |

`State` is an immutable value (a frozen pydantic model or a number). `inputs` and `wanted` hold
one value per name for this step; `wanted` holds only the names the plant behind asked for.

`PlantOutput.to_frame(index=None) -> DataFrame`: its fields as columns; scalars spread over `index`.

`kiozesim.chain`:

| Member | Meaning |
|---|---|
| `Chain(plants: Sequence[Plant])` | a straight chain, front to back; rejects duplicate names |
| `Chain.run(index, inputs: Mapping[str, DataFrame], states=None) -> ChainResult` | `inputs`: per plant name, its source columns on `index`; `states`: per plant name, the state to start from (default `initial_state`), so a caller can run a long period in pieces |
| `ChainResult.outputs: dict[str, DataFrame]` | every plant's outputs, per plant name |
| `ChainResult.flared_kw: Series` | `fuel_kw` left at the end of the chain |
| `ChainResult.states: dict[str, State]` | every plant's state after the last step |
| `Chain.size(wanted: Mapping[str, float]) -> SizingResult` | wanted average output of the last plant → per plant its needed inputs, limits hit, shortfall, feed per substrate |

## Requirements

Library: contract
- **CHAIN-001** `Plant` MUST offer `initial_state`, `want`, `step`, `needs` and `follows_requests` as in Interface, with defaults for plants without memory; a plant MUST NOT keep state in itself between calls.
- **CHAIN-002** For every plant in `REGISTRY`, stepping from `initial_state` through a period with `wanted` all `None` MUST give the same outputs as `simulate` over that period, within 1e-9 relative.
- **CHAIN-003** A plant with `follows_requests` MUST NOT make more of an output than `wanted` in that step (what is left of an input, e.g. spare `fuel_kw`, is passed on in full: it cannot be unmade); a plant without it MUST ignore `wanted`.
- **CHAIN-004** `PlantOutput.to_frame()` MUST return one column per field, named as the field, on the output's index, and spread scalar fields over a given index.
- **CHAIN-005** Plant inputs and outputs that flow between plants MUST be named `fuel_kw`, `heat_kw` or `power_kw` by the naming scheme in Domain notes; an output of the same kind as an input MUST be what is left of that input; no other output MAY use those names.

Library: chain runner
- **CHAIN-010** `Chain` MUST take plants front to back and reject an empty chain and duplicate names; each plant's flow inputs MUST come from the plant before it, the first plant's from `inputs`, and a missing one MUST raise `MissingInputError` naming the plant and column.
- **CHAIN-011** In each step `Chain.run` MUST run a backward pass (`want`, back to front) and then a forward pass (`step`, front to back), passing each plant its state from the step before, starting from `states` if given, else `initial_state`, and MUST return every plant's last state.
- **CHAIN-012** A plant without memory with no plant with memory behind it MUST be run once with `simulate`, not stepped, and give the same result.
- **CHAIN-013** `ChainResult` MUST hold every plant's outputs under its name on `index`, and `flared_kw` = the `fuel_kw` the last plant passes on (0 if it passes none).
- **CHAIN-014** The library MUST NOT read files, fetch data or import the tool; sources stay in the tool.

Library: plants
- **CHAIN-020** The digester MUST be a plant `DigesterPlant`, registered as `digester`, with no input, outputs `fuel_kw` and `methane_nm3_per_h` with the values of 0005, and `power_kw` 0.
- **CHAIN-021** The gas engine and the boiler MUST be one plant, `CombustionPlant`, registered as `combustion`, following the equations under "One combustion plant", with `follows_requests` true and `availability` defaulting to 1; its datasheet MUST have exactly one of `rated_electrical_kw` and `rated_thermal_kw`; TEDOM (0015) and ICI REX (0006) units MUST be its bundled datasheets, all in `kiozesim/datasheets/combustion/`.
- **CHAIN-022** The tank MUST be its own plant, `HeatStorePlant`, registered as `heat_store`, as under "The tank as its own plant", with memory and `follows_requests` true.
- **CHAIN-023** `needs` MUST invert each plant's own equations: for the combustion plant the fuel for a wanted `power_kw` or `heat_kw`; for the heat store the heat in for a wanted delivery plus its average losses; for the digester the feed per substrate, every substrate scaled by the same factor.
- **CHAIN-024** `needs` on a plant driven by weather (PV, HAWT, VAWT) MUST raise `CannotBeAsked` naming the plant.
- **CHAIN-025** `Source` and `ConstantSource` MUST move from `kiozesim.sources` to the tool; the library MUST NOT define sources.

Sizing
- **CHAIN-030** `Chain.size` MUST walk the chain back to front with `needs`, report each plant's needed inputs and, at a digester, the feed per substrate; it MUST stop at a plant that cannot be asked and say so.
- **CHAIN-031** When a wanted output exceeds a plant's limit, sizing MUST report what the plant can give and the shortfall.

Apps (both)
- **CHAIN-040** A plant MUST be allowed in another plant's `from`; plants wired to plants MUST form straight chains, and a loop, a merge or a split MUST be rejected before running, naming the plant; each chain MUST be run with `Chain.run`.
- **CHAIN-041** The power chart, the stream and the electricity total MUST use every plant's `power_kw` only (other outputs: their own charts, 0020).
- **CHAIN-042** The tool MUST offer `kiozesim-tool size --config <file> --plant <last plant> --want <name>=<kW>`, printing the sizing result of that plant's chain.
- **CHAIN-043** The web page MUST offer a sizing section: pick a plant at the end of a chain and a wanted average output, and show the sizing result.

Validation
- **CHAIN-050** Sizing 100 kW of heat through a combustion plant of thermal efficiency 0.92 and electrical efficiency 0 back to a digester fed 0005's worked-example substrate MUST give 2.516 t/day within ±0.1 %.
- **CHAIN-051** A chain constant fuel → boiler → heat store with a demand that changes over the day MUST close the store's energy balance (0006) within 1e-6 relative, and the boiler MUST never make more heat than the store asked for in any step.
- **CHAIN-052** A chain digester → engine → boiler MUST burn in the boiler exactly the gas the engine leaves, and `flared_kw` MUST be what the boiler leaves.

## Acceptance
- Every CHAIN-xxx requirement has at least one test marked with its ID; `uv run pytest`,
  `uv run python scripts/spec_check.py`, `ruff` and `mypy` are green.
- Spec edits on approval: constitution 2 (plants step; the library runs chains; sources are the
  tool's) and 10 (stepping where requests or memory need it); 0001 (`Plant` contract);
  0005 (digester is a plant); 0006 (heat store plant + ICI REX datasheets on the combustion plant);
  0015 (becomes the combustion plant, heat-led, spare gas as `fuel_kw`); 0016 (sources in the tool,
  plants in `from`).

## Open questions
- [x] **Combustion datasheet size**: exactly one of `rated_electrical_kw` or `rated_thermal_kw`,
      as each document gives it (left to Claude, 2026-10-15).
- [x] **Shelf**: one folder, `kiozesim/datasheets/combustion/` (decided 2026-10-15).
- [x] **Availability default**: 1 for all combustion plants; typical values documented (left to
      Claude, 2026-10-15).

## Changelog
- 2026-10-15 draft: plants chained front to back, stepped with a backward pass of requests and a
  forward pass of supplies; state passed in and out; digester becomes a plant; sizing on averages
- 2026-10-15 decided: chain runner in the library; sources move to the tool; gas engine and boiler
  one combustion plant, tank its own plant; engine follows requests (heat-led); flow naming scheme
  (spare fuel passed on as `fuel_kw`); merges stay out of v1; sizing in the tool and the web page
- 2026-10-15 combustion datasheets sized by one of electrical or heat output, one `combustion/`
  folder, availability default 1; no open questions left
- 2026-10-15 approved
- 2026-10-15 while planning: `want`/`step` take the step start `t` and length `dt_h` (a tank's room
  and PV's sun need them); `step` returns plain values; `needs` returns a `Sizing` (inputs, what
  can be given, feed); `Chain.run` takes and returns states so the tool can run day by day
  (CHAIN-011); availability caps the burn instead of scaling a request; CHAIN-003 spare fuel passes
  on in full; CHAIN-012 "plant with memory behind it"
- 2026-10-15 implemented (`kiozesim/chain.py`, step contract in `plants/base.py`, `combustion`,
  `digester` and `heat_store` plants, sources in `kiozesim_tool.sources`, `kiozesim-tool size`,
  sizing section on the web page)
- 2026-10-15 CHAIN-041: "the power chart"; the other outputs get their own charts (0020)
