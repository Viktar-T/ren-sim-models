---
id: 0006
title: Heat store and bundled boilers
prefix: BOIL
status: implemented
---

# 0006 Heat store and bundled boilers

## Problem
Store heat in a hot-water tank between whatever makes the heat (a boiler or a gas engine) and the
buildings that use it, so heat made at one time can be used later. And ship real boilers to make
that heat.

Since spec 0019 (plant chains) a boiler is not a model of its own: it is a combustion plant
(0015, 0019) whose electrical efficiency is 0. So this spec holds two things: the **heat store
plant**, which sits at the end of a chain, and the **boiler datasheets** for the combustion plant.

```
[digester] ─fuel_kw─▶ [combustion: ICI REX 62] ─heat_kw─▶ [heat store] ─▶ delivered_kw, unmet_kw, ...
                                    ▲                          │   ▲
                                    └──── "send me 420" ───────┘   heat_demand_kw (from a source)
```

## Scope
In:
- One hot-water tank as a plant (`HeatStorePlant`, 0019 CHAIN-022): heat in from the plant before
  it, heat demand from a source, heat delivered out; memory (its content) and requests upstream.
- Heat lost through the tank's walls, by oemof.thermal.
- Bundled datasheets of three real boilers, on the combustion plant's shelf.

Out (each may get its own spec later):
- Electricity: the store makes none (`power_kw` is always 0).
- Heat from two makers into one tank (engine and boiler): a merge, out of 0019 v1.
- Heat demand models (from outdoor temperature, daily patterns, files); v1 takes demand from any
  source, e.g. a constant.
- Temperatures inside the tank (layers mixing, pipes, valves): no FMU (see Domain notes).
- Condensing boilers (see "Bundled boilers").

## Domain notes

### What the plant is
A **heat store** (buffer tank) is a big insulated flask of hot water. Heat is put in when more is
made than needed and taken out later, when the demand is higher than the heat maker can follow or
its fuel runs short. A **boiler** is a big kettle: it burns fuel to heat water, heat only, no
electricity. In a chain the boiler sits in front of the tank and the tank tells it how much to make.

### The tank
The tank is modelled the way oemof.thermal models a **stratified** tank: hot water (`temp_hot_c`)
sits on top of cold water (`temp_cold_c`) because hot water is lighter. Charging moves the boundary
down, discharging moves it up. "Empty" means all cold, "full" means all hot. How much heat it
holds when full:

```
capacity_kwh = volume_m3 × density × heat_capacity × (temp_hot_c − temp_cold_c) / 3.6e6
```

with water at about 80 °C: density 971.803 kg/m³, heat capacity 4195.52 J/(kg·K) (the
oemof.thermal defaults). A 50 m³ tank at 80/40 °C holds about 2,265 kWh.

The tank is an upright cylinder of the given volume and height; its diameter follows from those.

### Heat lost through the walls
A flask loses heat through its walls, faster the hotter the water and the worse the insulation.
oemof.thermal splits this into three parts, all set by the insulation's **U-value** (watts lost per
square metre of wall per degree of difference to the room, `u_value_w_m2k`; smaller is better,
about 0.2–0.5 for an insulated buffer tank) and the room temperature `temp_room_c`:

```
loss_rate      β = 4 U Δt / (d ρ c)                                   (share of the content)
fixed_relative γ = 4 U (T_cold − T_room) Δt / (d ρ c (T_hot − T_cold))  (share of the capacity)
fixed_absolute δ = U π d²/4 (T_hot + T_cold − 2 T_room) Δt             (kWh, lid and floor)

loss_kwh = β × stored_kwh + γ × capacity_kwh + δ
```

`d` is the diameter in m, `ρ c` the water values above, `Δt` the step length (in seconds for β and
γ; δ converted to kWh). Equations from oemof.thermal's documentation, "Stratified thermal storage".

The plant does not compute these itself: it calls oemof.thermal's
`stratified_thermal_storage.calculate_capacities` and `calculate_losses` (constitution 6: through
the plant's adapter, imported only when needed, oemof values converted from MWh to kWh there).
oemof.thermal 0.0.9a1 is the first version that works with oemof.solph 0.6 (0.0.8 needs solph
≤ 0.5.5; 0.0.6 fails on import, asking for solph's old `Transformer`). It is a pre-release, so the
`system` extra pins it exactly. A store of 0 m³ has no losses to compute and needs no extra package.

An empty tank (all cold water) still loses a little heat. v1 does not let the tank go below empty:
in a step the loss is at most what the tank holds.

### Each time step
The step length `Δt` (hours) is read from the time axis. Following 0019's two passes:

```
backward pass (want):
  loss      = min(stored, β·stored + γ·capacity + δ)
  wanted_in = heat_demand_kw + (capacity − (stored − loss)) / Δt     ask upstream for demand + room

forward pass (step), with heat_kw = what the plant in front actually sent:
  stored   −= loss                                                    tank cools
  stored   += heat_kw · Δt                                            heat comes in
  delivered = min(heat_demand_kw · Δt, stored);  stored −= delivered  demand drawn
  unmet     = heat_demand_kw · Δt − delivered
  dumped    = max(0, stored − capacity);  stored = min(stored, capacity)

delivered_kw = delivered / Δt     unmet_kw = unmet / Δt     dumped_kw = dumped / Δt
loss_kw      = loss / Δt          stored_kwh = stored        power_kw = 0
```

Heat coming in goes to the demand even when the tank is full; only what is left beyond a full tank
is dumped. A plant in front that follows requests (the combustion plant) never sends more than
`wanted_in`, so nothing is dumped behind it. One that does not may send more, and the rest is
dumped (in a real plant: an emergency cooler).

Within one step the heat maker and the tank are treated as running evenly, which is what a period
average means (constitution 9). No sub-stepping is needed: an insulated tank loses about 0.05 % of
its heat per hour, so one update per step stays accurate even with daily steps.

### Energy balance
Over any run, heat is neither made nor lost unaccounted:

```
stored at start + Σ heat in = stored at end + Σ delivered + Σ losses + Σ dumped
```

### Why no FMU
An FMU (a packaged detailed physics model) would follow the water temperatures, pipes and valves
minute by minute. The outputs here are averages per step, which the energy balance gives
directly. Constitution 7: simplest model first.

### Bundled boilers
Three sizes of one boiler family, all from one manufacturer document, so the basis is the same. The
sizes match the heat of the three bundled gas engines (0015: TEDOM Cento 100 ≈ 142 kW, Cento 200
≈ 245 kW, Flexi 530 ≈ 584 kW of heat), so each engine has a boiler that can back it up. They are
combustion datasheets (0019) with `rated_thermal_kw` and `electrical_efficiency` 0:

| Manufacturer | Model | `rated_thermal_kw` | `thermal_efficiency` | `electrical_efficiency` | Fuel input in the document | Document |
|---|---|---|---|---|---|---|
| ICI Caldaie | REX 15 | 150 | 0.92 | 0 | 163 kW | [1] |
| ICI Caldaie | REX 30 | 300 | 0.92 | 0 | 325 kW | [1] |
| ICI Caldaie | REX 62 | 620 | 0.92 | 0 | 672 kW | [1] |

[1] ICI Caldaie, *REX – Reverse flame boiler* (brochure "Depliant REX_2024", EN),
https://www.icicaldaie.com/wp-content/uploads/2024/03/Depliant-REX_2024_EN_Web-4.pdf, page 1,
table "Technical data", columns "Heat output", "100% Productivity" (REX, not REX F) and "Thermal
capacity" (= fuel input) (read 2026-10-15). Page 2 lists biogas among its fuels ("Clean fuels:
Biogas – Biomethane – Biodiesel – Syngas"). Hot-water boiler, not condensing, for water at
60–100 °C; the burner is bought separately. Each efficiency checks against heat output ÷ fuel input
within 0.5 % (e.g. REX 62: 620 / 672 = 0.923). The document does not name the heating-value basis;
0.92 for a boiler that is not condensing fits the lower heating value, the Italian convention
("rendimento" on PCI) and the basis of `fuel_kw`. Files in `kiozesim/datasheets/combustion/`,
named per DS-009, e.g. `ici_caldaie_rex_15`.

Why this family: the only current document found that covers small to large sizes in one table and
names biogas as a fuel. Backups: Hoval Max-3 (catalogue Oil/gas 2026/27, full-load efficiency at
80/60 °C on both heating-value bases, but no biogas and nothing below 500 kW); Viessmann Vitoplex
(often seen at biogas plants, but discontinued).

Condensing boilers and biogas: their datasheets give efficiencies above 1 (up to about 1.09) on the
lower heating value basis, because they recover heat from the steam in the exhaust. No manufacturer
document found rates one for biogas: raw biogas carries hydrogen sulphide, which turns into
sulphuric acid when the exhaust is cooled far enough to condense, eating the boiler. EU rules
otherwise require condensing boilers up to 400 kW (Regulation (EU) 813/2013), but they exempt
boilers designed for fuels mostly made from biomass (Art. 1(2)). So efficiencies stay below 1
(CHP-001) and condensing boilers are left out.

## Interface

`HeatStoreParams`:

| Field | Unit | Default | Allowed | Meaning |
|---|---|---|---|---|
| `name` | – | required | – | plant name (from `PlantParams`) |
| `volume_m3` | m³ | required | ≥ 0 | tank size; 0 = no tank, heat passes straight to the demand |
| `height_m` | m | 2.0 | > 0 | tank height, sets its diameter |
| `u_value_w_m2k` | W/(m²·K) | 0.4 | > 0 | heat lost through the tank wall |
| `temp_hot_c` | °C | 80 | > `temp_cold_c` | water temperature when charged |
| `temp_cold_c` | °C | 40 | > `temp_room_c` | water temperature when discharged |
| `temp_room_c` | °C | 15 | – | air around the tank |
| `initial_fill` | – | 0.5 | 0 ≤ x ≤ 1 | share of the capacity charged at the start |

The heat store has no datasheet: tanks are described by their size and insulation.

`HeatStoreInputs` (`TimeSeries`):

| Field | Unit | Required | From | Allowed |
|---|---|---|---|---|
| `heat_kw` | kW | yes | the plant in front (flow, 0019 naming scheme) | ≥ 0, average over the period |
| `heat_demand_kw` | kW | yes | a source | ≥ 0, heat wanted, average over the period |

`HeatStoreOutput` (`PlantOutput` subclass, all Series on the input index); none of these is a flow
name, so nothing is passed on (0019 naming scheme, rule 3):

| Field | Unit | Meaning |
|---|---|---|
| `power_kw` | kW | always 0: the store makes no electricity |
| `delivered_kw` | kW | heat delivered to the demand |
| `unmet_kw` | kW | demand not covered |
| `dumped_kw` | kW | heat coming in that neither the demand nor the tank could take |
| `loss_kw` | kW | heat lost through the tank walls |
| `stored_kwh` | kWh | heat in the tank at the end of the period |

`State`: `stored_kwh` (a number).

## Requirements

Parameters and inputs
- **BOIL-001** `HeatStoreParams` MUST have exactly the fields, units, defaults and allowed ranges of the `HeatStoreParams` table, including `temp_hot_c > temp_cold_c > temp_room_c`, and MUST reject any value outside them at construction.
- **BOIL-002** `HeatStoreInputs` MUST require `heat_kw` and `heat_demand_kw` and MUST reject negative values with an error naming the series.

Model
- **BOIL-003** The tank capacity MUST follow the capacity equation in Domain notes.
- **BOIL-004** Tank losses in each step MUST follow the loss equations in Domain notes for the step length of the input's time axis, and MUST NOT exceed the heat in the tank.
- **BOIL-005** `want` MUST ask for `heat_kw` = this step's `heat_demand_kw` plus the room left in the tank after this step's losses, per "Each time step".
- **BOIL-006** `step` MUST follow "Each time step", so the tank never holds less than 0 or more than its capacity and `delivered_kw + unmet_kw = heat_demand_kw` in every step.
- **BOIL-007** Over any run the energy balance in Domain notes MUST close within 1e-6 relative.
- **BOIL-008** `initial_state` MUST be `initial_fill × capacity_kwh`, and `simulate` MUST start from it on every call.
- **BOIL-009** A store with `volume_m3` 0 MUST pass heat straight through: `delivered_kw = min(heat_kw, heat_demand_kw)`, the rest dumped, `loss_kw` and `stored_kwh` 0.
- **BOIL-010** `simulate` MUST return a `HeatStoreOutput` whose fields are Series on the input index, with `power_kw` 0 in every step.
- **BOIL-011** Tank capacity and losses MUST come from oemof.thermal (`kiozesim[system]`, `oemof.thermal==0.0.9a1`), imported lazily in the plant's adapter; no oemof object MAY appear in the plant's public API, and a store with `volume_m3` 0 MUST work with the core dependencies only.

Datasheets
- **BOIL-012** The `combustion` shelf MUST ship the boilers in the "Bundled boilers" table, with exactly those values.

Validation
- **BOIL-013** For a 50 m³ tank, 2 m high, U 0.4 W/(m²·K), 80/40 °C, room 15 °C, the hourly `loss_rate`, `fixed_losses_relative` and `fixed_losses_absolute` used by the plant MUST equal the values of the published equations in Domain notes, worked out by hand and kept in the test, within 1e-9 relative (this catches unit mix-ups between kWh, MWh, seconds and hours in the adapter).
- **BOIL-014** A full tank with no heat in and no demand MUST lose heat step by step as the loss equations give, with no sub-stepping: after 24 hourly steps `stored_kwh` MUST match the result of repeating `stored_n = (1 − β)·stored_{n−1} − (γ·capacity + δ)` within 1e-9 relative.

## Acceptance
- Every BOIL-xxx requirement has at least one test marked with its ID; `uv run pytest`,
  `uv run python scripts/spec_check.py`, `ruff` and `mypy` are green.
- `kiozesim/tests/golden/heat_store/` holds a one-week hourly case (steady heat in, demand that
  changes over the day) whose energy balance closes; the empty `golden/boiler/` folder goes.
- The heat store is usable in both apps behind a combustion plant, with `heat_demand_kw` from a
  source (0019 CHAIN-040).
- Spec edit on approval: 0001 open question "what `power_kw` means for the boiler" resolved:
  electricity, so 0 for the heat store; the boiler is a combustion plant (0019).

## Open questions
- [x] **Bundled boilers**: ICI Caldaie REX 15, 30, 62 (decided 2026-10-15, "looks ok").
- [x] **Condensing boilers**: left out; efficiencies stay below 1 (decided 2026-10-15).
- [x] **Tank defaults**: height 2 m, U 0.4, 80/40 °C, room 15 °C, half full (decided 2026-10-15).
- [x] **FMU**: not needed (decided 2026-10-15).
- [x] **Sub-stepping**: not needed (decided 2026-10-15).
- [x] **Boiler and tank one plant or two**: two; the boiler is a combustion plant datasheet, the
      tank its own plant in a chain (0019, decided 2026-10-15).
- [x] **Control rule**: by requests in the chain; the tank asks for demand plus room (0019).

## Changelog
- 2026-10-05 stub created
- 2026-10-15 draft: one plant, boiler and tank, fed `fuel_kw` and `heat_demand_kw`; no electricity;
  tank losses from oemof.thermal's stratified tank equations, called through an adapter
  (oemof.thermal 0.0.9a1); bundled boilers ICI Caldaie REX 15, 30, 62
- 2026-10-15 rewritten after 0019 (plant chains): the boiler becomes combustion-plant datasheets,
  the tank its own plant `HeatStorePlant` (`heat_store`) at the end of a chain, asking upstream for
  demand plus room; title "Heat store and bundled boilers"
- 2026-10-15 approved
- 2026-10-15 implemented (`kiozesim/plants/heat_store/`, REX datasheets on the `combustion` shelf)
