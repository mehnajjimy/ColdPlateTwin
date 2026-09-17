"""Analytical and seeded Monte Carlo uncertainty propagation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from .metrics import INPUT_CHANNELS, METRIC_NAMES, evaluate_metrics, metric_jacobian


@dataclass(frozen=True)
class UncertaintyInputs:
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
    """Convert an uncertainty statement to a standard uncertainty."""

    if distribution in {"standard", "normal"}:
        return float(value)
    if distribution == "rectangular":
        bound = value if stated_bound is None else stated_bound
        return float(bound / np.sqrt(3.0))
    raise ValueError(f"Unsupported uncertainty distribution: {distribution}")


def propagate_experiment(values, weights, roi_mean, metadata, config):
    """Use the run's calibrated-unit uncertainty records, with no sensor defaults.

    Each supplied sensor uncertainty is conservatively a shared calibration
    error over a run and over runs with the same calibration_id. This avoids
    claiming independent-noise averaging without a sensor noise model.
    """
    metadata.validate()
    sensors = {sensor.channel: sensor for sensor in metadata.sensors}
    missing = [name for name in INPUT_CHANNELS if name not in sensors]
    if missing:
        return {}, ["Uncertainty unavailable: missing sensor specifications for " + ", ".join(missing)]
    standard = np.zeros(9)
    labels, distributions = [], []
    for i, name in enumerate(INPUT_CHANNELS):
        sensor = sensors[name]
        standard[i] = standard_uncertainty(sensor.standard_uncertainty, sensor.distribution, sensor.stated_bound)
        labels.append(sensor.calibration_id + ":" + name)
        distributions.append(sensor.distribution)
    camera_u = metadata.camera.absolute_accuracy_standard_uncertainty_k if metadata.camera else None
    standard[6] = camera_u if camera_u is not None else 0
    labels.append((metadata.camera.calibration_id if metadata.camera else "missing") + ":roi_mean_c")
    distributions.append("normal")
    standard[7:] = (config.density_relative_standard, config.enthalpy_relative_standard)
    labels.extend(("water-table-v1:density_relative", "water-table-v1:enthalpy_relative"))
    distributions.extend(("normal", "normal"))
    correlation = np.eye(9)
    correlation_records = {}
    for record in metadata.calibration_correlations:
        if record.channel_a in INPUT_CHANNELS and record.channel_b in INPUT_CHANNELS:
            i, j = INPUT_CHANNELS.index(record.channel_a), INPUT_CHANNELS.index(record.channel_b)
            correlation[i, j] = correlation[j, i] = record.correlation
            correlation_records["|".join(sorted((labels[i], labels[j])))] = record.correlation
    covariance = correlation * np.outer(standard, standard)
    roi_value = 0.0 if roi_mean is None else roi_mean
    nominal = evaluate_metrics(values, weights, roi_value, metadata.flow_measurement_location)[0]
    jacobian = metric_jacobian(values, weights, roi_value, metadata.flow_measurement_location)
    with np.errstate(invalid="ignore"):
        variance = np.einsum("ij,jk,ik->i", jacobian, covariance, jacobian)
    rng = np.random.default_rng(config.seed)
    errors = rng.multivariate_normal(np.zeros(9), covariance, size=config.monte_carlo_samples)
    for i, distribution in enumerate(distributions):
        if distribution == "rectangular":
            errors[:, i] = rng.uniform(-np.sqrt(3)*standard[i], np.sqrt(3)*standard[i], len(errors))
    # Do not extrapolate the water table when large uncertainty leaves its range.
    valid = np.ones(len(errors), dtype=bool)
    for i in (1, 2):
        valid &= (values[:, i].min() + errors[:, i] >= 15) & (values[:, i].max() + errors[:, i] <= 70)
    valid &= values[:, 0].min() + errors[:, 0] > 0
    draws = []
    for offset in range(0, len(errors), 128):
        accepted = errors[offset:offset+128][valid[offset:offset+128]]
        if len(accepted):
            draws.append(evaluate_metrics(values, weights, roi_value, metadata.flow_measurement_location, accepted))
    samples = np.vstack(draws) if draws else np.empty((0, len(METRIC_NAMES)))
    warnings = []
    if not valid.all():
        warnings.append("Monte Carlo leaves the property/positive-flow domain; its standard uncertainty is withheld.")
    if roi_mean is not None and camera_u is None:
        warnings.append("Thermal-resistance uncertainty unavailable: camera absolute accuracy is missing.")
    result = {}
    for i, name in enumerate(METRIC_NAMES):
        if i >= 6 and roi_mean is None:
            continue
        denominator_index = 1 if i in (5, 6) else 0
        weak_denominator = i >= 5 and abs(nominal[denominator_index]) <= max(1.0, 3*np.sqrt(max(0, variance[denominator_index])))
        unavailable = weak_denominator or (i >= 6 and camera_u is None)
        u = None if unavailable or not np.isfinite(variance[i]) else float(np.sqrt(max(0, variance[i])))
        mc = None
        if u is not None and valid.all() and len(samples) > 1 and np.isfinite(samples[:, i]).all():
            mc = float(np.std(samples[:, i], ddof=1))
        result[name] = {
            "value": float(nominal[i]) if np.isfinite(nominal[i]) and not weak_denominator else None,
            "analytical_standard": u, "monte_carlo_standard": mc,
            "status": "unavailable_or_weak_denominator" if unavailable else "available",
            "monte_carlo_valid_fraction": float(valid.mean()),
            "shared_standard_effects": dict(zip(labels, (jacobian[i] * standard).tolist())) if u is not None else {},
            "shared_correlations": correlation_records,
            "uncertainty_basis": "run-constant additive calibration errors in calibrated units; no sample-count reduction",
        }
    return result, warnings


def difference_standard_uncertainty(first: dict, second: dict) -> float | None:
    """Uncertainty of A-B, preserving errors shared by calibration ID/channel."""
    if first["analytical_standard"] is None or second["analytical_standard"] is None:
        return None
    a, b = first["shared_standard_effects"], second["shared_standard_effects"]
    correlations = first["shared_correlations"] | second["shared_correlations"]
    for pair in first["shared_correlations"].keys() & second["shared_correlations"].keys():
        if first["shared_correlations"][pair] != second["shared_correlations"][pair]:
            raise ValueError("Inconsistent shared calibration correlation between runs")
    cross_covariance = sum(a.get(key, 0) * b.get(key, 0) for key in a.keys() | b.keys())
    for pair, rho in correlations.items():
        left, right = pair.split("|")
        cross_covariance += rho * (a.get(left, 0)*b.get(right, 0) + a.get(right, 0)*b.get(left, 0))
    variance = first["analytical_standard"]**2 + second["analytical_standard"]**2 - 2*cross_covariance
    return float(np.sqrt(max(0, variance)))


def delta_t_standard(inputs: UncertaintyInputs) -> float:
    """u(Tout-Tin), retaining covariance from pair calibration."""

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
    """Return analytical standard uncertainties and a Monte Carlo cross-check."""

    if abs(flow_lpm) < 1e-12 or abs(voltage_v * current_a) < 1e-12:
        raise ValueError("Uncertainty propagation requires nonzero flow and electrical power")
    flow_m3_s = flow_lpm / 60_000.0
    u_flow = inputs.flow_standard_lpm / 60_000.0
    u_dt = delta_t_standard(inputs)
    heat = density * flow_m3_s * cp * delta_t_k
    power = voltage_v * current_a
    hydraulic = pressure_pa * flow_m3_s
    u_heat = np.sqrt(
        (flow_m3_s * cp * delta_t_k * inputs.density_standard_kg_m3) ** 2
        + (density * cp * delta_t_k * u_flow) ** 2
        + (density * flow_m3_s * delta_t_k * inputs.cp_standard_j_kg_k) ** 2
        + (density * flow_m3_s * cp * u_dt) ** 2
    )
    u_power = np.sqrt((current_a * inputs.voltage_standard_v) ** 2 + (voltage_v * inputs.current_standard_a) ** 2)
    u_hydraulic = np.sqrt((flow_m3_s * inputs.pressure_standard_pa) ** 2 + (pressure_pa * u_flow) ** 2)

    rng = np.random.default_rng(seed)
    covariance = np.array(
        [
            [inputs.tin_standard_k**2, inputs.rtd_correlation * inputs.tin_standard_k * inputs.tout_standard_k],
            [inputs.rtd_correlation * inputs.tin_standard_k * inputs.tout_standard_k, inputs.tout_standard_k**2],
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
        "heat_to_water_w": {"value": heat, "analytical_standard": float(u_heat), "monte_carlo_standard": float(np.std(heat_mc, ddof=1))},
        "electrical_power_w": {"value": power, "analytical_standard": float(u_power), "monte_carlo_standard": float(np.std(power_mc, ddof=1))},
        "hydraulic_power_w": {"value": hydraulic, "analytical_standard": float(u_hydraulic), "monte_carlo_standard": float(np.std(hydraulic_mc, ddof=1))},
        "delta_t_k": {"value": delta_t_k, "analytical_standard": u_dt, "monte_carlo_standard": float(np.std(dt_mc, ddof=1))},
    }
