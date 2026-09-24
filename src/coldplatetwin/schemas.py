"""versioned experiment schemas that serialize to json.

the measurement table itself is checked in coldplatetwin.io.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import math
import re
from pathlib import Path
from typing import Literal
import numpy as np


# the metadata version this code reads and writes
SCHEMA_VERSION = "1.0"

# the unit each sensor's standard uncertainty must be stated in.
# temperature uncertainties are differences, so they are in kelvin
CHANNEL_UNITS = {
    "flow_lpm": "L/min",
    "tin_c": "K",
    "tout_c": "K",
    "dp_pa": "Pa",
    "ambient_c": "K",
    "heater_voltage_v": "V",
    "heater_current_a": "A",
}

SourceClass = Literal["synthetic", "experimental"]


# ---------------------------------------------------------------------------
# metadata records
# ---------------------------------------------------------------------------

# one sensor: its calibration, uncertainty and affine correction
@dataclass
class SensorSpec:
    channel: str
    model: str
    calibration_id: str
    standard_uncertainty: float
    uncertainty_unit: str
    distribution: Literal["standard", "normal", "rectangular"] = "standard"
    stated_bound: float | None = None
    calibration_scale: float = 1.0
    calibration_offset: float = 0.0
    notes: str = ""


# the infrared camera setup used for a radiometric export
@dataclass
class CameraMetadata:
    calibration_id: str
    emissivity: float
    reflected_temperature_c: float
    export_is_temperature_corrected: bool
    absolute_accuracy_standard_uncertainty_k: float | None
    netd_k: float | None
    notes: str = "NETD describes short-term noise, not absolute accuracy."


# how the logger channels share one clock
@dataclass
class Synchronization:
    clock_basis: str = "UTC ISO-8601"
    maximum_channel_skew_s: float | None = None
    resampling_applied: bool = False
    notes: str = "No timing is invented for sources without timestamps."


# a correlation between two sensors that share a calibration
@dataclass
class CalibrationCorrelation:
    """correlation of run-constant errors from a shared calibration."""

    channel_a: str
    channel_b: str
    correlation: float


# ---------------------------------------------------------------------------
# run metadata
# ---------------------------------------------------------------------------

# everything recorded about one run, saved as a json file next to the logger csv
@dataclass
class RunMetadata:
    run_id: str
    insert_id: Literal["FI-000", "FI-100", "FI-200", "FI-300"]
    geometry_hash: str
    source: SourceClass
    started_at: str
    flow_unit: Literal["L/min"] = "L/min"
    pressure_unit: Literal["Pa"] = "Pa"
    temperature_unit: Literal["degC"] = "degC"
    voltage_unit: Literal["V"] = "V"
    current_unit: Literal["A"] = "A"
    schema_version: str = SCHEMA_VERSION
    sensors: list[SensorSpec] = field(default_factory=list)
    synchronization: Synchronization = field(default_factory=Synchronization)
    camera: CameraMetadata | None = None
    raw_files: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    calibration_correlations: list[CalibrationCorrelation] = field(default_factory=list)
    flow_measurement_location: str = "inlet"
    electrical_power_mode: str = "unspecified"

    # raise ValueError on the first field that is missing, unsafe or ambiguous
    def validate(self) -> None:
        """reject metadata that would make units or provenance ambiguous."""
        # identity and provenance
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version {self.schema_version!r}")
        if self.source not in {"synthetic", "experimental"}:
            raise ValueError("source must be 'synthetic' or 'experimental'")
        if not self.run_id.strip():
            raise ValueError("run_id cannot be empty")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", self.run_id) or self.run_id in {".", ".."}:
            raise ValueError("run_id must be a safe file identifier")
        if self.insert_id not in {"FI-000", "FI-100", "FI-200", "FI-300"}:
            raise ValueError("Unknown insert_id")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.geometry_hash):
            raise ValueError("geometry_hash must be a 64-character SHA-256 hash")

        # units are fixed. raw exports in other units must be converted first
        required_units = (
            ("flow_unit", "L/min"),
            ("pressure_unit", "Pa"),
            ("temperature_unit", "degC"),
            ("voltage_unit", "V"),
            ("current_unit", "A"),
        )
        for field_name, unit in required_units:
            if getattr(self, field_name) != unit:
                raise ValueError(f"{field_name} must be {unit}; convert the raw export explicitly")

        # timing and measurement setup
        started = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
        if started.tzinfo is None or started.utcoffset() is None:
            raise ValueError("started_at requires an explicit timezone")
        if self.flow_measurement_location not in {"inlet", "outlet"}:
            raise ValueError("flow_measurement_location must be inlet or outlet")
        if self.electrical_power_mode not in {"dc", "adequately_sampled", "unspecified"}:
            raise ValueError("Unsupported electrical_power_mode")
        if self.synchronization.clock_basis != "UTC ISO-8601":
            raise ValueError("Only UTC ISO-8601 clock_basis is supported")
        skew = self.synchronization.maximum_channel_skew_s
        if skew is not None and (not math.isfinite(skew) or skew < 0):
            raise ValueError("maximum_channel_skew_s must be nonnegative")

        # sensors, keyed by channel. each channel may appear only once
        channels = {}
        for sensor in self.sensors:
            unit = CHANNEL_UNITS.get(sensor.channel)
            if sensor.channel.startswith("surface_reference_") and sensor.channel.endswith("_c"):
                unit = "K"
            if unit is None or sensor.channel in channels:
                raise ValueError(f"Unknown or duplicate calibration channel: {sensor.channel}")
            if sensor.uncertainty_unit != unit:
                raise ValueError(f"{sensor.channel} uncertainty_unit must be {unit}")
            if not sensor.calibration_id.strip() or not sensor.model.strip():
                raise ValueError("Sensor model and calibration_id are required")
            if any(delimiter in sensor.calibration_id for delimiter in (":", "|")):
                raise ValueError("calibration_id cannot contain ':' or '|'")
            for name in ("standard_uncertainty", "calibration_scale", "calibration_offset"):
                if not math.isfinite(getattr(sensor, name)):
                    raise ValueError(f"Sensor {name} must be finite")
            if sensor.standard_uncertainty < 0 or sensor.calibration_scale <= 0:
                raise ValueError("Sensor uncertainty must be nonnegative and scale positive")
            if sensor.distribution not in {"standard", "normal", "rectangular"}:
                raise ValueError("Unsupported uncertainty distribution")
            # a stated bound goes with a rectangular distribution, and only with one
            if sensor.stated_bound is not None:
                if not math.isfinite(sensor.stated_bound) or sensor.stated_bound < 0:
                    raise ValueError("stated_bound must be finite and nonnegative")
                if sensor.distribution != "rectangular":
                    raise ValueError("stated_bound requires a rectangular distribution")
            if sensor.distribution == "rectangular" and sensor.stated_bound is None:
                raise ValueError("Rectangular uncertainty requires an explicit stated_bound")
            channels[sensor.channel] = sensor

        # calibration correlations. build the full correlation matrix and check
        # it is positive semidefinite, as any real correlation matrix must be
        names = list(channels)
        correlation_matrix = np.eye(len(names))
        seen = set()
        for record in self.calibration_correlations:
            a = record.channel_a
            b = record.channel_b
            rho = record.correlation
            pair = tuple(sorted((a, b)))
            if a == b or pair in seen or a not in channels or b not in channels:
                raise ValueError("Invalid or duplicate calibration correlation channels")
            if not math.isfinite(rho) or abs(rho) > 1:
                raise ValueError("Calibration correlation must lie in [-1, 1]")
            if channels[a].calibration_id != channels[b].calibration_id:
                raise ValueError("Correlated sensors must name the same calibration_id")
            if channels[a].distribution == "rectangular" or channels[b].distribution == "rectangular":
                raise ValueError("Correlated rectangular errors are unsupported; provide a joint normal calibration")
            i = names.index(a)
            j = names.index(b)
            correlation_matrix[i, j] = rho
            correlation_matrix[j, i] = rho
            seen.add(pair)
        if names and np.linalg.eigvalsh(correlation_matrix).min() < -1e-10:
            raise ValueError("Calibration covariance must be positive semidefinite")

        # the optional camera
        if self.camera:
            camera = self.camera
            if not camera.calibration_id.strip() or not 0 < camera.emissivity <= 1:
                raise ValueError("Camera calibration_id and emissivity in (0, 1] are required")
            if any(delimiter in camera.calibration_id for delimiter in (":", "|")):
                raise ValueError("Camera calibration_id cannot contain ':' or '|'")
            if not math.isfinite(camera.reflected_temperature_c):
                raise ValueError("Reflected temperature must be finite")
            if type(camera.export_is_temperature_corrected) is not bool:
                raise ValueError("Camera correction status must be a boolean")
            for value in (camera.absolute_accuracy_standard_uncertainty_k, camera.netd_k):
                if value is not None and (not math.isfinite(value) or value < 0):
                    raise ValueError("Camera uncertainties must be finite and nonnegative")

    # validate, then save as indented json
    def write_json(self, path: str | Path) -> None:
        self.validate()
        Path(path).write_text(json.dumps(asdict(self), indent=2) + "\n")

    # load from json, rebuild the nested records, then validate
    @classmethod
    def read_json(cls, path: str | Path) -> "RunMetadata":
        data = json.loads(Path(path).read_text())
        data["sensors"] = [SensorSpec(**item) for item in data.get("sensors", [])]
        data["synchronization"] = Synchronization(**data.get("synchronization", {}))
        data["calibration_correlations"] = [
            CalibrationCorrelation(**record) for record in data.get("calibration_correlations", [])
        ]
        if data.get("camera"):
            data["camera"] = CameraMetadata(**data["camera"])
        result = cls(**data)
        result.validate()
        return result


# the current time in utc as an iso string ending in z
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
