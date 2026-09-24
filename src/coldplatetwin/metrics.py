"""one time-weighted estimator used for nominal values and uncertainty draws."""

import numpy as np
from .properties import specific_enthalpy, temperature_properties

# --- channel and metric order ---
# the six measured channels, in the column order of the values array
INPUT_CHANNELS = ("flow_lpm", "tin_c", "tout_c", "heater_voltage_v", "heater_current_a", "dp_pa")
# the eight reported metrics, in the column order evaluate_metrics returns
METRIC_NAMES = (
    "heat_to_water_enthalpy_w", "electrical_power_synchronized_vi_w", "hydraulic_power_w",
    "delta_t_k", "unaccounted_energy_residual_w",
    "energy_closure_ratio_heat_to_water_over_electrical",
    "apparatus_resistance_roi_mean_minus_inlet_over_electrical_k_w",
    "water_normalized_resistance_roi_mean_minus_inlet_over_heat_to_water_k_w",
)

# the nine shared error components are the six channels above, then
# 6 = roi mean bias, 7 = relative density error, 8 = relative enthalpy error.
# dividing by 60000 turns l/min into m3/s.


# --- estimator ---

def evaluate_metrics(values, weights, roi_mean, location="inlet", errors=None):
    """compute every metric sample by sample, then time-average with weights.

    values has one row per sample and one column per input channel. each row
    of errors is one draw: its first six numbers shift every sample of the
    matching channel, and the last three are the roi and property errors.
    with no errors this gives the nominal metrics as a single row.
    """
    if errors is None:
        errors = np.zeros((1, 9))
    # shape (draws, samples, channels)
    shifted = values[None, :, :] + errors[:, None, :6]
    flow = shifted[:, :, 0]
    tin = shifted[:, :, 1]
    tout = shifted[:, :, 2]
    voltage = shifted[:, :, 3]
    current = shifted[:, :, 4]
    pressure = shifted[:, :, 5]

    # water heat uptake: density at the flowmeter times flow times enthalpy rise
    if location == "inlet":
        rho, _, _ = temperature_properties(tin)
    else:
        rho, _, _ = temperature_properties(tout)
    dh = specific_enthalpy(tout) - specific_enthalpy(tin)
    heat = (rho * flow / 60000 * dh) @ weights
    heat = heat * ((1 + errors[:, 7]) * (1 + errors[:, 8]))

    # electrical power, hydraulic power and temperature rise
    power = (voltage * current) @ weights
    hydraulic = (pressure * flow / 60000) @ weights
    delta_t = (tout - tin) @ weights

    # roi mean minus mean inlet temperature, shared by both resistances
    numerator = roi_mean + errors[:, 6] - tin @ weights
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.column_stack((heat, power, hydraulic, delta_t, power - heat,
                                heat / power, numerator / power, numerator / heat))


# --- analytical derivatives ---

def metric_jacobian(values, weights, roi_mean, location="inlet"):
    """derivative of each metric with respect to each of the nine errors.

    returns an array with one row per metric and one column per error.
    """
    # one column per input channel, in INPUT_CHANNELS order
    flow, tin, tout, voltage, current, pressure = values.T
    if location == "inlet":
        rho, _, density_slope = temperature_properties(tin)
    else:
        rho, _, density_slope = temperature_properties(tout)
    _, cp_in, _ = temperature_properties(tin)
    _, cp_out, _ = temperature_properties(tout)
    dh = specific_enthalpy(tout) - specific_enthalpy(tin)
    nominal = evaluate_metrics(values, weights, roi_mean, location)[0]
    heat = nominal[0]
    power = nominal[1]

    d_heat = np.zeros(9)
    d_power = np.zeros(9)
    d_hydraulic = np.zeros(9)
    d_delta = np.zeros(9)
    d_numerator = np.zeros(9)

    # heat: a temperature error also moves the density when the flowmeter sits there
    if location == "inlet":
        inlet_density_term = density_slope * dh
    else:
        inlet_density_term = 0
    if location == "outlet":
        outlet_density_term = density_slope * dh
    else:
        outlet_density_term = 0
    d_heat[0] = np.dot(weights, rho * dh / 60000)
    d_heat[1] = np.dot(weights, flow / 60000 * (-rho * cp_in + inlet_density_term))
    d_heat[2] = np.dot(weights, flow / 60000 * (rho * cp_out + outlet_density_term))
    d_heat[7] = heat
    d_heat[8] = heat

    # power = v * i and hydraulic = dp * flow
    d_power[3] = np.dot(weights, current)
    d_power[4] = np.dot(weights, voltage)
    d_hydraulic[0] = np.dot(weights, pressure / 60000)
    d_hydraulic[5] = np.dot(weights, flow / 60000)

    # delta t = tout - tin and numerator = roi mean - tin
    d_delta[1] = -1
    d_delta[2] = 1
    d_numerator[1] = -1
    d_numerator[6] = 1

    # quotient rule for the closure ratio and the two resistances
    numerator = roi_mean - np.dot(weights, tin)
    with np.errstate(divide="ignore", invalid="ignore"):
        d_closure = d_heat / power - heat * d_power / power**2
        d_electric_r = d_numerator / power - numerator * d_power / power**2
        d_water_r = d_numerator / heat - numerator * d_heat / heat**2
    return np.array([d_heat, d_power, d_hydraulic, d_delta, d_power - d_heat,
                     d_closure, d_electric_r, d_water_r])
