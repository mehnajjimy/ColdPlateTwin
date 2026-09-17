"""Offline liquid-water properties for 15-70 degC near atmospheric pressure.

Values are checked in so the demo never needs a network connection.  Linear
interpolation is appropriate for this screening model; unsupported mixtures and
temperatures outside the table are rejected explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# Reference ledger: IAPWS R6-95(2018), IAPWS R12-08(2008) and NIST Chemistry
# WebBook water data.  The rounded table is intended for 0.1 MPa screening, not
# custody-transfer thermodynamics.
_T_C = np.array([15.0, 20.0, 25.0, 30.0, 40.0, 50.0, 60.0, 70.0])
_RHO = np.array([999.10, 998.21, 997.05, 995.65, 992.22, 988.05, 983.20, 977.76])
_CP = np.array([4186.0, 4182.0, 4180.0, 4178.0, 4179.0, 4181.0, 4185.0, 4190.0])
_MU = np.array([1.138e-3, 1.002e-3, 0.890e-3, 0.798e-3, 0.653e-3, 0.547e-3, 0.466e-3, 0.404e-3])
_K = np.array([0.589, 0.598, 0.607, 0.615, 0.631, 0.643, 0.654, 0.663])


@dataclass(frozen=True)
class WaterProperties:
    density_kg_m3: float
    cp_j_kg_k: float
    viscosity_pa_s: float
    conductivity_w_m_k: float


def water_properties(temperature_c: float, pressure_pa: float = 101_325.0, fluid: str = "water") -> WaterProperties:
    """Interpolate pure-water properties within the declared range.

    Pressure dependence is neglected over ordinary benchtop liquid pressures.
    The function rejects mixtures so a glycol model can never be implied.
    """

    if fluid.lower() != "water":
        raise ValueError("Only pure water is supported; supply a documented mixture model separately")
    if not 15.0 <= temperature_c <= 70.0:
        raise ValueError("Water property table is valid only from 15 to 70 degC")
    if not 80_000.0 <= pressure_pa <= 500_000.0:
        raise ValueError("Water property table is limited to 0.08-0.50 MPa absolute")
    return WaterProperties(
        density_kg_m3=float(np.interp(temperature_c, _T_C, _RHO)),
        cp_j_kg_k=float(np.interp(temperature_c, _T_C, _CP)),
        viscosity_pa_s=float(np.interp(temperature_c, _T_C, _MU)),
        conductivity_w_m_k=float(np.interp(temperature_c, _T_C, _K)),
    )


def temperature_properties(temperature_c):
    """Vectorized rho, cp and d(rho)/dT of the same piecewise-linear table."""
    t = np.asarray(temperature_c, dtype=float)
    if not np.isfinite(t).all() or np.any((t < _T_C[0]) | (t > _T_C[-1])):
        raise ValueError("Water property table is valid only from 15 to 70 degC")
    segment = np.clip(np.searchsorted(_T_C, t, side="right") - 1, 0, len(_T_C) - 2)
    density_slope = np.diff(_RHO) / np.diff(_T_C)
    return np.interp(t, _T_C, _RHO), np.interp(t, _T_C, _CP), density_slope[segment]


def specific_enthalpy(temperature_c):
    """Exact integral of the linear cp table, relative to 15 degC.

    Integrate each segment as cp_left*dT + slope*dT**2/2. This uses basic
    array operations available in NumPy 1.26 as well as NumPy 2.
    """
    t = np.asarray(temperature_c, dtype=float)
    temperature_properties(t)
    widths = np.diff(_T_C)
    integral_at_knots = np.r_[0.0, np.cumsum((_CP[:-1] + _CP[1:]) * widths / 2)]
    index = np.clip(np.searchsorted(_T_C, t, side="right") - 1, 0, len(_T_C) - 2)
    offset = t - _T_C[index]
    slope = np.diff(_CP) / widths
    return integral_at_knots[index] + _CP[index] * offset + slope[index] * offset**2 / 2


def enthalpy_rise_j_kg(tin_c: float, tout_c: float) -> float:
    """Integrate cp(T)dT exactly across every table knot."""
    return float(specific_enthalpy(tout_c) - specific_enthalpy(tin_c))
