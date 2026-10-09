---
id: 0004
title: VAWT plant
prefix: VAWT
status: implemented
---

# 0004 VAWT plant

## Problem
Estimate how much electricity a vertical-axis wind turbine ("VAWT", one that spins around an
upright shaft) or a small group of identical ones delivers in each time step, given the rotor's
shape and size, its height and the weather. Unlike the HAWT plant (spec 0003), which looks output
up in a manufacturer's measured power curve, the VAWT plant **calculates** how good the rotor is
from its geometry. That way designs that were never built or measured can be compared.
Someone who instead has a real product's power curve (the seller's wind speed → kW table) can
use that instead, as for HAWT. The result is power in kW, the same shape as every other plant, so it can be combined in a `Portfolio`.

## Scope
In:
- Two ways to describe a turbine, chosen per datasheet: by its **geometry** (calculated) or by
  its **power curve** (looked up, like HAWT).
- Two rotor families: **Darrieus** (lift-driven, wing-like blades) and **Savonius**
  (drag-driven scoops).
- Geometry, Darrieus: the rotor's efficiency curve Cp(TSR) is computed from its geometry with the
  double-multiple-streamtube (DMST) method, using Sandia's published blade (airfoil) data.
- Geometry, Savonius: the efficiency curve Cp(TSR) is taken from TU Delft's open wind tunnel
  measurements of a 2-scoop rotor (zEPHYR dataset).
- The curve is computed once per rotor, then looked up for each time step.
- `n_turbines` identical turbines that all see the same wind.
- Lifting the measured wind to the rotor's centre height, and the air-density effect, the same as
  for HAWT.
- Power curve: the manufacturer's table of wind speed → kW, interpolated linearly.
- Generator/drivetrain efficiency, rated power limit, cut-in and cut-out wind speeds, and one
  lumped loss percentage.
- Weather time steps from 1 minute up to 1 hour.

Out (each may get its own spec later):
- User-supplied blade (airfoil) data or user-supplied Savonius curves.
- Airfoils other than NACA 0015, 0018 and 0021 (the report's NACA 0012 and 0025 tables exist only
  as a scanned print; 0009 and 0012H have no full tables).
- 3-scoop Savonius rotors (no open measured data found).
- Dynamic stall (the extra, short-lived lift a blade gets when its angle changes quickly), flow
  curvature (the air bending along the circular blade path), struts, blade-tip losses, tower
  shadow. Dynamic stall and flow curvature are planned as switchable corrections in spec 0013.
- Savonius variants other than the measured one (twisted/helical scoops, other overlaps or
  aspect ratios, guide vanes).
- Turbulence, gusts, wind direction (a VAWT does not need to face the wind anyway), icing,
  curtailment, ageing, availability schedules, grid limits.
- Wake losses between turbines beyond the lumped `losses_pct`.
- Fetching weather data; resampling (caller's job, constitution 3).

## Domain notes

### Two ways to describe a turbine (`method`)
- **`geometry`**: the datasheet describes the rotor itself (size, blades, scoops, speed control),
  and the plant calculates how much power it makes. Use this to compare designs, or when no
  trustworthy measured data exists.
- **`power_curve`**: the datasheet holds the seller's table "at this wind speed, the turbine
  delivers this many kW", as for HAWT (spec 0003). The table already includes everything the
  turbine does internally (blade efficiency, speed control, generator losses, cut-in and
  cut-out), so none of those fields are needed. Use this for a real product you can buy. Between
  table points the curve is interpolated linearly; outside the table's wind speeds the output is 0.
- Small-turbine power curves are often marketing numbers rather than independent measurements.
  Curves measured to the IEC 61400-12-1 standard, or certified (for example under the small-turbine
  standard IEC 61400-2), are more trustworthy. The `source` field should say which it is.

### The two rotor families
- **Darrieus**: two or three thin blades, either straight and parallel to the shaft (an
  "H-rotor") or bowed outwards like an eggbeater (a "troposkien", the shape a spinning skipping
  rope takes). The blades are shaped like aeroplane wings. As they spin, the air they meet comes
  mostly from the front of the blade, and the wing shape turns that into **lift** that pulls the
  blade around. These rotors can be fairly efficient (best Cp about 0.35–0.45), but they need to
  spin fast, and many cannot start by themselves in light wind.
- **Savonius**: two or three half-cylinder scoops, like an oil drum cut in half lengthways. The
  wind simply **pushes** the open scoop harder than the rounded back of the other one, like
  pushing a sail. It is simple, quiet and self-starting, but slow and inefficient (best Cp about
  0.15–0.25).

### Power from wind
- The wind carries power `½ × ρ × A × v³` through the area the rotor sweeps:
  - `ρ` is air density (kg/m³), about 1.225 at sea level and 15 °C;
  - `A` is the **swept area** (m²), the rotor's silhouette seen from the wind;
  - `v` is the wind speed (m/s).
  Doubling the wind speed gives 8× the power.
- **Swept area** `A`: for an H-rotor and a Savonius rotor it is `diameter × height` (a rectangle).
  For a curved Darrieus it is the area of the bowed outline, `⅔ × diameter × height` (see the
  outline below).
- **Power coefficient** `Cp`: the share of the wind's power the rotor actually captures.
  `P_rotor = Cp × ½ × ρ × A × v³`. Physics caps it at 16/27 ≈ 0.593 (the **Betz limit**).
  No real rotor gets near that.
- **Tip speed ratio** `TSR` (λ): how fast the blades move compared with the wind,
  `λ = ω × R / v`, where `ω` is the rotation speed in radians per second and `R` the rotor
  radius. A Savonius works best around λ ≈ 0.8–1. A Darrieus works best around λ ≈ 4–6.
- **Cp(TSR) curve**: Cp depends mostly on λ, so one curve describes how good a rotor is at every
  speed ratio. This plant computes or loads that curve once, then for every time step works out
  λ and reads Cp off the curve (interpolating linearly between points).

### Darrieus: how the curve is computed (DMST)
- **Airfoil**: the cross-section shape of a blade. The two digits at the end of a NACA name give
  the thickness as a % of the blade's width, e.g. NACA 0015 is 15 % thick. Supported: NACA 0015,
  0018 and 0021, the shapes most small VAWTs use and the ones whose full 0–180° tables Sandia
  also publishes in machine-readable form (see "Engine and references").
- **Chord** `chord_m`: the blade's width from front edge to back edge, at mid-height. Blades may
  **taper** (get narrower towards their ends): with `tip_chord_m` the width changes linearly
  from `chord_m` at mid-height to `tip_chord_m` at the top and bottom ends. Without it the width
  is the same everywhere.
- **Angle of attack**: the angle between the blade and the air it meets. On a VAWT this angle
  changes all the way round each turn, from 0° up past **stall** (where the wing stops lifting
  and mostly drags) and back. So the blade data must cover every angle from 0 to 180°.
- **Lift and drag coefficients**: two numbers, read from the airfoil table for a given angle,
  that say how hard the blade is pulled sideways (lift, useful) and backwards (drag, wasteful).
- **Reynolds number** `Re`: one number combining blade width, air speed at the blade and air
  "stickiness". Small, slow blades (low Re) lift worse than large, fast ones. Sandia tabulates
  each airfoil at several Re values (10 000 up to 10 000 000 for NACA 0015, up to 5 000 000 for
  0018 and 0021), and the model interpolates between them; outside that range it uses the
  nearest table.
- **One curve per rotor**: Re depends on how fast the blade moves, which depends on the wind. To
  compute the curve only once, each λ is paired with one wind speed. For `fixed_rpm` this is
  exact: `v = ω × R / λ`. For `optimal_tsr` the datasheet's `rated_wind_speed_m_s` is used for
  every λ. Air "stickiness" (kinematic viscosity) is taken as constant, 1.46 × 10⁻⁵ m²/s (15 °C).
  This can be slightly optimistic for small rotors in light wind.
- **DMST** (double multiple streamtube, Paraschivoiu 1981): the standard quick method for
  Darrieus rotors.
  1. Slice the rotor into thin horizontal layers. On a curved rotor each layer has its own
     radius.
  2. Split each layer into narrow "tubes" of air flowing through the rotor, one per angle
     around the circle.
  3. In each tube the air passes the blades twice: on the upwind half, and again on the
     downwind half, where it has already been slowed by the first pass.
  4. In each half, find how much the air is slowed so that the push the blades get (from the
     airfoil table) equals the push the air loses. This is a small equation solved by
     iteration.
  5. Add the blade forces over all tubes and layers to get the torque, then the power, then Cp.

  Repeating this for λ from 0.1 to 15 in steps of 0.05 gives the Cp(TSR) curve.
- **Where the curve stops**: at very low and very high λ the calculation gives a negative Cp,
  meaning the rotor would have to be driven by a motor. A real turbine does not do that; it just
  makes no power. So the curve keeps only the unbroken stretch of λ around the best Cp where Cp
  is positive; outside it Cp is 0, by the same "0 outside the curve" rule as everywhere else.
- **Known limitation**: plain DMST is optimistic for small rotors whose blades are wide compared
  with the radius (chord/radius around 0.1 or more). Against the UNH RM2 rotor it gives about
  20 % more peak Cp than measured, at a λ about 1 higher (VAWT-018). Against the slender Sandia
  17-m rotor it is within 7 % (VAWT-022). Spec 0013 is meant to reduce the gap.
- Reference: I. Paraschivoiu, *Wind Turbine Design: With Emphasis on Darrieus Concept*, Polytechnic
  International Press, 2002.

### Savonius: where the curve comes from
- TU Delft measured a 2-scoop rotor (0.5 m wide, 2.2 m tall, scoops overlapping by 80 mm at the
  centre) in its Open Jet Facility at 6 m/s, at 9 generator loads (zEPHYR dataset, Sachar et al.
  2023, CC-BY 4.0). Its best Cp is 0.158 at λ = 0.74.
- The bundled curve is those measured points, ordered by λ: loads L0–L7 (λ 0.36–1.17). L8
  repeats L7 exactly and is left out. Outside λ 0.36–1.17 the curve gives Cp = 0.
- Rotor size enters only through the swept area and the radius in λ. Cp itself is taken to be
  the same for a small and a large rotor of the same shape.

### Rotor speed control
How fast the rotor turns in a given wind decides λ, and so Cp. This is a property of the product,
so it goes in the datasheet:
- **Fixed speed** (`control: fixed_rpm`): the generator holds the rotor at one speed, as on
  Sandia's research turbines. λ changes with the wind, so the rotor is only at its best in one
  wind speed.
- **Variable speed** (`control: optimal_tsr`): the controller adjusts rotor speed so λ stays at
  the curve's best point. This is how most modern small turbines work ("MPPT"). Above rated
  power it holds output at rated power.

### Wind and air (same as HAWT, spec 0003)
- **Wind grows with height**. The measured wind is lifted to `hub_height_m`, the height of the
  rotor's middle, with the logarithmic profile and `roughness_length_m`:
  `v_hub = v_meas × ln(h_hub / z0) / ln(h_meas / z0)`. See spec 0003 for the roughness table.
- **Air density** at hub height, from temperature (carried up at −6.5 °C per km) and surface
  pressure (falling 1/8 hPa per metre of height), via the ideal gas law
  `ρ = p × (1.225 × 288.15 / 101 330) / T`, which is windpowerlib's "barometric" formula used by HAWT. Without density
  correction, `ρ = 1.225 kg/m³`. With `geometry`, density enters the power formula directly. With
  `power_curve`, the published curve holds for 1.225 kg/m³, so its output is multiplied by
  `ρ / 1.225` (the IEC 61400-12-1 rule for turbines without blade pitch control, which covers
  nearly every small VAWT), never exceeding the curve's maximum.

### Turbine limits and losses (geometry)
- **Cut-in speed** `cut_in_m_s`: below it the rotor does not turn usefully; output is 0.
- **Cut-out speed** `cut_out_m_s`: above it the turbine brakes to protect itself; output is 0.
- **Rated power** `rated_power_kw`: the generator's maximum output; output is capped there.
- **Drivetrain efficiency** `drivetrain_efficiency_pct`: share of the rotor's mechanical power
  that comes out of the generator as electricity (gearbox, generator, converter). Small turbines
  typically reach 75–90 %.
- **Lumped losses** `losses_pct` (both methods): wake effects inside a group, maintenance
  downtime, cabling.

### Time convention
Same as HAWT: inputs are averages over each period, labelled at the period start; the output keeps
the input's labels. Steps longer than 1 hour are rejected, because output grows with the cube of
wind speed.

### Formula
```
method: geometry
once per rotor:
  curve      = DMST(geometry, airfoil)          (Darrieus)
             | zEPHYR curve                     (Savonius)
  A          = swept area from geometry
per time step:
  v_hub      = logarithmic profile(wind_speed_m_s, wind_height_m → hub_height_m, roughness_length_m)
  ρ          = density at hub height (only if density_correction), else 1.225
  λ          = rpm × 2π/60 × R / v_hub      (fixed_rpm)
             | λ at the curve's maximum Cp     (optimal_tsr)
  Cp         = curve(λ), 0 outside the curve
  P_rotor    = Cp × ½ × ρ × A × v_hub³
  P_turbine  = min(P_rotor × drivetrain_efficiency_pct/100, rated_power_kw),
               0 when v_hub < cut_in_m_s or v_hub > cut_out_m_s
  power_kw   = n_turbines × P_turbine × (1 − losses_pct / 100)

method: power_curve
per time step:
  v_hub, ρ   = as above
  P_turbine  = min(power curve(v_hub) × ρ / 1.225, max(power_kw curve)),
               0 outside the curve's wind speed range
  power_kw   = n_turbines × P_turbine × (1 − losses_pct / 100)
```

### Engine and references
- Engine: our own NumPy code in `kiozesim/plants/vawt/`. There is no established Python VAWT
  library, so no optional extra is needed.
- R. E. Sheldahl, P. C. Klimas, *Aerodynamic characteristics of seven symmetrical airfoil sections
  through 180-degree angle of attack for use in aerodynamic analysis of vertical axis wind
  turbines*, Sandia SAND80-2114, 1981 (public domain). Tables 3–5 (NACA 0015, 0018, 0021) are the
  bundled airfoil data, taken from the machine-readable copy Sandia ships with its CACTUS code
  (github.com/sandialabs/CACTUS, `test/Airfoil_Section_Data/`, BSD-3-Clause). CACTUS's extra
  NACA 0021 table at Re 8 000 000 (added 1988, not in the report) is left out.
- M. Sachar et al., *zEPHYR – noise and performance correlation of a Savonius type vertical axis
  wind turbine*, Zenodo 2023, doi:10.5281/zenodo.8328824, CC-BY 4.0. Bundled Savonius curve.
- P. Bachant, M. Wosnik, B. Gunawan, V. Neary, *Experimental study of a reference model
  vertical-axis cross-flow turbine*, PLoS ONE 2016; data: github.com/UNH-CORE/RM2-tow-tank
  (doi:10.6084/m9.figshare.1373899), CC-BY 4.0. Darrieus validation (VAWT-018).
- E. Nellums, M. H. Worstell, *Test results of the DOE/Sandia 17 meter VAWT*, 1979, NASA NTRS
  19800008205 (public domain). Darrieus validation (VAWT-022).
- IEC 61400-12-1, *Power performance measurements of electricity producing wind turbines*
  (power-curve method).

## Interface

`VAWTDatasheet` (rotor product data, YAML in `kiozesim/datasheets/vawt/`):

| Field | Unit | Allowed | Meaning |
|---|---|---|---|
| All datasheets: | | | |
| `manufacturer`, `model`, `source` | – | – | from `Datasheet` |
| `method` | – | `geometry`, `power_curve` | how the turbine is described |
| `rotor_type` | – | `darrieus`, `savonius` | rotor family |
| `rotor_diameter_m` | m | > 0 | largest diameter |
| `rotor_height_m` | m | > 0 | height of the bladed part |
| `rated_power_kw` | kW | > 0 | generator maximum (nameplate) |
| `power_curve` only: | | | |
| `wind_speed_m_s` | m/s | ≥ 2 points, ≥ 0, strictly increasing | power curve: wind speed at hub height |
| `power_kw` | kW | same length, each 0 … 1.10 × `rated_power_kw` | power curve: output at that speed |
| `geometry` only: | | | |
| `cut_in_m_s` | m/s | ≥ 0 | |
| `cut_out_m_s` | m/s | > `cut_in_m_s` | |
| `drivetrain_efficiency_pct` | % | 0 < x ≤ 100 | |
| `control` | – | `fixed_rpm`, `optimal_tsr` | rotor speed control |
| `rpm` | rev/min | > 0; required if and only if `control: fixed_rpm` | fixed rotor speed |
| `rated_wind_speed_m_s` | m/s | > `cut_in_m_s`, < `cut_out_m_s`; required if and only if `control: optimal_tsr` | wind speed at which rated power is reached (reference for Re) |
| `geometry`, Darrieus only: | | | |
| `n_blades` | – | 1–6 (integer) | number of blades |
| `chord_m` | m | > 0 | blade width at mid-height |
| `tip_chord_m` | m | > 0, optional | blade width at the ends (tapered blades) |
| `airfoil` | – | `NACA0015`, `NACA0018`, `NACA0021` | blade cross-section |
| `blade_shape` | – | `straight`, `troposkien` | H-rotor or curved |
| `geometry`, Savonius only: | | | |
| `n_buckets` | – | 2 | number of scoops |

Fields belonging to the other method or the other rotor family MUST be absent. A troposkien's
outline is approximated by a parabola through the top, the widest point and the bottom:
radius `r(z) = R × (1 − (2z / H)²)` at height `z` from the middle, with `R = rotor_diameter_m / 2`
and `H = rotor_height_m`. Sandia's 17-m blades ("straight–circular–straight") are 79 ft long; the
parabola for that rotor is within 1 % of it.

### Bundled datasheets (`kiozesim/datasheets/vawt/`)
Real products (`method: power_curve`). No VAWT maker publishes a usable power-curve table, so both
come from independent test reports (DS-008):

| Name | Turbine | Source | Notes |
|---|---|---|---|
| `mariah_power_windspire` | Mariah Power Windspire, 1 kW, straight-blade Darrieus, 1.2 m × 6.10 m | NREL/TP-500-46192 (2009), Table 6 | test not completed: no data above 13.5 m/s, so output is 0 there; width derived from the report's Cp column |
| `hi_vawt_technology_corp_ds3000` | Hi-VAWT DS3000, combined Darrieus–Savonius, AWEA rated 1.4 kW at 11 m/s | ICC-SWCC Summary Report SWCC-18-02 | values printed in W under a "kW" heading; size is the equivalent rectangle of the stated swept area 10.6 m² (3.66 m × 2.90 m) |

Both reports show small negative power in light wind (the turbine's own standby draw); those bins
are set to 0, since this plant does not model standby consumption.

Two illustrative examples (DS-012) so the apps can offer the `geometry` method. They are made up,
sized so their rated power is what this model gives at their rated wind speed:

| Field | `example_darrieus_h_rotor_3_kw` | `example_savonius_0_4_kw` |
|---|---|---|
| `manufacturer` / `model` | Example / Darrieus H-rotor 3 kW | Example / Savonius 0.4 kW |
| `source` | Illustrative example, not a real product (spec 0004) | same |
| `rotor_type` | darrieus | savonius |
| `rotor_diameter_m` × `rotor_height_m` | 3.0 × 3.5 | 1.2 × 2.4 |
| `rated_power_kw` | 3.0 | 0.4 |
| `cut_in_m_s` / `cut_out_m_s` | 3.0 / 20 | 2.5 / 25 |
| `drivetrain_efficiency_pct` | 85 | 85 |
| `control` / `rated_wind_speed_m_s` | optimal_tsr / 10.5 | optimal_tsr / 12 |
| `n_blades`, `chord_m`, `airfoil`, `blade_shape` | 3, 0.10, NACA0018, straight | – |
| `n_buckets` | – | 2 |

`VAWTParams`:

| Field | Unit | Default | Allowed | Meaning |
|---|---|---|---|---|
| `name` | – | required | – | plant name (from `PlantParams`) |
| `datasheet` | – | required | – | a `VAWTDatasheet` |
| `hub_height_m` | m | required | > `rotor_height_m` / 2 | height of the rotor's middle above ground |
| `n_turbines` | – | 1 | ≥ 1 (integer) | number of identical turbines |
| `wind_height_m` | m | 10 | > `roughness_length_m` | height at which the input wind was measured |
| `roughness_length_m` | m | 0.1 | > 0, < `hub_height_m` | ground roughness (spec 0003 table) |
| `temp_height_m` | m | 2 | > 0 | height at which the input temperature was measured |
| `density_correction` | – | true | bool | use measured air density |
| `losses_pct` | % | 10 | 0 ≤ x < 100 | lumped losses |

`VAWTInputs` (`TimeSeries`; every series is a period average on the shared index):

| Field | Unit | Required | Allowed |
|---|---|---|---|
| `wind_speed_m_s` | m/s | yes | ≥ 0, at `wind_height_m` |
| `temp_air_c` | °C | when `density_correction` | finite, at `temp_height_m` |
| `pressure_hpa` | hPa | when `density_correction` | > 0, surface pressure at ground level |

`VAWTOutput` (`PlantOutput` subclass, all Series on the input index):

| Field | Unit | Meaning |
|---|---|---|
| `power_kw` | kW | power delivered by all turbines after losses, average over the period |
| `wind_speed_hub_m_s` | m/s | wind speed lifted to hub height |
| `air_density_kg_m3` | kg/m³ | air density at hub height (1.225 without density correction) |
| `tsr` | – | tip speed ratio λ used; absent (None) for `power_curve` |
| `cp` | – | power coefficient read from the curve; absent (None) for `power_curve` |

`VAWTPlant.cp_curve() -> pandas.DataFrame | None` (columns `tsr`, `cp`): the rotor's computed or
bundled curve, for display and checks; None for `power_curve`.

## Requirements

Parameters and inputs
- **VAWT-001** `VAWTDatasheet` MUST have exactly the fields of the `VAWTDatasheet` table and MUST reject at load time any value outside the allowed ranges, a missing method- or family-specific field, a field of the other method or family, `rpm` present without `control: fixed_rpm` or missing with it, and `rated_wind_speed_m_s` present without `control: optimal_tsr` or missing with it.
- **VAWT-002** `VAWTParams` MUST have exactly the fields, units, defaults and allowed ranges of the `VAWTParams` table and MUST reject any value outside them at construction.
- **VAWT-003** `VAWTInputs` MUST require `wind_speed_m_s` and MUST reject negative values in it with an error naming the series.
- **VAWT-004** `VAWTPlant.simulate` MUST raise an error naming the missing series when `density_correction` is true and `temp_air_c` or `pressure_hpa` is absent; when it is false, both MAY be absent and MUST be ignored if given.
- **VAWT-005** `VAWTPlant.simulate` MUST reject inputs whose time step is longer than 1 hour.

Cp(TSR) curve
- **VAWT-006** For a Darrieus rotor the curve MUST be computed with DMST as described under "Darrieus: how the curve is computed", with the blade width and radius of each layer taken from `chord_m`, `tip_chord_m` and the outline, using the bundled Sandia airfoil table for `airfoil`, interpolated linearly in angle of attack and Reynolds number, with each λ paired with one wind speed as described under "One curve per rotor".
- **VAWT-007** For a Savonius rotor the curve MUST be the bundled zEPHYR curve (loads L0–L7, ordered by λ).
- **VAWT-008** For `geometry`, the curve MUST be computed or loaded once per plant, not per time step, and `cp_curve()` MUST return it; for `power_curve`, `cp_curve()` MUST return None.
- **VAWT-009** A computed Darrieus curve MUST keep only the unbroken range of λ around its maximum where Cp > 0; every Cp on a curve MUST be ≥ 0 and below the Betz limit 16/27, and a curve that breaks this (or has no positive Cp at all) MUST raise an error rather than be clipped.
- **VAWT-010** The bundled airfoil tables MUST hold SAND80-2114 Tables 3–5's lift and drag coefficients for 0–180° at every Reynolds number the report gives, and the bundled Savonius curve MUST hold the zEPHYR points, each file with its source recorded.

Model
- **VAWT-011** For `geometry`, the swept area MUST be `rotor_diameter_m × rotor_height_m` for Savonius and straight Darrieus rotors, and `⅔ × rotor_diameter_m × rotor_height_m` (the parabolic outline) for troposkien rotors.
- **VAWT-012** For `geometry`, λ MUST be computed from `rpm` for `fixed_rpm` and MUST be the curve's best λ for `optimal_tsr`.
- **VAWT-013** For `geometry`, `power_kw` MUST follow the "Formula" section: Cp read from the curve (0 outside it), times ½ρAv³, times drivetrain efficiency, capped at `rated_power_kw`, 0 below cut-in and above cut-out, times `n_turbines` and `(1 − losses_pct/100)`.
- **VAWT-014** Wind lifting and air density MUST be computed as for HAWT (logarithmic profile, linear temperature gradient −6.5 °C/km, barometric pressure); when `wind_height_m` equals `hub_height_m`, `wind_speed_hub_m_s` MUST equal the input.
- **VAWT-015** `simulate` MUST return a `VAWTOutput` with every field of the `VAWTOutput` table as Series on the input index, except `tsr` and `cp`, which MUST be None for `power_curve`.
- **VAWT-020** For `power_curve`, `power_kw` MUST follow the "Formula" section: the curve interpolated linearly at `v_hub`, 0 below its first and above its last wind speed, multiplied by `ρ / 1.225` and capped at the curve's maximum `power_kw`, times `n_turbines` and `(1 − losses_pct/100)`.
- **VAWT-016** Importing `kiozesim` MUST NOT compute any curve or load any airfoil table.

Datasheets
- **VAWT-023** The `vawt` shelf MUST ship the two illustrative examples with exactly the values in "Bundled datasheets", and the two real products listed there with their report's power curve, each with its document and URL in `source`.

Golden data
- **VAWT-017** `kiozesim/tests/golden/vawt/` MUST hold, for each validation case, the measured points, the rotor geometry exactly as the source states it, and the source (citation, licence, which table or figure).

Validation

In VAWT-018 and VAWT-022, the *measured peak λ* is the top of a parabola fitted (least squares)
through the measured points whose Cp is at least 85 % of the highest measured Cp; the *measured
maximum* is the highest measured Cp. For the computed curve both are read directly off the
curve (its grid is 0.05 in λ).

- **VAWT-018** For the UNH RM2 turbine (3 straight tapered NACA 0021 blades, D 1.075 m, H 0.8067 m, chord 0.06667 m at mid-height to 0.04 m at the ends), the computed curve's maximum Cp MUST be within ±25 % of the measured maximum of run `Perf-1.2`, and the λ where it occurs MUST be within ±1.0 of the measured one (loosened from ±15 % / ±0.5, see "Known limitation"). The curve is computed with `optimal_tsr` and `rated_wind_speed_m_s` = 1.2 m/s × (1.46 × 10⁻⁵ / 1.0 × 10⁻⁶) = 17.5 m/s, the air speed with the same Reynolds number as the tow tank's water.
- **VAWT-019** For a `geometry` Savonius, `cp_curve()` MUST return the bundled zEPHYR points unchanged, and the power of a Savonius plant at one known wind speed MUST equal a hand calculation from the Formula section within 0.1 %.
- **VAWT-022** For the Sandia 17-m Darrieus with 2 NACA 0015 blades of 24 in (0.61 m) chord without struts (D 54.9 ft, H 55.8 ft, troposkien) at a fixed 46.7 rpm, the computed curve's maximum Cp MUST be within ±15 % of the maximum of the field test points in Nellums & Worstell's Figure 6, and the λ where it occurs MUST be within ±0.5 of the measured one.
- **VAWT-021** For `power_curve`, with `wind_height_m = hub_height_m`, no density correction and `losses_pct = 0`, `power_kw` at each of the curve's wind speeds MUST equal the curve's value exactly, and halfway between two points MUST equal their average.

## Acceptance
- Every VAWT-xxx requirement has at least one test marked with its ID; `uv run pytest`,
  `uv run python scripts/spec_check.py`, `ruff` and `mypy` are green.
- The ±15 % of VAWT-022 (and the ±25 % of VAWT-018) allows for what DMST leaves out (dynamic stall, flow
  curvature, struts), which is typical accuracy for the method. RM2's measured Cp includes
  strut drag and 10 % tank blockage (not corrected by its authors, which pushes measured Cp up).
  The 17-m case is partly circular: Sandia chose where the NACA 0015 table switches from
  calculated to measured data by matching this turbine at 50.6 rpm; Figure 6 (46.7 rpm) is the
  other speed tested. RM2 is the independent check.
- The 17-m points are read off the scanned Figure 6; the reading method and the pixel scale go
  into the golden case.
- A test re-checks a sample of the bundled airfoil values against numbers read from the printed
  SAND80-2114 tables.

## Open questions
- [x] **A. Model approach**: rotor geometry → Cp(TSR) curve (confirmed 2026-10-09); a
      manufacturer power curve was later added as an alternative (decision E).
- [x] **B. Types in v1**: both Darrieus and Savonius (confirmed 2026-10-09).
- [x] **C. Darrieus airfoil data**: Sandia SAND80-2114 tables (confirmed 2026-10-09; narrowed by F).
- [x] **D. Savonius Cp curve**: Sandia SAND76-0131 wind tunnel data (confirmed 2026-10-09;
      superseded by F).
- [x] **1. Speed control**: both `fixed_rpm` and `optimal_tsr`, chosen per datasheet
      (confirmed 2026-10-09).
- [x] **2. Darrieus blade shape**: both straight and troposkien (confirmed 2026-10-09).
- [x] **3. Reynolds number**: one curve per rotor (confirmed 2026-10-09); this adds
      `rated_wind_speed_m_s` for `optimal_tsr` rotors.
- [x] **4. Validation**: Darrieus peak Cp ±15 %, peak λ ±0.5 against the Sandia 17-m; Savonius by
      exact data reproduction and a hand-calculated power check (confirmed 2026-10-09; data
      sources changed by F).
- [x] **5. Savonius overlap**: per scoop count, bundle the measured configuration with the highest
      maximum Cp (confirmed 2026-10-09; superseded by F, which has one configuration).
- [x] **E. Power curves**: a datasheet may describe the turbine by a power curve instead of its
      geometry (`method: power_curve`) (confirmed 2026-10-09). User-supplied Cp curves stay out.
- [x] **F. Data availability** (2026-10-09): SAND76-0131 and the 17-m reports SAND78-1737/79-1753
      are not openly available. Confirmed replacements: airfoils 0015/0018/0021 only (CACTUS copy
      of SAND80-2114); Savonius from zEPHYR, 2 scoops only; Darrieus validated against both UNH
      RM2 and the Sandia 17-m (NASA NTRS report), each ±15 %.
- [x] **G. RM2 miss** (2026-10-09): plain DMST gives RM2 peak Cp 0.445 at λ 4.1 vs 0.370 at 3.1
      measured (+20 %), converged in grid; struts explain about 0.016. Confirmed: loosen VAWT-018
      to ±25 % / ±1.0 and document the limitation now; dynamic stall and flow curvature as their
      own spec (0013). Negative-Cp ends of the curve are trimmed (VAWT-009).
- [x] **H. Peak location** (2026-10-09): field data have a flat, scattered top (17-m: 0.407 at
      λ 5.52 and 0.408 at 6.29), so the measured peak λ is a parabola fitted through the points
      within 85 % of the best one (confirmed).
- [x] **I. Apps** (2026-10-09): the apps choose datasheets by name, so the shelf ships real
      power-curve products plus two labelled illustrative examples for the geometry method
      (needs DS-012 in spec 0007).
- [x] **7. Real products** (2026-10-09): Mariah Windspire (NREL test report) and Hi-VAWT DS3000
      (ICC-SWCC certification report); DS-008 widened to accept independent test reports. Small
      measured curves overshoot nameplate (Windspire 1.09 kW vs 1 kW), so the power-curve margin
      is 1.10 × rated for VAWT (HAWT keeps 1.05).
- [x] **6. Density and power curves**: multiply output by `ρ / 1.225`, capped at the curve's
      maximum; off when `density_correction` is false (confirmed 2026-10-09).

## Changelog
- 2026-10-05 stub created
- 2026-10-09 draft: decisions A–D, domain notes, interface, VAWT-001..019; open questions 1–5
- 2026-10-09 open questions 1–4 resolved; `rated_wind_speed_m_s` added; VAWT-018/019 filled in;
  open question 5 resolved
- 2026-10-09 decision E: `method: power_curve` alongside geometry; VAWT-020, VAWT-021 added;
  open question 6
- 2026-10-09 open question 6 resolved (power scaled with density)
- 2026-10-09 approved
- 2026-10-09 density formula written out exactly as windpowerlib's (clarifies VAWT-014, no change)
- 2026-10-09 decision F: open data sources replace unavailable Sandia reports; airfoils limited to
  0015/0018/0021; Savonius 2 scoops (zEPHYR); `tip_chord_m` for tapered blades; troposkien as a
  parabola; VAWT-017 now golden data instead of a shelf datasheet; VAWT-018 → RM2; VAWT-022 added
- 2026-10-09 decision G: VAWT-018 loosened to ±25 % / ±1.0 with the limitation documented;
  VAWT-009 trims negative-Cp ends; λ grid 0.1–15 step 0.05; spec 0013 stub for corrections
- 2026-10-09 decision H: measured peak λ defined by a parabola fit over the top points
- 2026-10-09 library built (status stays approved until the apps, specs 0010/0011, support VAWT); VAWT-018: RM2 0.445 at λ 4.10 vs 0.370 at 3.23 (+20 %); VAWT-022: 17-m 0.437 at λ 5.65 vs 0.408 at 5.82 (+7 %)
- 2026-10-09 decision I: bundled datasheets (VAWT-023, two labelled examples + real products); back to draft
- 2026-10-09 open question 7 resolved (Windspire, DS3000); VAWT power-curve margin 1.10; approved
- 2026-10-09 implemented, with the apps (0010, 0011) offering VAWT
