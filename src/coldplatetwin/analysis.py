"""time-weighted analysis of one run, with provenance."""

from dataclasses import asdict, dataclass, field
import numpy as np
import pandas as pd

from .configuration import AnalysisConfig
from .io import validate_measurements
from .metrics import INPUT_CHANNELS, METRIC_NAMES, evaluate_metrics
from .properties import temperature_properties
from .roi import ROIStatistics
from .schemas import RunMetadata
from .steady import REQUIRED, SteadyStateConfig, find_steady_state, time_weights
from .uncertainty import propagate_experiment, standard_uncertainty


# --- result record ---

@dataclass
class AnalysisResult:
    """everything one analyzed run reports, ready to write as json."""

    run_id: str
    insert_id: str
    source: str
    steady_state: dict
    metrics: dict
    uncertainties: dict
    warnings: list[str]
    roi: dict | None = None
    provenance: dict = field(default_factory=dict)
    schema_version: str = "1.1"

    def as_dict(self):
        """plain nested dict of this result."""
        return asdict(self)


# --- run analysis ---

def analyze_run(frame, run_id, insert_id, source, steady_config=None, roi=None,
                *, metadata: RunMetadata | None = None, config: AnalysisConfig | None = None,
                steady_result=None):
    """analyze one logged run: steady-state check, metrics and uncertainty.

    metrics are worked out per sample and then time-averaged over the
    accepted interval. without run metadata the run can still be screened and
    measured, but no uncertainty is claimed.
    note: a given steady_config is written into config.steady_state.
    """
    config = config or AnalysisConfig()
    if steady_config is not None:
        config.steady_state = steady_config
    config.validate()
    validate_measurements(frame)
    if metadata is not None:
        metadata.validate()
        if (run_id, insert_id, source) != (metadata.run_id, metadata.insert_id, metadata.source):
            raise ValueError("Analysis identity disagrees with metadata")
    steady = steady_result or find_steady_state(frame, config.steady_state)

    # provenance and the warnings every run carries
    provenance = {
        "metadata": asdict(metadata) if metadata else None,
        "analysis_configuration": config.as_dict(),
        "analysis_configuration_hash": config.configuration_hash,
        "measurement_schema": "calibrated-1.1",
        "averaging": "trapezoid time weights on adjacent complete samples, no extrapolation or long-gap fill",
    }
    warnings = [
        "Unaccounted energy residual includes environmental loss, transient storage and measurement/model error.",
        "Steady-state criteria are provisional operating criteria.",
    ]
    if metadata is None or metadata.electrical_power_mode == "unspecified":
        warnings.append("Electrical power bandwidth/DC status is unspecified; low-rate V*I cannot establish PWM power.")
    if metadata is None or metadata.synchronization.maximum_channel_skew_s is None:
        warnings.append("Channel synchronization skew is unspecified.")
    if not steady.passed:
        return AnalysisResult(run_id, insert_id, source, asdict(steady), {}, {},
                              warnings + steady.reasons, provenance=provenance)

    # time weights over the accepted averaging interval
    selected = frame[(frame.timestamp >= steady.start) & (frame.timestamp <= steady.end)]
    thermal = list(config.steady_state.thermal_channels)
    if config.steady_state.include_surface_references:
        thermal.extend(c for c in selected if c.startswith("surface_reference_"))
    checked_columns = list(dict.fromkeys([*REQUIRED, *thermal]))
    complete = np.isfinite(selected[checked_columns].to_numpy(float)).all(axis=1)
    times = (selected.timestamp - selected.timestamp.iloc[0]).dt.total_seconds().to_numpy()
    weights = time_weights(times, complete, config.steady_state.maximum_gap_s)
    used = weights > 0
    values = selected[list(INPUT_CHANNELS)].to_numpy(float)[used]
    weights = weights[used] / weights.sum()

    # nominal metrics. the resistances need an roi.
    if metadata:
        location = metadata.flow_measurement_location
    else:
        location = "inlet"
    roi_mean = roi.mean_c if roi else 0
    nominal = evaluate_metrics(values, weights, roi_mean, location)[0]
    metrics = dict(zip(METRIC_NAMES, map(float, nominal)))
    if roi is None:
        for name in METRIC_NAMES[6:]:
            metrics[name] = None

    # time-weighted means of the inputs
    means = weights @ values
    flow, tin, tout, voltage, current, pressure = means
    if location == "inlet":
        density_column = 1
    else:
        density_column = 2
    rho, _, _ = temperature_properties(values[:, density_column])
    metrics.update({
        "flow_lpm": float(flow), "volume_flow_m3_s": float(flow / 60000),
        "mass_flow_kg_s": float(weights @ (rho * values[:, 0] / 60000)),
        "flow_density_location": location, "tin_c": float(tin), "tout_c": float(tout),
        "differential_pressure_pa": float(pressure),
        "ambient_c": float(weights @ selected.ambient_c.to_numpy(float)[used]),
        "roi_is_payload_subset_not_entire_payload": roi is not None,
    })

    # uncertainty needs run metadata
    uncertainties = {}
    if metadata:
        uncertainties, uncertainty_warnings = propagate_experiment(
            values, weights, roi.mean_c if roi else None, metadata, config)
        warnings.extend(uncertainty_warnings)
    else:
        warnings.append("Uncertainty unavailable: run metadata was not supplied.")

    # reject ratios whose denominators are weak, even when their point values
    # look plausible. keep the dimensional heat and power estimates.
    # 5 and 6 divide by power (index 1), 7 divides by heat (index 0).
    for i in (5, 6, 7):
        name = METRIC_NAMES[i]
        if i == 7:
            denominator = nominal[0]
        else:
            denominator = nominal[1]
        if abs(denominator) <= 1 or (name in uncertainties and uncertainties[name]["value"] is None):
            metrics[name] = None
            warnings.append(f"{name}: denominator is near zero or unresolved by uncertainty.")

    # weak signal warnings: delta t or delta p under three standard uncertainties
    dt_u = uncertainties.get("delta_t_k", {}).get("analytical_standard")
    if dt_u is not None and abs(metrics["delta_t_k"]) < 3*dt_u:
        warnings.append("Weak delta T: less than three propagated standard uncertainties.")
    sensors = {s.channel: s for s in metadata.sensors} if metadata else {}
    if "dp_pa" in sensors:
        sensor = sensors["dp_pa"]
        u_dp = standard_uncertainty(sensor.standard_uncertainty, sensor.distribution, sensor.stated_bound)
        if abs(pressure) < 3*u_dp:
            warnings.append("Weak delta p: less than three standard uncertainties.")
    return AnalysisResult(run_id, insert_id, source, asdict(steady), metrics, uncertainties,
                          warnings, asdict(roi) if roi else None, provenance)
