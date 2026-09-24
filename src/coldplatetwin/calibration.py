"""simple affine sensor calibration."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .schemas import SensorSpec
from .io import validate_measurements


# a straight-line correction for one channel: corrected = raw * scale + offset
@dataclass(frozen=True)
class AffineCalibration:
    channel: str
    calibration_id: str
    scale: float = 1.0
    offset: float = 0.0


# apply each correction to a copy of the table, then re-check the value ranges
def apply_calibrations(raw: pd.DataFrame, calibrations: list[AffineCalibration]) -> pd.DataFrame:
    """return a calibrated copy. the raw table and csv stay unchanged."""
    calibrated = raw.copy(deep=True)
    for item in calibrations:
        if item.channel not in calibrated:
            raise ValueError(f"Calibration channel not found: {item.channel}")
        calibrated[item.channel] = calibrated[item.channel] * item.scale + item.offset
    validate_measurements(calibrated)
    return calibrated


# make one correction per sensor listed in the run metadata
def calibrations_from_sensor_specs(sensors: list[SensorSpec]) -> list[AffineCalibration]:
    """build affine corrections directly from versioned run metadata."""
    return [
        AffineCalibration(
            channel=sensor.channel,
            calibration_id=sensor.calibration_id,
            scale=sensor.calibration_scale,
            offset=sensor.calibration_offset,
        )
        for sensor in sensors
    ]
