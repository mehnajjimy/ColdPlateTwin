"""analytical and seeded monte carlo uncertainty propagation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from .metrics import INPUT_CHANNELS, METRIC_NAMES, evaluate_metrics, metric_jacobian


# --- simple bench-level inputs ---

@dataclass(frozen=True)
class UncertaintyInputs:
    """standard uncertainties for the simple propagate_metrics check."""

    flow_standard_lpm: float = 0.005
    tin_standard_k: float = 0.05
    tout_standard_k: float = 0.05
    rtd_correlation: float = 0.65
    voltage_standard_v: float = 0.02
    current_standard_a: float = 0.01
    pressure_standard_pa: float = 25.0
    density_standard_kg_m3: float = 0.3
    cp_standard_j_kg_k: float = 3.0


def standard_uncertainty(value: float, distribution: str, stated_bound: float | None = None) -> float:
    """turn an uncertainty statement into one standard uncertainty.

    a normal or standard value is used as is. a rectangular bound b becomes
    b / sqrt(3).
    """
    if distribution in {"standard", "normal"}:
        return float(value)
    if distribution == "rectangular":
        if stated_bound is None:
            bound = value
        else:
            bound = stated_bound
        return float(bound / np.sqrt(3.0))
    raise ValueError(f"Unsupported uncertainty distribution: {distribution}")


# --- full experiment propagation ---

def propagate_experiment(values, weights, roi_mean, metadata, config):
    """propagate the run's recorded sensor uncertainties into every metric.

    there are no sensor defaults: a missing sensor record makes the whole
    result unavailable. each sensor uncertainty is treated as one calibration
    error shared by every sample of the run (and by other runs with the same
    calibration_id), so averaging more samples does not shrink it.
    returns (result dict keyed by metric name, list of warnings).
    """
    metadata.validate()
    sensors = {sensor.channel: sensor for sensor in metadata.sensors}
    missing = [name for name in INPUT_CHANNELS if name not in sensors]
    if missing:
        return {}, ["Uncertainty unavailable: missing sensor specifications for " + ", ".join(missing)]

    # standard uncertainty, label and distribution for each of the nine errors.
    # 0-5 are the sensors, 6 is the camera roi mean, 7-8 are the water table.
    standard = np.zeros(9)
    labels = []
    distributions = []
    for i, name in enumerate(INPUT_CHANNELS):
        sensor = sensors[name]
        standard[i] = standard_uncertainty(sensor.standard_uncertainty, sensor.distribution, sensor.stated_bound)
        labels.append(sensor.calibration_id + ":" + name)
        distributions.append(sensor.distribution)
    if metadata.camera:
        camera_u = metadata.camera.absolute_accuracy_standard_uncertainty_k
        camera_id = metadata.camera.calibration_id
    else:
        camera_u = None
        camera_id = "missing"
    if camera_u is not None:
        standard[6] = camera_u
    else:
        standard[6] = 0
    labels.append(camera_id + ":roi_mean_c")
    distributions.append("normal")
    standard[7] = config.density_relative_standard
    standard[8] = config.enthalpy_relative_standard
    labels.append("water-table-v1:density_relative")
    labels.append("water-table-v1:enthalpy_relative")
    distributions.append("normal")
    distributions.append("normal")

    # covariance from the declared sensor pair correlations
    correlation = np.eye(9)
    correlation_records = {}
    for record in metadata.calibration_correlations:
        if record.channel_a in INPUT_CHANNELS and record.channel_b in INPUT_CHANNELS:
            i = INPUT_CHANNELS.index(record.channel_a)
            j = INPUT_CHANNELS.index(record.channel_b)
            correlation[i, j] = record.correlation
            correlation[j, i] = record.correlation
            pair_key = "|".join(sorted((labels[i], labels[j])))
            correlation_records[pair_key] = record.correlation
    covariance = correlation * np.outer(standard, standard)

    # analytical: variance = J C J^T, one value per metric
    if roi_mean is None:
        roi_value = 0.0
    else:
        roi_value = roi_mean
    location = metadata.flow_measurement_location
    nominal = evaluate_metrics(values, weights, roi_value, location)[0]
    jacobian = metric_jacobian(values, weights, roi_value, location)
    with np.errstate(invalid="ignore"):
        variance = np.einsum("ij,jk,ik->i", jacobian, covariance, jacobian)

    # monte carlo: seeded normal draws, with rectangular channels redrawn uniformly
    rng = np.random.default_rng(config.seed)
    errors = rng.multivariate_normal(np.zeros(9), covariance, size=config.monte_carlo_samples)
    for i, distribution in enumerate(distributions):
        if distribution == "rectangular":
            half_width = np.sqrt(3) * standard[i]
            errors[:, i] = rng.uniform(-half_width, half_width, len(errors))

    # do not extrapolate the water table when large uncertainty leaves its range
    valid = np.ones(len(errors), dtype=bool)
    for i in (1, 2):
        lowest = values[:, i].min() + errors[:, i]
        highest = values[:, i].max() + errors[:, i]
        valid &= (lowest >= 15) & (highest <= 70)
    lowest_flow = values[:, 0].min() + errors[:, 0]
    valid &= lowest_flow > 0

    # evaluate the accepted draws in chunks of 128 to limit memory
    chunk_size = 128
    draws = []
    for offset in range(0, len(errors), chunk_size):
        chunk = errors[offset:offset + chunk_size]
        accepted = chunk[valid[offset:offset + chunk_size]]
        if len(accepted):
            draws.append(evaluate_metrics(values, weights, roi_value, location, accepted))
    if draws:
        samples = np.vstack(draws)
    else:
        samples = np.empty((0, len(METRIC_NAMES)))

    warnings = []
    if not valid.all():
        warnings.append("Monte Carlo leaves the property/positive-flow domain; its standard uncertainty is withheld.")
    if roi_mean is not None and camera_u is None:
        warnings.append("Thermal-resistance uncertainty unavailable: camera absolute accuracy is missing.")

    # one record per metric. the two resistances (6, 7) are skipped without an roi.
    result = {}
    for i, name in enumerate(METRIC_NAMES):
        if i >= 6 and roi_mean is None:
            continue
        # ratios (5, 6, 7) are withheld when their denominator is within
        # max(1, 3 standard uncertainties) of zero. 5 and 6 divide by power, 7 by heat.
        weak_denominator = False
        if i >= 5:
            if i in (5, 6):
                denominator_index = 1
            else:
                denominator_index = 0
            denominator_u = np.sqrt(max(0, variance[denominator_index]))
            weak_denominator = abs(nominal[denominator_index]) <= max(1.0, 3*denominator_u)
        # the resistances also need the camera's absolute accuracy
        unavailable = weak_denominator or (i >= 6 and camera_u is None)

        if unavailable or not np.isfinite(variance[i]):
            u = None
        else:
            u = float(np.sqrt(max(0, variance[i])))
        mc = None
        if u is not None and valid.all() and len(samples) > 1 and np.isfinite(samples[:, i]).all():
            mc = float(np.std(samples[:, i], ddof=1))
        if np.isfinite(nominal[i]) and not weak_denominator:
            value = float(nominal[i])
        else:
            value = None
        if u is not None:
            effects = dict(zip(labels, (jacobian[i] * standard).tolist()))
        else:
            effects = {}
        if unavailable:
            status = "unavailable_or_weak_denominator"
        else:
            status = "available"
        result[name] = {
            "value": value,
            "analytical_standard": u,
            "monte_carlo_standard": mc,
            "status": status,
            "monte_carlo_valid_fraction": float(valid.mean()),
            "shared_standard_effects": effects,
            "shared_correlations": correlation_records,
            "uncertainty_basis": "run-constant additive calibration errors in calibrated units; no sample-count reduction",
        }
    return result, warnings


# --- comparing two runs ---

def difference_standard_uncertainty(first: dict, second: dict) -> float | None:
    """standard uncertainty of a - b for two metric records.

    errors with the same calibration id and channel label are shared by both
    runs, so they partly cancel in the difference.
    """
    if first["analytical_standard"] is None or second["analytical_standard"] is None:
        return None
    a = first["shared_standard_effects"]
    b = second["shared_standard_effects"]
    correlations = first["shared_correlations"] | second["shared_correlations"]
    shared_pairs = first["shared_correlations"].keys() & second["shared_correlations"].keys()
    for pair in shared_pairs:
        if first["shared_correlations"][pair] != second["shared_correlations"][pair]:
            raise ValueError("Inconsistent shared calibration correlation between runs")
    # same error label in both runs
    cross_covariance = sum(a.get(key, 0) * b.get(key, 0) for key in a.keys() | b.keys())
    # correlated pairs of labels across the two runs
    for pair, rho in correlations.items():
        left, right = pair.split("|")
        cross_covariance += rho * (a.get(left, 0)*b.get(right, 0) + a.get(right, 0)*b.get(left, 0))
    variance = first["analytical_standard"]**2 + second["analytical_standard"]**2 - 2*cross_covariance
    return float(np.sqrt(max(0, variance)))


# --- simple bench-level check ---

def delta_t_standard(inputs: UncertaintyInputs) -> float:
    """u(tout - tin), keeping the covariance of a paired rtd calibration."""
    covariance = inputs.rtd_correlation * inputs.tin_standard_k * inputs.tout_standard_k
    variance = inputs.tout_standard_k**2 + inputs.tin_standard_k**2 - 2.0 * covariance
    if variance < 0:
        raise ValueError("RTD covariance produces negative variance")
    return float(np.sqrt(variance))


def propagate_metrics(
    flow_lpm: float,
    density: float,
    cp: float,
    delta_t_k: float,
    voltage_v: float,
    current_a: float,
    pressure_pa: float,
    inputs: UncertaintyInputs = UncertaintyInputs(),
    seed: int = 20260917,
    samples: int = 20_000,
) -> dict[str, dict[str, float]]:
    """uncertainty of heat, power, hydraulic power and delta t from mean values.

    gives the analytical standard uncertainty with a seeded monte carlo
    cross-check for each.
    """
    if abs(flow_lpm) < 1e-12 or abs(voltage_v * current_a) < 1e-12:
        raise ValueError("Uncertainty propagation requires nonzero flow and electrical power")

    # nominal values, with flow in m3/s
    flow_m3_s = flow_lpm / 60_000.0
    u_flow = inputs.flow_standard_lpm / 60_000.0
    u_dt = delta_t_standard(inputs)
    heat = density * flow_m3_s * cp * delta_t_k
    power = voltage_v * current_a
    hydraulic = pressure_pa * flow_m3_s

    # analytical: root sum of squares of each input's effect
    u_heat = np.sqrt(
        (flow_m3_s * cp * delta_t_k * inputs.density_standard_kg_m3) ** 2
        + (density * cp * delta_t_k * u_flow) ** 2
        + (density * flow_m3_s * delta_t_k * inputs.cp_standard_j_kg_k) ** 2
        + (density * flow_m3_s * cp * u_dt) ** 2
    )
    u_power = np.sqrt((current_a * inputs.voltage_standard_v) ** 2 + (voltage_v * inputs.current_standard_a) ** 2)
    u_hydraulic = np.sqrt((flow_m3_s * inputs.pressure_standard_pa) ** 2 + (pressure_pa * u_flow) ** 2)

    # monte carlo: the draw order below fixes the seeded results
    rng = np.random.default_rng(seed)
    tin_tout_covariance = inputs.rtd_correlation * inputs.tin_standard_k * inputs.tout_standard_k
    covariance = np.array(
        [
            [inputs.tin_standard_k**2, tin_tout_covariance],
            [tin_tout_covariance, inputs.tout_standard_k**2],
        ]
    )
    temperature_errors = rng.multivariate_normal([0.0, 0.0], covariance, size=samples)
    flow_mc = rng.normal(flow_lpm, inputs.flow_standard_lpm, samples) / 60_000.0
    density_mc = rng.normal(density, inputs.density_standard_kg_m3, samples)
    cp_mc = rng.normal(cp, inputs.cp_standard_j_kg_k, samples)
    dt_mc = delta_t_k + temperature_errors[:, 1] - temperature_errors[:, 0]
    voltage_mc = rng.normal(voltage_v, inputs.voltage_standard_v, samples)
    current_mc = rng.normal(current_a, inputs.current_standard_a, samples)
    pressure_mc = rng.normal(pressure_pa, inputs.pressure_standard_pa, samples)
    heat_mc = density_mc * flow_mc * cp_mc * dt_mc
    power_mc = voltage_mc * current_mc
    hydraulic_mc = pressure_mc * flow_mc

    return {
        "heat_to_water_w": {
            "value": heat,
            "analytical_standard": float(u_heat),
            "monte_carlo_standard": float(np.std(heat_mc, ddof=1)),
        },
        "electrical_power_w": {
            "value": power,
            "analytical_standard": float(u_power),
            "monte_carlo_standard": float(np.std(power_mc, ddof=1)),
        },
        "hydraulic_power_w": {
            "value": hydraulic,
            "analytical_standard": float(u_hydraulic),
            "monte_carlo_standard": float(np.std(hydraulic_mc, ddof=1)),
        },
        "delta_t_k": {
            "value": delta_t_k,
            "analytical_standard": u_dt,
            "monte_carlo_standard": float(np.std(dt_mc, ddof=1)),
        },
    }
