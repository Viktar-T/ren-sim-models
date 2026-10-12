# 0005 Biogas digester: plan

How to build [spec.md](spec.md). Written 2026-10-12.

## Design in one paragraph
The digester is the first **fuel source** (constitution 2): `kiozesim/sources/digester/digester.py`
holds `Substrate`, `DigesterParams`, `DigesterOutput` and `Digester`. No engine
library; Buswell–Boyle is a few lines of arithmetic, the feed-to-fuel step one sum over substrates
(feed is a setting, so the output is constant).

## Modules touched

| File | Change |
|---|---|
| `kiozesim/src/kiozesim/sources/__init__.py` | **new**, empty package docstring |
| `kiozesim/src/kiozesim/sources/digester/{__init__,digester}.py` | **new** |
| `kiozesim/tests/test_digester.py` | **new**: tests per BIO-001..011, plus the digester → CHP year from Acceptance |

## Models
- `Substrate(BaseModel)`, frozen, `extra="forbid"`, `allow_inf_nan=False`: fractions
  `gt=0, le=1`, `fresh_t_per_day` `ge=0`, `name` `min_length=1`. An `after` validator parses `formula` (BIO-003), error
  message starts with the substrate name. Property `yield_nm3_per_kg` (Buswell–Boyle, BIO-005).
- Formula grammar: full match of `(?:([A-Z][a-z]?)(\d+(?:\.\d+)?)?)+`; each element in
  {C, H, O, N, S}, at most once, count > 0, C and H present; methane per unit > 0.
- `DigesterParams`: `name` (`min_length=1`), `substrates: tuple[Substrate, ...]` (`min_length=1`),
  unique names validator.
- `DigesterOutput(TimeSeries)`: `fuel_kw`, `methane_nm3_per_h`.
- `Digester(params).simulate(index)`: checks the index (BIO-004), then a constant
  `Σ fresh_t_per_day × 1000 × dm × organic × bio × yield / 24` Nm³/h on it.

## Constants
`NM3_PER_MOL = 0.022414`, `CH4_KWH_PER_NM3 = 9.97`, molar masses C 12.011, H 1.008, O 15.999,
N 14.007, S 32.06 (spec Domain notes).
