"""One time-weighted estimator used for nominal values and uncertainty draws."""

import numpy as np
from .properties import specific_enthalpy, temperature_properties

INPUT_CHANNELS = ("flow_lpm", "tin_c", "tout_c", "heater_voltage_v", "heater_current_a", "dp_pa")
METRIC_NAMES = (
    "heat_to_water_enthalpy_w", "electrical_power_synchronized_vi_w", "hydraulic_power_w",
    "delta_t_k", "unaccounted_energy_residual_w",
    "energy_closure_ratio_heat_to_water_over_electrical",
    "apparatus_resistance_roi_mean_minus_inlet_over_electrical_k_w",
    "water_normalized_resistance_roi_mean_minus_inlet_over_heat_to_water_k_w",
)


def evaluate_metrics(values, weights, roi_mean, location="inlet", errors=None):
    """Average rho(T)*flow*dh, V*I and dp*flow after row-wise calculation.

    A draw adds one common calibration error per channel to every time sample.
    Columns 6-8 contain ROI bias and relative density/enthalpy property errors.
    """
    if errors is None:
        errors = np.zeros((1, 9))
    shifted = values[None, :, :] + errors[:, None, :6]
    flow, tin, tout, voltage, current, pressure = np.moveaxis(shifted, 2, 0)
    rho, _, _ = temperature_properties(tin if location == "inlet" else tout)
    dh = specific_enthalpy(tout) - specific_enthalpy(tin)
    heat = (rho * flow / 60000 * dh) @ weights
    heat *= (1 + errors[:, 7]) * (1 + errors[:, 8])
    power = (voltage * current) @ weights
    hydraulic = (pressure * flow / 60000) @ weights
    delta_t = (tout - tin) @ weights
    numerator = roi_mean + errors[:, 6] - tin @ weights
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.column_stack((heat, power, hydraulic, delta_t, power - heat,
                                heat / power, numerator / power, numerator / heat))


def metric_jacobian(values, weights, roi_mean, location="inlet"):
    """Analytical derivatives with respect to nine shared error components."""
    flow, tin, tout, voltage, current, pressure = values.T
    rho, _, density_slope = temperature_properties(tin if location == "inlet" else tout)
    _, cp_in, _ = temperature_properties(tin)
    _, cp_out, _ = temperature_properties(tout)
    dh = specific_enthalpy(tout) - specific_enthalpy(tin)
    nominal = evaluate_metrics(values, weights, roi_mean, location)[0]
    heat, power = nominal[:2]
    d_heat, d_power, d_hydraulic, d_delta, d_numerator = np.zeros((5, 9))
    d_heat[0] = np.dot(weights, rho * dh / 60000)
    d_heat[1] = np.dot(weights, flow / 60000 * (-rho * cp_in + (density_slope * dh if location == "inlet" else 0)))
    d_heat[2] = np.dot(weights, flow / 60000 * (rho * cp_out + (density_slope * dh if location == "outlet" else 0)))
    d_heat[7:9] = heat
    d_power[3], d_power[4] = np.dot(weights, current), np.dot(weights, voltage)
    d_hydraulic[0], d_hydraulic[5] = np.dot(weights, pressure / 60000), np.dot(weights, flow / 60000)
    d_delta[1:3] = (-1, 1)
    d_numerator[1], d_numerator[6] = -1, 1
    numerator = roi_mean - np.dot(weights, tin)
    with np.errstate(divide="ignore", invalid="ignore"):
        d_closure = d_heat / power - heat * d_power / power**2
        d_electric_r = d_numerator / power - numerator * d_power / power**2
        d_water_r = d_numerator / heat - numerator * d_heat / heat**2
    return np.array([d_heat, d_power, d_hydraulic, d_delta, d_power - d_heat,
                     d_closure, d_electric_r, d_water_r])
