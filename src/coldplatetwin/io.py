"""CSV input boundaries for logger data and radiometric temperature matrices."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from datetime import datetime

import numpy as np
import pandas as pd


MEASUREMENT_COLUMNS = (
    "timestamp",
    "flow_lpm",
    "tin_c",
    "tout_c",
    "dp_pa",
    "ambient_c",
    "heater_voltage_v",
    "heater_current_a",
)


class MeasurementSource(Protocol):
    """Minimal future boundary for serial loggers or camera adapters."""

    def read(self) -> pd.DataFrame: ...


def parse_timestamps(values) -> pd.DatetimeIndex:
    """Require explicit timezones before normalizing timestamps to UTC."""
    for value in values:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"Invalid timestamp: {value!r}") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Each timestamp requires an explicit timezone")
    result = pd.DatetimeIndex(pd.to_datetime(values, utc=True, format="mixed"))
    if result.hasnans or result.has_duplicates or not result.is_monotonic_increasing:
        raise ValueError("Duplicate or nonmonotonic timestamps are not allowed")
    return result


def numeric_values(values: pd.Series) -> pd.Series:
    """Empty, NA and NaN cells are missing; malformed strings are errors."""
    try:
        result = pd.to_numeric(values, errors="raise")
    except (ValueError, TypeError) as error:
        raise ValueError(f"Malformed numeric input in {values.name}: {error}") from error
    if np.isinf(result.to_numpy(float)).any():
        raise ValueError(f"Infinite values in {values.name}")
    return result


def read_measurement_csv(path: str | Path) -> pd.DataFrame:
    """Read a logger CSV while preserving the source file unchanged.

    Required channels must be present.  Missing numeric values remain NaN and
    are never silently interpolated.  Timestamps must be unique and increasing.
    """

    path = Path(path)
    frame = pd.read_csv(path)
    missing = [name for name in MEASUREMENT_COLUMNS if name not in frame.columns]
    if missing:
        raise ValueError(f"Missing required measurement columns: {missing}")
    if frame.empty:
        raise ValueError("Measurement CSV contains no rows")

    frame["timestamp"] = parse_timestamps(frame["timestamp"])

    numeric = list(MEASUREMENT_COLUMNS[1:]) + [c for c in frame if c.startswith("surface_reference_")]
    for name in numeric:
        frame[name] = numeric_values(frame[name])
    validate_measurements(frame)
    return frame


def validate_measurements(frame: pd.DataFrame) -> None:
    """Apply the same physical-domain checks to raw AND calibrated values."""

    rules = {
        "flow_lpm": (0.0, 20.0),
        "tin_c": (-5.0, 100.0),
        "tout_c": (-5.0, 100.0),
        "dp_pa": (-1000.0, 1e7),
        "ambient_c": (-20.0, 80.0),
        "heater_voltage_v": (0.0, 1000.0),
        "heater_current_a": (0.0, 1000.0),
    }
    rules.update({c: (-20.0, 200.0) for c in frame if c.startswith("surface_reference_")})
    for name, (low, high) in rules.items():
        finite = frame[name].dropna()
        bad = finite[(finite < low) | (finite > high)]
        if not bad.empty:
            raise ValueError(f"Invalid {name} values at rows {bad.index.tolist()[:5]}")
        if np.isinf(frame[name].to_numpy(float)).any():
            raise ValueError(f"Invalid infinite {name} values")


@dataclass(frozen=True)
class RadiometricCSVConfig:
    delimiter: str = ","
    skip_rows: int = 0
    timestamp_column: int | None = None
    frame_column: int | None = None
    data_start_column: int = 0
    width: int | None = None
    height: int | None = None
    invalid_values: tuple[float, ...] = (-9999.0,)
    already_temperature_corrected: bool = True
    temperature_unit: str = "degC"


@dataclass
class RadiometricFrames:
    temperatures_c: np.ma.MaskedArray
    timestamps: pd.DatetimeIndex | None
    frame_ids: np.ndarray | None
    correction_applied: bool = False


def read_radiometric_csv(path: str | Path, config: RadiometricCSVConfig) -> RadiometricFrames:
    """Import numeric temperature arrays from a generic radiometric CSV.

    This parser does not claim vendor compatibility.  Colored screenshots/JPEGs
    are not accepted because their pixels are not calibrated temperatures.
    """

    if config.temperature_unit != "degC" or not config.already_temperature_corrected:
        raise ValueError("Only already-corrected degC temperature exports are supported")
    if not isinstance(config.width, int) or not isinstance(config.height, int) or min(config.width, config.height) < 1:
        raise ValueError("Radiometric width and height must be positive integers")
    if config.skip_rows < 0 or config.data_start_column < 0 or len(config.delimiter) != 1:
        raise ValueError("Invalid radiometric parsing configuration")
    raw = pd.read_csv(path, sep=config.delimiter, skiprows=config.skip_rows, header=None)
    if raw.empty:
        raise ValueError("Radiometric CSV contains no frames")

    timestamps = None
    if config.timestamp_column is not None:
        timestamps = parse_timestamps(raw.iloc[:, config.timestamp_column])

    frame_ids = None
    if config.frame_column is not None:
        frame_ids = pd.to_numeric(raw.iloc[:, config.frame_column], errors="raise").to_numpy()

    values = raw.iloc[:, config.data_start_column:].apply(numeric_values).to_numpy(float)
    if config.width is None or config.height is None:
        raise ValueError("Radiometric width and height are required; shape is never guessed")
    expected = config.width * config.height
    if values.shape[1] != expected:
        raise ValueError(f"Expected {expected} temperature values per frame, got {values.shape[1]}")
    if np.isinf(values).any():
        raise ValueError("Radiometric data contains infinite values")
    mask = np.isnan(values)
    for invalid in config.invalid_values:
        mask |= values == invalid
    if np.any((~mask) & ((values < -273.15) | (values > 1000))):
        raise ValueError("Invalid radiometric temperature outside [-273.15, 1000] degC")
    cube = np.ma.array(values.reshape((-1, config.height, config.width)), mask=mask.reshape((-1, config.height, config.width)))
    return RadiometricFrames(cube, timestamps, frame_ids, correction_applied=False)
