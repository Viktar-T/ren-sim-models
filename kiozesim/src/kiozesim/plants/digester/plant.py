"""Biogas digester: steady feed in, methane out, as fuel for a combustion plant. Specs 0005, 0019.

I/O contract (a plant without input, CORE-004)
  input : none; the feed (t/day per substrate) is a setting
  output: DigesterOutput, single values: fuel_kw (methane energy, lower heating value),
          methane_nm3_per_h and power_kw 0 (it makes no electricity). `fuel_kw` flows on to a
          combustion plant in a chain (spec 0019).
Steady feeding: the output is the same on every time step. Ignores requests within a step (the
bacteria take weeks to react); sizing (`needs`) scales the feed on averages.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kiozesim.plants.base import Plant, PlantOutput, PlantParams, Sizing

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


class DigesterParams(PlantParams):
    name: str = Field(min_length=1)
    substrates: tuple[Substrate, ...] = Field(
        min_length=1,
        examples=[
            [
                {
                    "name": "maize silage",
                    "fresh_t_per_day": 40,
                    "dry_matter_frac": 0.33,
                    "organic_frac": 0.95,
                    "formula": "C6H10O5",
                    "biodegradability": 0.8,
                }
            ]
        ],
    )

    @field_validator("substrates")
    @classmethod
    def _unique_names(cls, v: tuple[Substrate, ...]) -> tuple[Substrate, ...]:
        names = [s.name for s in v]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"substrate names must be unique: {', '.join(dupes)}")
        return v


class DigesterOutput(PlantOutput):
    fuel_kw: float  # methane energy made, kW, lower heating value
    methane_nm3_per_h: float


class DigesterPlant(Plant[DigesterParams, None, DigesterOutput]):
    """Steady feed -> constant methane, as fuel for a combustion plant."""

    params_model = DigesterParams
    output_model = DigesterOutput
    askable = ("fuel_kw",)

    def _simulate(self, ts: None) -> DigesterOutput:
        subs = self.params.substrates
        nm3_per_h = sum(s.fresh_t_per_day * s.methane_nm3_per_t for s in subs) / 24
        return DigesterOutput(
            power_kw=0.0, fuel_kw=nm3_per_h * CH4_KWH_PER_NM3, methane_nm3_per_h=nm3_per_h
        )

    def needs(self, wanted: Mapping[str, float]) -> Sizing:
        """The feed giving `fuel_kw` on average: all substrates scaled alike (CHAIN-023)."""
        self.check_asked(wanted)
        made = self._simulate(None).fuel_kw
        want = max(0.0, wanted.get("fuel_kw", 0.0))
        if made == 0 and want > 0:
            raise ValueError(f"{self.name}: its feed makes no gas, so there is nothing to scale")
        factor = want / made if made > 0 else 0.0
        feed = {s.name: s.fresh_t_per_day * factor for s in self.params.substrates}
        return Sizing({}, {"fuel_kw": want}, feed)
