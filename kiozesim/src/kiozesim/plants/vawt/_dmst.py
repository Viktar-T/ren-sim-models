"""Darrieus Cp(TSR) by the double-multiple-streamtube method (DMST). Spec 0004, VAWT-006.

Paraschivoiu's DMST: the rotor is cut into horizontal layers; each layer into streamtubes, one per
azimuth. Each tube crosses the blade path twice and is treated as two actuator discs in a row: the
upwind half slows the free wind V∞ to V = (1 − a)·V∞ and leaves a wake Ve = (1 − 2a)·V∞, which the
downwind half slows again. In each half, the induction a balances the momentum the air loses
against the blade forces from the airfoil table.

Conventions (Paraschivoiu, *Wind Turbine Design*, 2002, ch. 4): azimuth θ in (−π/2, π/2) upwind
and its mirror π − θ downwind (same crosswind position); δ is the blade's slope from the vertical;
X = r·ω / V is the local speed ratio. Relative wind W and angle of attack α follow from
  W² = V² · ((X − sin θ)² + (cos θ · cos δ)²),   α = atan2(cos θ · cos δ, X − sin θ).
Normal and tangential force coefficients are CN = cl·cos α + cd·sin α and CT = cl·sin α − cd·cos α;
the streamwise blade force per unit blade length is ½ρW²c·(CN·cos θ·cos δ − CT·sin θ).

Thrust coefficient of a tube from momentum: 4a(1 − a) up to a = 0.4, above that Buhl's empirical
correction (Glauert's heavy-loading regime, Buhl 2005, NREL/TP-500-36834, with F = 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Literal

import numpy as np
import pandas as pd

NU_AIR = 1.46e-5  # m²/s, kinematic viscosity of air at 15 °C (spec "One curve per rotor")
N_LAYERS = 20  # layers over half the height (the rotor is symmetric about its middle)
N_TUBES = 36  # streamtubes per half revolution (5° each)
A_MAX = 0.95  # largest induction searched for
BISECT_STEPS = 25  # bisection steps: induction resolved to about 3e-8


@dataclass(frozen=True)
class Rotor:
    n_blades: int
    radius_m: float  # largest radius
    height_m: float
    chord_m: float  # at mid-height
    tip_chord_m: float  # at both ends; equal to chord_m for untapered blades
    shape: Literal["straight", "troposkien"]
    airfoil: str  # "NACA0015" ...

    @property
    def swept_area_m2(self) -> float:
        area = 2 * self.radius_m * self.height_m
        return area * 2 / 3 if self.shape == "troposkien" else area


class Polar:
    """Lift and drag of one airfoil over 0–180° at several Reynolds numbers (bundled table)."""

    def __init__(self, table: pd.DataFrame) -> None:
        self.re = np.sort(table["re"].unique()).astype(float)
        grid = np.radians(
            np.linspace(0, 180, 361)
        )  # common 0.5° grid; tables are linear between points
        cl, cd = [], []
        for re in self.re:
            block = table[table["re"] == re].sort_values("alpha_deg")
            alpha = np.radians(block["alpha_deg"].to_numpy())
            cl.append(np.interp(grid, alpha, block["cl"].to_numpy()))
            cd.append(np.interp(grid, alpha, block["cd"].to_numpy()))
        self._grid, self._cl, self._cd = grid, np.array(cl), np.array(cd)

    def coefficients(self, alpha: np.ndarray, re: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """cl and cd at angle α (rad, −π … π) and Reynolds number, linear in both.

        Symmetric airfoil: cl(−α) = −cl(α), cd(−α) = cd(α). Reynolds numbers outside the table
        use the nearest table.
        """
        a = np.abs(alpha)
        re = np.clip(re, self.re[0], self.re[-1])
        hi = np.clip(np.searchsorted(self.re, re, side="right"), 1, len(self.re) - 1)
        lo = hi - 1
        w = (re - self.re[lo]) / (self.re[hi] - self.re[lo])
        step = self._grid[1]
        i = np.clip((a / step).astype(int), 0, len(self._grid) - 2)
        f = a / step - i
        out = []
        for table in (self._cl, self._cd):
            at_lo = table[lo, i] * (1 - f) + table[lo, i + 1] * f
            at_hi = table[hi, i] * (1 - f) + table[hi, i + 1] * f
            out.append(at_lo * (1 - w) + at_hi * w)
        return np.sign(alpha) * out[0], out[1]


@cache
def polar(airfoil: str) -> Polar:
    name = airfoil.lower()
    path = files("kiozesim") / "datasheets" / "vawt" / "_data" / f"{name}.csv"
    with path.open() as f:
        return Polar(pd.read_csv(f, comment="#"))


def _momentum_ct(a: np.ndarray) -> np.ndarray:
    """Thrust coefficient of an actuator disc with induction a (Buhl's correction above 0.4)."""
    glauert = 8 / 9 + (4 - 40 / 9) * a + (50 / 9 - 4) * a**2
    return np.where(a <= 0.4, 4 * a * (1 - a), glauert)


def _half(
    rotor: Rotor,
    pol: Polar,
    lam_loc: np.ndarray,
    v_in: np.ndarray,
    v_inf: np.ndarray,
    r: np.ndarray,
    chord: np.ndarray,
    delta: np.ndarray,
    theta: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One half of the rotor: induction a, (W / V∞)² and CT per tube.

    lam_loc = r·ω / V∞ and v_in = (speed entering this half) / V∞; all arrays broadcast together.
    """
    sin, cos_n = np.sin(theta), np.cos(theta) * np.cos(delta)
    solidity = rotor.n_blades * chord / (2 * np.pi * r * np.abs(np.cos(theta)) * np.cos(delta))

    def forces(a: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        v = (1 - a) * v_in  # speed at the blade, / V∞
        tang, norm = lam_loc - v * sin, v * cos_n
        w2 = tang**2 + norm**2
        alpha = np.arctan2(norm, tang)
        cl, cd = pol.coefficients(alpha, np.sqrt(w2) * v_inf * chord / NU_AIR)
        cn = cl * np.cos(alpha) + cd * np.sin(alpha)
        ct = cl * np.sin(alpha) - cd * np.cos(alpha)
        cx = cn * np.cos(theta) * np.cos(delta) - ct * sin  # streamwise, per unit blade length
        with np.errstate(divide="ignore", invalid="ignore"):
            ct_blade = np.where(v_in > 0, solidity * w2 * cx / v_in**2, 0.0)
        return ct_blade, w2, ct

    shape = np.broadcast_shapes(lam_loc.shape, v_in.shape, theta.shape, r.shape)
    lo, hi = np.zeros(shape), np.full(shape, A_MAX)
    for _ in range(BISECT_STEPS):  # momentum − blade thrust rises with a where a root exists
        mid = (lo + hi) / 2
        below = _momentum_ct(mid) < forces(mid)[0]
        lo, hi = np.where(below, mid, lo), np.where(below, hi, mid)
    a = (lo + hi) / 2
    a = np.where(forces(np.zeros(shape))[0] <= 0, 0.0, a)  # blades push upwind: no slowing
    _, w2, ct = forces(a)
    return a, w2, ct


def cp(rotor: Rotor, tsr: np.ndarray, v_inf: np.ndarray) -> np.ndarray:
    """Power coefficient at each tip speed ratio; v_inf (m/s, one per λ) sets Reynolds numbers."""
    pol = polar(rotor.airfoil)
    R, H = rotor.radius_m, rotor.height_m
    z = (np.arange(N_LAYERS) + 0.5) / N_LAYERS * H / 2  # layer midpoints, middle to top
    dz = H / 2 / N_LAYERS
    if rotor.shape == "troposkien":
        r = R * (1 - (2 * z / H) ** 2)
        delta = np.arctan(8 * R * z / H**2)  # |dr/dz| of the parabola
    else:
        r, delta = np.full_like(z, R), np.zeros_like(z)
    chord = rotor.chord_m + (rotor.tip_chord_m - rotor.chord_m) * (2 * z / H)
    # identical layers (straight, untapered blades) are solved once and counted several times
    layers, weight = np.unique(np.stack([r, chord, delta], axis=1), axis=0, return_counts=True)
    r, chord, delta = layers.T

    lam = np.asarray(tsr, dtype=float)[:, None, None]
    vi = np.asarray(v_inf, dtype=float)[:, None, None]
    r3, c3, d3 = r[None, :, None], chord[None, :, None], delta[None, :, None]
    theta = (-np.pi / 2 + (np.arange(N_TUBES) + 0.5) * np.pi / N_TUBES)[None, None, :]
    lam_loc = lam * r3 / R

    a_up, w2_up, ct_up = _half(rotor, pol, lam_loc, np.ones_like(lam), vi, r3, c3, d3, theta)
    v_wake = np.maximum(1 - 2 * a_up, 0.0)  # the upwind disc's far wake feeds the downwind half
    _, w2_dn, ct_dn = _half(rotor, pol, lam_loc, v_wake, vi, r3, c3, d3, np.pi - theta)

    # mean power over a revolution, both halves, both (mirrored) half-heights, / (½ρ A V∞³)
    per_tube = rotor.n_blades / N_TUBES / 2 * c3 * r3 * dz / np.cos(d3) * weight[None, :, None]
    torque = (per_tube * (w2_up * ct_up + w2_dn * ct_dn)).sum(axis=(1, 2))
    return np.asarray(2 * lam[:, 0, 0] / R * torque / rotor.swept_area_m2)
