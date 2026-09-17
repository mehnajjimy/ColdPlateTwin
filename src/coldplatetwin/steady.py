"""Screen stability and sampling quality before AND during averaging."""

from dataclasses import asdict, dataclass
import numpy as np
import pandas as pd

REQUIRED = ("tin_c", "tout_c", "flow_lpm", "heater_voltage_v",
            "heater_current_a", "dp_pa", "ambient_c")


@dataclass(frozen=True)
class SteadyStateConfig:
    screening_window_s: float = 300.0
    averaging_interval_s: float = 180.0
    maximum_thermal_slope_k_min: float = 0.03
    maximum_thermal_step_k: float = 0.3
    maximum_flow_cv: float = 0.01
    maximum_power_cv: float = 0.01
    minimum_coverage_fraction: float = 0.90
    maximum_gap_s: float = 5.0
    minimum_flow_lpm: float = 0.05
    minimum_power_w: float = 5.0
    thermal_channels: tuple[str, ...] = ("tin_c", "tout_c", "ambient_c")
    include_surface_references: bool = True

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if name not in {"thermal_channels", "include_surface_references"}:
                if not np.isfinite(value) or value <= 0:
                    raise ValueError(f"steady_state.{name} must be finite and positive")
        if self.minimum_coverage_fraction > 1:
            raise ValueError("minimum_coverage_fraction must be <= 1")
        if not {"tin_c", "tout_c"}.issubset(self.thermal_channels):
            raise ValueError("thermal_channels must include tin_c and tout_c")


@dataclass
class SteadyStateResult:
    passed: bool
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    reasons: list[str]
    diagnostics: dict
    criteria: dict


def time_weights(time_s: np.ndarray, complete: np.ndarray, maximum_gap_s: float) -> np.ndarray:
    """Trapezoid weights on adjacent complete samples only.

    Missing samples break an integration segment. Long gaps receive no weight;
    no interpolated samples or endpoint extrapolation are invented.
    """
    weights = np.zeros(len(time_s))
    gaps = np.diff(time_s)
    usable = complete[:-1] & complete[1:] & (gaps <= maximum_gap_s)
    half_duration = np.where(usable, gaps / 2, 0)
    weights[:-1] += half_duration
    weights[1:] += half_duration
    return weights


def _check_window(time_s, data, power, columns, thermal_columns, start, end, config):
    selected = (time_s >= start) & (time_s <= end)
    t = time_s[selected]
    values = data[selected]
    complete = np.isfinite(values).all(axis=1)
    reasons = []
    weights = time_weights(t, complete, config.maximum_gap_s)
    covered = float(weights.sum())
    valid_times = t[complete]
    gap = float(np.diff(np.r_[start, valid_times, end]).max())
    coverage = covered / (end - start)
    diagnostics = {"coverage_fraction": coverage, "maximum_valid_sample_gap_s": gap}
    if coverage < config.minimum_coverage_fraction:
        reasons.append("insufficient valid-channel time coverage")
    if gap > config.maximum_gap_s:
        reasons.append("valid-sample gap exceeds maximum_gap_s")
    if complete.sum() < 3 or covered == 0:
        return reasons + ["fewer than three usable samples"], diagnostics
    good = weights > 0
    w = weights[good] / covered
    t_minutes = t[good] / 60
    centered_time = t_minutes - np.dot(w, t_minutes)
    for channel in thermal_columns:
        y = values[good, columns.index(channel)]
        slope = float(np.dot(w, centered_time * y) / np.dot(w, centered_time**2))
        steps = np.abs(np.diff(values[complete, columns.index(channel)]))
        max_step = float(steps.max())
        diagnostics[channel + "_slope_k_min"] = slope
        diagnostics[channel + "_maximum_step_k"] = max_step
        if abs(slope) > config.maximum_thermal_slope_k_min:
            reasons.append(f"{channel} slope exceeds criterion")
        if max_step > config.maximum_thermal_step_k:
            reasons.append(f"{channel} temperature step exceeds criterion")
    for name, series, floor, limit in (
        ("flow", values[good, columns.index("flow_lpm")], config.minimum_flow_lpm, config.maximum_flow_cv),
        ("power", power[selected][good], config.minimum_power_w, config.maximum_power_cv),
    ):
        mean = float(np.dot(w, series))
        cv = float(np.sqrt(np.dot(w, (series - mean)**2)) / abs(mean)) if mean > floor else None
        diagnostics[name + "_cv"] = cv
        if cv is None or cv > limit:
            reasons.append(f"{name} mean/CV fails criterion")
    return reasons, diagnostics


def find_steady_state(frame: pd.DataFrame, config: SteadyStateConfig = SteadyStateConfig()) -> SteadyStateResult:
    """Accept only a complete screen, average AND stable interval boundary."""
    config.validate()
    thermal = list(config.thermal_channels)
    if config.include_surface_references:
        thermal.extend(c for c in frame if c.startswith("surface_reference_") and c not in thermal)
    columns = list(dict.fromkeys([*REQUIRED, *thermal]))
    missing = set(["timestamp", *columns]) - set(frame)
    if missing:
        raise ValueError(f"Steady-state input missing columns: {sorted(missing)}")
    criteria = asdict(config)
    if len(frame) < 3:
        return SteadyStateResult(False, None, None, ["fewer than three samples"], {}, criteria)
    timestamps = pd.DatetimeIndex(frame["timestamp"])
    if timestamps.hasnans or timestamps.tz is None or not timestamps.is_monotonic_increasing or timestamps.has_duplicates:
        raise ValueError("Timestamps must be timezone-aware, unique and increasing")
    t = (timestamps - timestamps[0]).total_seconds().to_numpy()
    data = frame[columns].to_numpy(float)
    power = (frame.heater_voltage_v * frame.heater_current_a).to_numpy(float)
    screen, average = config.screening_window_s, config.averaging_interval_s
    reasons, diagnostics = ["run shorter than screening plus averaging intervals"], {}
    for start in t[t <= t[-1] - screen - average]:
        boundary, end = start + screen, start + screen + average
        reasons, diagnostics = [], {}
        for name, left, right in (("screen", start, boundary), ("average", boundary, end), ("combined", start, end)):
            failures, details = _check_window(t, data, power, columns, thermal, left, right, config)
            diagnostics[name] = details
            reasons.extend(f"{name}: {reason}" for reason in failures)
        if not reasons:
            return SteadyStateResult(True, timestamps[0] + pd.Timedelta(seconds=boundary),
                                     timestamps[0] + pd.Timedelta(seconds=end), [], diagnostics, criteria)
    return SteadyStateResult(False, None, None, reasons, diagnostics, criteria)
