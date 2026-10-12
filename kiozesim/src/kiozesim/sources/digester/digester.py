"""Biogas digester: steady feed in, methane out, as fuel for a gas engine. Spec 0005.

I/O contract
  input : only the time axis to fill; the feed (t/day per substrate) is a setting
  output: DigesterOutput (TimeSeries): fuel_kw (methane energy, lower heating value) and
          methane_nm3_per_h on that axis; `fuel_kw` is the gas engine's input (spec 0015).
Steady feeding: the output is the same on every step.
"""

from __future__ import annotations

import re
from typing import Self

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kiozesim.plants.base import TimeSeries
from kiozesim.timegrid import validate_time_index

NM3_PER_MOL = 0.022414  # ideal gas at 0 degC, 1.01325 bar
CH4_KWH_PER_NM3 = 9.97  # methane lower heating value, DIN EN ISO 6976
MOLAR_MASS_G = {"C": 12.011, "H": 1.008, "O": 15.999, "N": 14.007, "S": 32.06}
# mol CH4 per atom in the formula unit (Buswell-Boyle): a/2 + b/8 - c/4 - 3d/8 - e/4
CH4_PER_ATOM = {"C": 1 / 2, "H": 1 / 8, "O": -1 / 4, "N": -3 / 8, "S": -1 / 4}

_FORMULA = re.compile(r"(?:[A-Z][a-z]?(?:\d+(?:\.\d+)?)?)+")
_ELEMENT = re.compile(r"([A-Z][a-z]?)(\d+(?:\.\d+)?)?")


def _parse(formula: str) -> dict[str, float]:
    if not _FORMULA.fullmatch(formula):
        raise ValueError(f"formula {formula!r} is not like C6H10O5")
    counts: dict[str, float] = {}
    for element, count in _ELEMENT.findall(formula):
        if element not in MOLAR_MASS_G:
            raise ValueError(f"formula {formula!r}: element {element} not one of C, H, O, N, S")
        if element in counts:
            raise ValueError(f"formula {formula!r}: {element} given twice")
        n = float(count) if count else 1.0
        if n <= 0:
            raise ValueError(f"formula {formula!r}: count of {element} must be positive")
        counts[element] = n
    if not {"C", "H"} <= counts.keys():
        raise ValueError(f"formula {formula!r} needs C and H")
    if sum(CH4_PER_ATOM[e] * n for e, n in counts.items()) <= 0:
        raise ValueError(f"formula {formula!r} gives no methane")
    return counts


class Substrate(BaseModel):
    """One kind of feed: its make-up and how much of it the bacteria digest."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    name: str = Field(min_length=1)
    fresh_t_per_day: float = Field(ge=0)  # fresh mass fed per day
    dry_matter_frac: float = Field(gt=0, le=1)  # dry matter / fresh mass
    organic_frac: float = Field(gt=0, le=1)  # organic dry matter / dry matter
    formula: str  # average formula of the organic matter, e.g. C6H10O5
    biodegradability: float = Field(gt=0, le=1)  # fraction of organic matter digested

    @model_validator(mode="after")
    def _check_formula(self) -> Self:
        try:
            _parse(self.formula)
        except ValueError as e:
            raise ValueError(f"substrate {self.name!r}: {e}") from None
        return self

    @property
    def yield_nm3_per_kg(self) -> float:
        """Maximum methane per kg organic dry matter, Buswell-Boyle."""
        counts = _parse(self.formula)
        mol_ch4 = sum(CH4_PER_ATOM[e] * n for e, n in counts.items())
        molar_mass = sum(MOLAR_MASS_G[e] * n for e, n in counts.items())
        return mol_ch4 * NM3_PER_MOL * 1000 / molar_mass

    @property
    def methane_nm3_per_t(self) -> float:
        """Methane actually made per tonne of fresh mass fed."""
        organic_kg = 1000 * self.dry_matter_frac * self.organic_frac * self.biodegradability
        return organic_kg * self.yield_nm3_per_kg


class DigesterParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    substrates: tuple[Substrate, ...] = Field(min_length=1)

    @field_validator("substrates")
    @classmethod
    def _unique_names(cls, v: tuple[Substrate, ...]) -> tuple[Substrate, ...]:
        names = [s.name for s in v]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"substrate names must be unique: {', '.join(dupes)}")
        return v


class DigesterOutput(TimeSeries):
    fuel_kw: pd.Series  # methane energy flow, kW (lower heating value)
    methane_nm3_per_h: pd.Series


class Digester:
    """A fuel source (constitution 2): pure function of (params, time axis) -> methane."""

    def __init__(self, params: DigesterParams) -> None:
        self.params = params

    @property
    def name(self) -> str:
        return self.params.name

    def simulate(self, index: pd.DatetimeIndex) -> DigesterOutput:
        validate_time_index(index)
        subs = self.params.substrates
        nm3_per_h = sum(s.fresh_t_per_day * s.methane_nm3_per_t for s in subs) / 24
        methane = pd.Series(float(nm3_per_h), index=index, name="methane_nm3_per_h")
        return DigesterOutput(
            fuel_kw=(methane * CH4_KWH_PER_NM3).rename("fuel_kw"), methane_nm3_per_h=methane
        )
