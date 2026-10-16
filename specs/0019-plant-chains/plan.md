# 0019 Plant chains: plan

How to build [spec.md](spec.md), together with [0006](../0006-boiler-heat-store/spec.md) (heat
store, bundled boilers). Written 2026-10-15.

## Design in one paragraph
`Plant` gains a one-step form (`initial_state`, `want`, `step`, `needs`, `follows_requests`) with
defaults that wrap `simulate`, so PV, HAWT and VAWT need no changes. Three plants change shape: the
gas engine becomes `CombustionPlant` (boilers are its datasheets), the digester moves from
`kiozesim/sources/` to `kiozesim/plants/digester/`, and the tank is the new `HeatStorePlant`.
`kiozesim/chain.py` runs a straight chain in three zones: plants at the front that ignore requests
and have no memory (a digester) run vectorised with `simulate`; the plants from there up to the last
plant with memory are stepped with a backward pass of `want` (`_requests`) and a forward pass of
`step` (`_supplies`); plants behind it hear no requests and run vectorised too. Each plant in a run is a small
`_Link` (the plant, the inputs piped from the front, its own columns). The tool's wiring groups plants into chains, runs each with `Chain`, and
carries states from one day's chunk to the next.

## Modules touched

| File | Change |
|---|---|
| `kiozesim/src/kiozesim/plants/base.py` | step contract with defaults; `PlantOutput.to_frame`; `Sizing` |
| `kiozesim/src/kiozesim/errors.py` | `CannotBeAsked` |
| `kiozesim/src/kiozesim/chain.py` | **new**: `FLOWS`, `Chain`, `ChainResult`, `SizingStep`, `SizingResult` |
| `kiozesim/src/kiozesim/plants/combustion/` | **new** (from `chp/`): datasheet with one of two ratings, availability 1, spare fuel as `fuel_kw`, `want`/`step`/`needs` |
| `kiozesim/src/kiozesim/plants/digester/` | **new** (from `sources/digester/`): `DigesterPlant`, scalar outputs, `needs` scales the feed |
| `kiozesim/src/kiozesim/plants/heat_store/` | **new** (replaces `boiler/`): `HeatStorePlant`, `_engine.py` oemof.thermal adapter |
| `kiozesim/src/kiozesim/plants/{chp,boiler}/`, `sources/` | **deleted** |
| `kiozesim/src/kiozesim/plants/__init__.py` | `REGISTRY`: pv, hawt, vawt, combustion, digester, heat_store |
| `kiozesim/src/kiozesim/datasheets/combustion/` | TEDOM files moved from `chp/`; ICI REX 15, 30, 62 added |
| `kiozesim/tests/harness.py` | datasheet optional; `column:` picks the checked output (default `power_kw`) |
| `kiozesim/tests/golden/` | `chp/` → `combustion/`; `boiler/` → `heat_store/week_daily_demand/` (made by a hand-written script) |
| `kiozesim-tool/src/kiozesim_tool/sources.py` | **new**: `Source`, `ConstantSource` moved from the library |
| `kiozesim-tool/src/kiozesim_tool/wiring.py` | plants in `from`; chains found and checked (merge, split, loop); `run` returns power, outputs and states |
| `kiozesim-tool/src/kiozesim_tool/{boxes,config,cli,weather}.py` | new type lists; `size` command; states carried across chunks; chunks ≥ 2 steps |
| `kiozesim-tool/src/kiozesim_tool/ui/` | `from` lists plants too; sizing section |
| `kiozesim-tool/examples/sink.yaml` | digester → combustion chain |
| specs, constitution, README, CLAUDE.md | edits listed in the spec's Acceptance |

## Runner details
- Flow inputs of plant *i* come from plant *i − 1*'s outputs; everything else from the caller's
  table for that plant. Missing columns raise `MissingInputError` before any step.
- `wanted` for plant *i* = the names plant *i + 1*'s `want` returned; the last plant gets `{}`.
- Vectorised plants: `simulate(inputs_model.from_frame(frame))`, output `to_frame(index)`.
- Stepped plants: plain Python loop over steps, numbers only (a week hourly is ~170 steps, a year
  8760; fine without numpy).

## Sizing
`needs` per plant; `Chain.size` walks back to front, passing the flow inputs one plant needs as the
`wanted` outputs of the plant in front, and stops at `CannotBeAsked`.

## Risks
- The sink's one-day chunks with a 1-day step had one row; chunks become at least two steps so
  states carry over exactly.
- oemof.thermal 0.0.9a1 is a pre-release; only the heat store imports it, lazily.
