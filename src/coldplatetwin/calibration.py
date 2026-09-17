"""Simple, explicit affine sensor calibration."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .schemas import SensorSpec
from .io import validate_measurements


@dataclass(frozen=True)
class AffineCalibration:
    channel: str
    calibration_id: str
    scale: float = 1.0
    offset: float = 0.0


def apply_calibrations(raw: pd.DataFrame, calibrations: list[AffineCalibration]) -> pd.DataFrame:
    """Return a calibrated copy; the raw DataFrame and CSV remain unchanged."""

    calibrated = raw.copy(deep=True)
    for item in calibrations:
        if item.channel not in calibrated:
            raise ValueError(f"Calibration channel not found: {item.channel}")
        calibrated[item.channel] = calibrated[item.channel] * item.scale + item.offset
    validate_measurements(calibrated)
    return calibrated


def calibrations_from_sensor_specs(sensors: list[SensorSpec]) -> list[AffineCalibration]:
    """Build affine operations directly from versioned run metadata."""

    return [
        AffineCalibration(
            channel=sensor.channel,
            calibration_id=sensor.calibration_id,
            scale=sensor.calibration_scale,
            offset=sensor.calibration_offset,
        )
        for sensor in sensors
    ]
