"""Vertical-axis wind turbine: from rotor geometry (Cp(TSR) curve) or a power curve. Spec 0004.

I/O contract
  input : VAWTInputs (TimeSeries, one shared index, period averages labelled at period start):
          wind_speed_m_s, optionally temp_air_c + pressure_hpa (needed for density correction)
  output: VAWTOutput, power_kw (all turbines, after losses) plus wind_speed_hub_m_s,
          air_density_kg_m3, and for `geometry` rotors tsr and cp, on the input index.
Datasheet: YAML in kiozesim/datasheets/vawt/, loaded via VAWTDatasheet.bundled(name).
"""

from __future__ import annotations

from typing import Literal, Self

import numpy as np
import pandas as pd
from pydantic import ConfigDict, Field, model_validator

from kiozesim.datasheet import Datasheet
from kiozesim.plants.base import Plant, PlantOutput, PlantParams, TimeSeries
from kiozesim.plants.vawt._air import RHO_STD, density_at_hub, wind_at_hub
from kiozesim.timegrid import TimeGridError

MAX_STEP = pd.Timedelta(hours=1)
BETZ = 16 / 27  # the most any rotor can take from the wind
TSR_GRID = np.round(
    np.arange(0.1, 15.0 + 1e-9, 0.05), 2
)  # λ values a Darrieus curve is computed at
CURVE_MARGIN = (
    1.10  # measured small-turbine curves overshoot nameplate (Windspire: 1.09 kW at 1 kW)
)

Airfoil = Literal["NACA0015", "NACA0018", "NACA0021"]

# Fields each method, rotor family and speed control needs; other optional fields must be absent.
POWER_CURVE_FIELDS = {"wind_speed_m_s", "power_kw"}
GEOMETRY_FIELDS = {"cut_in_m_s", "cut_out_m_s", "drivetrain_efficiency_pct", "control"}
DARRIEUS_FIELDS = {"n_blades", "chord_m", "airfoil", "blade_shape"}
SAVONIUS_FIELDS = {"n_buckets"}
CONTROL_FIELDS = {"fixed_rpm": {"rpm"}, "optimal_tsr": {"rated_wind_speed_m_s"}}
OPTIONAL_FIELDS = (
    POWER_CURVE_FIELDS
    | GEOMETRY_FIELDS
    | DARRIEUS_FIELDS
    | SAVONIUS_FIELDS
    | {"tip_chord_m"}
    | {f for fs in CONTROL_FIELDS.values() for f in fs}
)


class VAWTDatasheet(Datasheet):
    shelf = "vawt"

    model_config = ConfigDict(allow_inf_nan=False)

    method: Literal["geometry", "power_curve"]
    rotor_type: Literal["darrieus", "savonius"]
    rotor_diameter_m: float = Field(gt=0)
    rotor_height_m: float = Field(gt=0)
    rated_power_kw: float = Field(gt=0)
    # power_curve
    wind_speed_m_s: list[float] | None = None  # at hub height
    power_kw: list[float] | None = None
    # geometry
    cut_in_m_s: float | None = Field(default=None, ge=0)
    cut_out_m_s: float | None = Field(default=None, gt=0)
    drivetrain_efficiency_pct: float | None = Field(default=None, gt=0, le=100)
    control: Literal["fixed_rpm", "optimal_tsr"] | None = None
    rpm: float | None = Field(default=None, gt=0)
    rated_wind_speed_m_s: float | None = Field(default=None, gt=0)
    # geometry, Darrieus
    n_blades: int | None = Field(default=None, ge=1, le=6)
    chord_m: float | None = Field(default=None, gt=0)  # at mid-height
    tip_chord_m: float | None = Field(default=None, gt=0)  # at both ends; tapered blades only
    airfoil: Airfoil | None = None
    blade_shape: Literal["straight", "troposkien"] | None = None
    # geometry, Savonius
    n_buckets: Literal[2] | None = None

    @model_validator(mode="after")
    def _check_fields(self) -> Self:
        if self.method == "power_curve":
            needed = set(POWER_CURVE_FIELDS)
        else:
            needed = GEOMETRY_FIELDS | (
                DARRIEUS_FIELDS if self.rotor_type == "darrieus" else SAVONIUS_FIELDS
            )
            if self.control is not None:
                needed |= CONTROL_FIELDS[self.control]
            if self.rotor_type == "darrieus" and self.tip_chord_m is not None:
                needed.add("tip_chord_m")  # optional
        given = {f for f in OPTIONAL_FIELDS if getattr(self, f) is not None}
        if missing := sorted(needed - given):
            raise ValueError(f"{self.method} {self.rotor_type} datasheet needs {missing}")
        if extra := sorted(given - needed):
            raise ValueError(f"{self.method} {self.rotor_type} datasheet must not have {extra}")
        if self.method == "power_curve":
            self._check_curve()
        else:
            self._check_speeds()
        return self

    def _check_curve(self) -> None:
        v, p = np.asarray(self.wind_speed_m_s), np.asarray(self.power_kw)
        if len(v) != len(p):
            raise ValueError("wind_speed_m_s and power_kw must have the same length")
        if len(v) < 2:
            raise ValueError("the power curve needs at least 2 points")
        if (v < 0).any() or (np.diff(v) <= 0).any():
            raise ValueError("wind_speed_m_s must be >= 0 and strictly increasing")
        if (p < 0).any() or (p > CURVE_MARGIN * self.rated_power_kw).any():
            raise ValueError(f"power_kw must lie within 0 ... {CURVE_MARGIN} x rated_power_kw")

    def _check_speeds(self) -> None:
        assert self.cut_in_m_s is not None and self.cut_out_m_s is not None  # by _check_fields
        if self.cut_out_m_s <= self.cut_in_m_s:
            raise ValueError("cut_out_m_s must be above cut_in_m_s")
        v = self.rated_wind_speed_m_s
        if v is not None and not self.cut_in_m_s < v < self.cut_out_m_s:
            raise ValueError("rated_wind_speed_m_s must lie between cut_in_m_s and cut_out_m_s")


class VAWTParams(PlantParams):
    model_config = ConfigDict(allow_inf_nan=False)

    datasheet: VAWTDatasheet
    hub_height_m: float = Field(gt=0)
    n_turbines: int = Field(default=1, ge=1)
    wind_height_m: float = Field(default=10.0, gt=0)  # where the input wind was measured
    roughness_length_m: float = Field(default=0.1, gt=0)
    temp_height_m: float = Field(default=2.0, gt=0)  # where the input temperature was measured
    density_correction: bool = True
    losses_pct: float = Field(default=10.0, ge=0, lt=100)

    @model_validator(mode="after")
    def _check_heights(self) -> Self:
        if self.hub_height_m <= self.datasheet.rotor_height_m / 2:
            raise ValueError("hub_height_m must be above half of rotor_height_m")
        if self.roughness_length_m >= self.wind_height_m:
            raise ValueError("wind_height_m must be above roughness_length_m")
        if self.roughness_length_m >= self.hub_height_m:
            raise ValueError("hub_height_m must be above roughness_length_m")
        return self


class VAWTInputs(TimeSeries):
    wind_speed_m_s: pd.Series  # at wind_height_m
    temp_air_c: pd.Series | None = None  # at temp_height_m; needed for density correction
    pressure_hpa: pd.Series | None = None  # surface pressure at ground level; same

    @model_validator(mode="after")
    def _check_values(self) -> Self:
        for name, s in self:
            if not isinstance(s, pd.Series):
                continue
            values = s.to_numpy(dtype=float)
            if not np.isfinite(values).all():
                raise ValueError(f"{name}: contains non-finite values")
            if name == "wind_speed_m_s" and (values < 0).any():
                raise ValueError(f"{name}: contains negative values")
            if name == "pressure_hpa" and (values <= 0).any():
                raise ValueError(f"{name}: must be positive")
        return self


class VAWTOutput(PlantOutput):
    wind_speed_hub_m_s: pd.Series
    air_density_kg_m3: pd.Series  # 1.225 throughout without density correction
    tsr: pd.Series | None = None  # geometry only
    cp: pd.Series | None = None  # geometry only


class VAWTPlant(Plant[VAWTParams, VAWTInputs, VAWTOutput]):
    params_model = VAWTParams
    inputs_model = VAWTInputs
    output_model = VAWTOutput

    def __init__(self, params: VAWTParams) -> None:
        super().__init__(params)
        self._curve: pd.DataFrame | None = None

    def cp_curve(self) -> pd.DataFrame | None:
        """The rotor's Cp(TSR) curve (columns tsr, cp); None for power-curve datasheets."""
        if self.params.datasheet.method == "power_curve":
            return None
        if self._curve is None:
            self._curve = self._build_curve()
        return self._curve.copy()

    def _build_curve(self) -> pd.DataFrame:
        ds = self.params.datasheet
        if ds.rotor_type == "savonius":
            from kiozesim.plants.vawt import _savonius

            assert ds.n_buckets is not None
            curve = _savonius.curve(ds.n_buckets)
        else:
            curve = self._darrieus_curve()
        cp = curve["cp"].to_numpy()
        if (cp < 0).any() or (cp >= BETZ).any():
            raise ValueError(f"{self.name}: Cp curve outside 0 ... Betz limit {BETZ:.3f}")
        return curve

    def _darrieus_curve(self) -> pd.DataFrame:
        """DMST over TSR_GRID, trimmed to the unbroken positive stretch around the best Cp."""
        from kiozesim.plants.vawt import _dmst

        ds = self.params.datasheet
        assert ds.n_blades and ds.chord_m and ds.airfoil and ds.blade_shape
        radius = ds.rotor_diameter_m / 2
        rotor = _dmst.Rotor(
            n_blades=ds.n_blades,
            radius_m=radius,
            height_m=ds.rotor_height_m,
            chord_m=ds.chord_m,
            tip_chord_m=ds.tip_chord_m if ds.tip_chord_m is not None else ds.chord_m,
            shape=ds.blade_shape,
            airfoil=ds.airfoil,
        )
        if ds.control == "fixed_rpm":  # each λ happens at one wind speed: v = ω·R / λ
            assert ds.rpm is not None
            v_inf = ds.rpm * 2 * np.pi / 60 * radius / TSR_GRID
        else:
            assert ds.rated_wind_speed_m_s is not None
            v_inf = np.full_like(TSR_GRID, ds.rated_wind_speed_m_s)
        cp = _dmst.cp(rotor, TSR_GRID, v_inf)
        best = int(np.argmax(cp))
        if cp[best] <= 0:
            raise ValueError(f"{self.name}: this rotor makes no power at any tip speed ratio")
        lo, hi = best, best
        while lo > 0 and cp[lo - 1] > 0:
            lo -= 1
        while hi < len(cp) - 1 and cp[hi + 1] > 0:
            hi += 1
        return pd.DataFrame({"tsr": TSR_GRID[lo : hi + 1], "cp": cp[lo : hi + 1]})

    def swept_area_m2(self) -> float:
        """Rotor silhouette seen from the wind; a troposkien's parabolic outline covers 2/3."""
        ds = self.params.datasheet
        area = ds.rotor_diameter_m * ds.rotor_height_m
        return area * 2 / 3 if ds.blade_shape == "troposkien" else area

    def _simulate(self, ts: VAWTInputs) -> VAWTOutput:
        p = self.params
        step = ts.index[1] - ts.index[0]
        if step > MAX_STEP:
            raise TimeGridError(f"{self.name}: VAWT needs a time step of at most 1 h, got {step}")
        if p.density_correction:
            for field in ("temp_air_c", "pressure_hpa"):
                if getattr(ts, field) is None:
                    raise ValueError(
                        f"{self.name}: density correction needs {field}"
                        " (or set density_correction: false)"
                    )
        v_hub = wind_at_hub(
            ts.wind_speed_m_s, p.wind_height_m, p.hub_height_m, p.roughness_length_m
        )
        if p.density_correction:
            assert ts.temp_air_c is not None and ts.pressure_hpa is not None
            rho = density_at_hub(ts.temp_air_c, p.temp_height_m, ts.pressure_hpa, p.hub_height_m)
        else:
            rho = pd.Series(RHO_STD, index=ts.index, dtype=float)
        if p.datasheet.method == "power_curve":
            turbine_kw = self._power_curve_kw(v_hub, rho)
            tsr = cp = None
        else:
            turbine_kw, tsr, cp = self._geometry_kw(v_hub, rho)
        power_kw = p.n_turbines * turbine_kw * (1 - p.losses_pct / 100)
        return VAWTOutput(
            power_kw=power_kw,
            wind_speed_hub_m_s=v_hub.rename("wind_speed_hub_m_s"),
            air_density_kg_m3=rho.rename("air_density_kg_m3"),
            tsr=tsr,
            cp=cp,
        )

    def _geometry_kw(
        self, v_hub: pd.Series, rho: pd.Series
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """One turbine from its Cp(TSR) curve (Formula section). Returns kW, λ and Cp."""
        ds = self.params.datasheet
        assert ds.cut_in_m_s is not None and ds.cut_out_m_s is not None
        assert ds.drivetrain_efficiency_pct is not None
        curve = self.cp_curve()
        assert curve is not None
        tsrs, cps = curve["tsr"].to_numpy(), curve["cp"].to_numpy()
        v = v_hub.to_numpy(dtype=float)
        if ds.control == "fixed_rpm":
            assert ds.rpm is not None
            tip_m_s = ds.rpm * 2 * np.pi / 60 * ds.rotor_diameter_m / 2
            with np.errstate(divide="ignore"):
                lam = np.where(v > 0, tip_m_s / np.where(v > 0, v, 1.0), 0.0)  # 0 in still air
        else:
            lam = np.full_like(v, tsrs[np.argmax(cps)])
        cp = np.interp(lam, tsrs, cps)
        cp[(lam < tsrs[0]) | (lam > tsrs[-1])] = 0.0
        rotor_kw = cp * 0.5 * rho.to_numpy(dtype=float) * self.swept_area_m2() * v**3 / 1000
        kw = np.minimum(rotor_kw * ds.drivetrain_efficiency_pct / 100, ds.rated_power_kw)
        kw[(v < ds.cut_in_m_s) | (v > ds.cut_out_m_s)] = 0.0
        index = v_hub.index
        return (
            pd.Series(kw, index=index),
            pd.Series(lam, index=index, name="tsr"),
            pd.Series(cp, index=index, name="cp"),
        )

    def _power_curve_kw(self, v_hub: pd.Series, rho: pd.Series) -> pd.Series:
        """One turbine: the table at v_hub, 0 outside it, scaled by ρ/1.225, capped at its max."""
        ds = self.params.datasheet
        assert ds.wind_speed_m_s is not None and ds.power_kw is not None
        speeds, powers = np.asarray(ds.wind_speed_m_s), np.asarray(ds.power_kw)
        v = v_hub.to_numpy(dtype=float)
        kw = np.interp(v, speeds, powers)
        kw[(v < speeds[0]) | (v > speeds[-1])] = 0.0
        kw = np.minimum(kw * rho.to_numpy(dtype=float) / RHO_STD, powers.max())
        return pd.Series(kw, index=v_hub.index)
