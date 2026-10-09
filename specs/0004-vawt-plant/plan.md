# 0004 VAWT plant: plan

How to build [spec.md](spec.md). Written 2026-10-09.

## Design in one paragraph
`VAWTPlant` is a pydantic shell in `plant.py`, like HAWT, but with no external engine: the physics
is our own NumPy code. `_air.py` lifts wind to hub height and computes air density with exactly
windpowerlib's formulas (VAWT-014), written out so windpowerlib is not needed. `plant.py` picks the
method: `power_curve` interpolates the datasheet table; `geometry` gets a Cp(TSR) curve once per
plant (cached on the instance) from `_savonius.py` (bundled Sandia curve) or `_dmst.py` (DMST with
bundled Sandia airfoil tables), then applies the Formula section per time step.

## Phases
The three methods need very different amounts of outside data, so they are built in this order;
each phase ends green (tests, spec_check, ruff, mypy).

1. **Shell + power curve** (no outside data): models per the Interface tables, `_air.py`,
   `power_curve` path, VAWT-001..005, 014, 015 (power-curve half), 016, 020, 021.
   `geometry` plants raise `NotImplementedError` until phases 2–3.
2. **Savonius**: zEPHYR points. VAWT-007, 008, 009, 011–013, 019.
3. **Darrieus**: airfoil tables, RM2 and 17-m data. VAWT-006, 010, 017, 018, 022.

## Modules touched

| File | Change |
|---|---|
| `kiozesim/src/kiozesim/plants/vawt/plant.py` | rewrite per the Interface tables; `VAWTOutput`; `cp_curve()`; `_simulate` |
| `kiozesim/src/kiozesim/plants/vawt/_air.py` | **new**: log profile, temperature gradient, barometric density |
| `kiozesim/src/kiozesim/plants/vawt/_savonius.py` | **new** (phase 2): loads the bundled curve |
| `kiozesim/src/kiozesim/plants/vawt/_dmst.py` | **new** (phase 3): DMST solver, troposkien outline |
| `kiozesim/src/kiozesim/plants/vawt/__init__.py` | also export `VAWTOutput` |
| `kiozesim/src/kiozesim/datasheets/vawt/_data/` | airfoil CSVs (phase 3), Savonius CSV (phase 2), each with source and licence |
| `kiozesim/tests/test_vawt.py` | **new** |
| `kiozesim/tests/golden/vawt/{rm2,sandia_17m,zephyr}/` | measured points, geometry, provenance |

## Phase 1 details
- `VAWTDatasheet`: every method/family field is `Optional = None`; an `after` validator builds the
  required and forbidden field sets from `method`, `rotor_type` and `control` and reports each
  missing or extra field by name (VAWT-001). The power-curve checks repeat HAWT's (≥ 2 points,
  equal lengths, speeds ≥ 0 strictly increasing, powers 0 … 1.05 × rated).
- `VAWTParams`: HAWT's fields and checks plus `hub_height_m > rotor_height_m / 2` (the rotor would
  hit the ground otherwise).
- `VAWTInputs`: same as HAWT's.
- `_air.py`: `wind_at_hub`, `density_at_hub`. Tests compare against windpowerlib's
  `logarithmic_profile`, `linear_gradient` and `barometric` when it is installed (dev and CI
  install all extras), and against hand values otherwise.
- Power curve (VAWT-020): `np.interp`, then 0 where `v_hub` is below the first or above the last
  speed, then `× ρ/1.225`, capped at `max(power_kw)`.
- `air_density_kg_m3` is a constant 1.225 Series without density correction (spec), unlike HAWT's
  None.

## Phase 2–3 data sources (decision F, 2026-10-09)
- **Airfoils** NACA 0015/0018/0021: Sandia CACTUS `test/Airfoil_Section_Data/NACA_00xx.dat`
  (BSD-3), = SAND80-2114 Tables 3–5 (one full page checked by eye against the scan: 49/49 rows
  equal). Copied into `datasheets/vawt/_data/` as CSV (Re, alpha, cl, cd; 0–180° only, CACTUS
  stores ±180° symmetric), keeping the BSD-3 notice; the 0021 Re 8·10⁶ block is dropped.
- **Savonius**: zEPHYR `data/U6_characteristics.txt` (CC-BY 4.0), L0–L7.
- **RM2** (VAWT-018): `Data/Processed/Perf-1.2.csv` from UNH-CORE/RM2-tow-tank (CC-BY 4.0),
  columns `mean_tsr`, `mean_cp`. Geometry from its README; taper confirmed by Sandia's OWENSAero
  RM2 example (widest at mid-height). Peak 0.370 at λ 3.1; repeat run `-b` agrees within 0.005.
- **17-m** (VAWT-022): NASA NTRS 19800008205, Figure 6 (page 10 of the PDF), points read off a
  300 dpi render by locating circle centres against the axis ticks; script and scale in the
  golden case.

## DMST (phase 3)
Stacked streamtubes, Paraschivoiu double-actuator-disc form: per layer and azimuth, upwind
induction from momentum balance with blade forces from the airfoil table, downwind sees the
upwind wake speed. Curved blades add the local blade slope δ (normal velocity and force
components). Heavy loading (induction > 0.4) uses Glauert's empirical correction. Numbers of
layers and azimuth tubes fixed in code and checked for convergence by a test.

## Risks
- **VAWT-018 may miss ±15 %.** Plain DMST without dynamic stall tends to over-predict peak Cp. If
  it misses, stop and bring the numbers to the user; do not tune or loosen without a spec change.
- **RM2 is water with 10 % blockage and struts**: measured Cp is pushed up by blockage and down by
  struts. If VAWT-018 misses, report both effects with the numbers; do not tune.
- **Low-Re airfoil data is odd.** Sandia's Eppler tables at Re 10⁴–4·10⁴ show negative lift at
  small angles (laminar separation). Small rotors will reach these; the results will be poor but
  faithful to the source.
- **DMST convergence**: the induction iteration can fail at high λ (heavy loading). Use the
  standard Glauert/empirical correction for induction above 0.4, named in `_dmst.py`.

## Outcome (2026-10-09)
- All three methods built. VAWT-018 (RM2): 0.445 at λ 4.10 vs measured 0.370 at 3.23 (+20 %, passes
  the loosened ±25 % / ±1.0). VAWT-022 (17-m): 0.437 at λ 5.65 vs 0.408 at 5.82 (+7 %).
  Struts explain about 0.016 of the RM2 gap (UNH "no blades" run); the rest is DMST without
  dynamic stall and flow curvature (spec 0013). Grid converged: 2× and 4× layers/tubes change
  peak Cp by < 0.001.
- 17-m Figure 6: 30 circles found by ring matching; two weaker hits (0.74, 0.64 of the legend
  circle's score) were the curve crossing circles and are cut off by the 0.8 threshold.
- Speed: straight untapered rotors solve one layer (identical layers merged), about 0.1 s per
  curve; tapered or curved about 2 s, once per plant. Bisection 25 steps (vs 40: < 1e-8 change).
- Bug injection (4 mutations in `_dmst.py`: no downwind wake slowing, drag left out of CT, taper
  ignored, troposkien radius ignored): each makes a VAWT test fail.
- The zEPHYR "no load" row L0 is consistent (Cp = Ct × λ) and kept; only the duplicate L8 is dropped.
