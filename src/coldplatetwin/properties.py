"""water properties from 15 to 70 degc near atmospheric pressure, from a checked-in table.

linear interpolation is enough for this screening model. other fluids and
temperatures outside the table are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# --- water property table ---
# rounded values from iapws r6-95(2018), iapws r12-08(2008) and the nist
# chemistry webbook. good for 0.1 mpa screening, not custody-transfer work.
_T_C = np.array([15.0, 20.0, 25.0, 30.0, 40.0, 50.0, 60.0, 70.0])
_RHO = np.array([999.10, 998.21, 997.05, 995.65, 992.22, 988.05, 983.20, 977.76])
_CP = np.array([4186.0, 4182.0, 4180.0, 4178.0, 4179.0, 4181.0, 4185.0, 4190.0])
_MU = np.array([1.138e-3, 1.002e-3, 0.890e-3, 0.798e-3, 0.653e-3, 0.547e-3, 0.466e-3, 0.404e-3])
_K = np.array([0.589, 0.598, 0.607, 0.615, 0.631, 0.643, 0.654, 0.663])


# --- single-point lookup ---

@dataclass(frozen=True)
class WaterProperties:
    """water properties at one temperature, in si units."""

    density_kg_m3: float
    cp_j_kg_k: float
    viscosity_pa_s: float
    conductivity_w_m_k: float


def water_properties(temperature_c: float, pressure_pa: float = 101_325.0, fluid: str = "water") -> WaterProperties:
    """interpolate pure-water properties at one temperature.

    pressure only has to be in range, it does not change the values.
    mixtures such as glycol are rejected on purpose.
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


# --- array lookups used by the calorimetry ---

def temperature_properties(temperature_c):
    """return density, cp and d(density)/dT for an array of temperatures."""
    t = np.asarray(temperature_c, dtype=float)
    if not np.isfinite(t).all() or np.any((t < _T_C[0]) | (t > _T_C[-1])):
        raise ValueError("Water property table is valid only from 15 to 70 degC")
    # index of the table segment each temperature falls in (70 degC uses the last one)
    segment = np.searchsorted(_T_C, t, side="right") - 1
    segment = np.clip(segment, 0, len(_T_C) - 2)
    density_slope = np.diff(_RHO) / np.diff(_T_C)
    density = np.interp(t, _T_C, _RHO)
    cp = np.interp(t, _T_C, _CP)
    return density, cp, density_slope[segment]


def specific_enthalpy(temperature_c):
    """specific enthalpy in j/kg relative to 15 degC.

    cp is linear on each table segment, so each segment integrates exactly to
    cp_left * dT + slope * dT**2 / 2. plain array maths keeps this working on
    numpy 1.26 and numpy 2.
    """
    t = np.asarray(temperature_c, dtype=float)
    # called only for its range check
    temperature_properties(t)
    widths = np.diff(_T_C)
    # enthalpy at each table knot, using the trapezoid rule on the linear cp
    segment_integrals = (_CP[:-1] + _CP[1:]) * widths / 2
    integral_at_knots = np.concatenate(([0.0], np.cumsum(segment_integrals)))
    # then add the part of the segment between the knot and t
    index = np.searchsorted(_T_C, t, side="right") - 1
    index = np.clip(index, 0, len(_T_C) - 2)
    offset = t - _T_C[index]
    slope = np.diff(_CP) / widths
    return integral_at_knots[index] + _CP[index] * offset + slope[index] * offset**2 / 2


def enthalpy_rise_j_kg(tin_c: float, tout_c: float) -> float:
    """enthalpy gained by water heated from tin_c to tout_c, in j/kg."""
    return float(specific_enthalpy(tout_c) - specific_enthalpy(tin_c))
