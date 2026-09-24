"""csv input for logger data and radiometric temperature matrices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd


# the channels every logger csv must contain
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


# a placeholder for future live sources such as serial loggers or cameras
class MeasurementSource(Protocol):
    """minimal future boundary for serial loggers or camera adapters."""

    def read(self) -> pd.DataFrame: ...


# ---------------------------------------------------------------------------
# cell parsing
# ---------------------------------------------------------------------------

# parse timestamps to utc, refusing any value without an explicit timezone
def parse_timestamps(values) -> pd.DatetimeIndex:
    """require explicit timezones before normalizing timestamps to utc."""
    # check each value on its own first so the error names the bad one
    for value in values:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"Invalid timestamp: {value!r}") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Each timestamp requires an explicit timezone")

    # then convert them together and require a clean increasing sequence
    result = pd.DatetimeIndex(pd.to_datetime(values, utc=True, format="mixed"))
    if result.hasnans or result.has_duplicates or not result.is_monotonic_increasing:
        raise ValueError("Duplicate or nonmonotonic timestamps are not allowed")
    return result


# convert a column to numbers. blank cells become nan, junk text is an error
def numeric_values(values: pd.Series) -> pd.Series:
    """empty, na and nan cells are missing. malformed text and infinities are errors."""
    try:
        result = pd.to_numeric(values, errors="raise")
    except (ValueError, TypeError) as error:
        raise ValueError(f"Malformed numeric input in {values.name}: {error}") from error
    if np.isinf(result.to_numpy(float)).any():
        raise ValueError(f"Infinite values in {values.name}")
    return result


# ---------------------------------------------------------------------------
# logger csv
# ---------------------------------------------------------------------------

# read a logger csv, check its columns and values, and return it as a table
def read_measurement_csv(path: str | Path) -> pd.DataFrame:
    """read a logger csv without changing the source file.

    required channels must be present. missing numbers stay nan and are never
    filled in. timestamps must be unique and increasing.
    """
    path = Path(path)
    frame = pd.read_csv(path)

    # the file needs every required channel and at least one row
    missing = [name for name in MEASUREMENT_COLUMNS if name not in frame.columns]
    if missing:
        raise ValueError(f"Missing required measurement columns: {missing}")
    if frame.empty:
        raise ValueError("Measurement CSV contains no rows")

    frame["timestamp"] = parse_timestamps(frame["timestamp"])

    # every channel after the timestamp is numeric, plus any surface references
    numeric = list(MEASUREMENT_COLUMNS[1:])
    numeric += [name for name in frame if name.startswith("surface_reference_")]
    for name in numeric:
        frame[name] = numeric_values(frame[name])

    validate_measurements(frame)
    return frame


# reject values outside a plausible physical range for each channel
def validate_measurements(frame: pd.DataFrame) -> None:
    """apply the same physical range checks to raw and calibrated values."""
    # allowed (low, high) range for each channel
    rules = {
        "flow_lpm": (0.0, 20.0),
        "tin_c": (-5.0, 100.0),
        "tout_c": (-5.0, 100.0),
        "dp_pa": (-1000.0, 1e7),
        "ambient_c": (-20.0, 80.0),
        "heater_voltage_v": (0.0, 1000.0),
        "heater_current_a": (0.0, 1000.0),
    }
    for name in frame:
        if name.startswith("surface_reference_"):
            rules[name] = (-20.0, 200.0)

    # missing values are allowed. any value out of range, an infinity included,
    # is reported with the first few row labels
    for name, (low, high) in rules.items():
        present = frame[name].dropna()
        bad = present[(present < low) | (present > high)]
        if not bad.empty:
            raise ValueError(f"Invalid {name} values at rows {bad.index.tolist()[:5]}")
        # infinities already fail the range check above, but reading the whole
        # column as floats here also rejects cells like pd.NA in an object column
        if np.isinf(frame[name].to_numpy(float)).any():
            raise ValueError(f"Invalid infinite {name} values")


# ---------------------------------------------------------------------------
# radiometric csv
# ---------------------------------------------------------------------------

# how to read a radiometric csv export. width and height must always be given
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


# a stack of temperature frames with bad pixels masked out
@dataclass
class RadiometricFrames:
    temperatures_c: np.ma.MaskedArray
    timestamps: pd.DatetimeIndex | None
    frame_ids: np.ndarray | None
    correction_applied: bool = False


# read a radiometric csv where each row holds one frame of temperatures
def read_radiometric_csv(path: str | Path, config: RadiometricCSVConfig) -> RadiometricFrames:
    """import numeric temperature arrays from a generic radiometric csv.

    this parser does not claim vendor compatibility. colored screenshots or
    jpegs are not accepted because their pixels are not calibrated temperatures.
    """
    # check the settings before reading the file. the frame shape is never
    # guessed, so width and height must be given
    if config.temperature_unit != "degC" or not config.already_temperature_corrected:
        raise ValueError("Only already-corrected degC temperature exports are supported")
    if not isinstance(config.width, int) or not isinstance(config.height, int) or min(config.width, config.height) < 1:
        raise ValueError("Radiometric width and height must be positive integers")
    if config.skip_rows < 0 or config.data_start_column < 0 or len(config.delimiter) != 1:
        raise ValueError("Invalid radiometric parsing configuration")

    raw = pd.read_csv(path, sep=config.delimiter, skiprows=config.skip_rows, header=None)
    if raw.empty:
        raise ValueError("Radiometric CSV contains no frames")

    # optional timestamp and frame number columns
    timestamps = None
    if config.timestamp_column is not None:
        timestamps = parse_timestamps(raw.iloc[:, config.timestamp_column])

    frame_ids = None
    if config.frame_column is not None:
        frame_ids = pd.to_numeric(raw.iloc[:, config.frame_column], errors="raise").to_numpy()

    # the temperature values. numeric_values already rejects infinities
    values = raw.iloc[:, config.data_start_column:].apply(numeric_values).to_numpy(float)
    expected = config.width * config.height
    if values.shape[1] != expected:
        raise ValueError(f"Expected {expected} temperature values per frame, got {values.shape[1]}")

    # mask blank cells and the export's invalid markers, then range check the rest
    mask = np.isnan(values)
    for invalid in config.invalid_values:
        mask |= values == invalid
    if np.any((~mask) & ((values < -273.15) | (values > 1000))):
        raise ValueError("Invalid radiometric temperature outside [-273.15, 1000] degC")

    # turn each row into a height by width image
    shape = (-1, config.height, config.width)
    cube = np.ma.array(values.reshape(shape), mask=mask.reshape(shape))
    return RadiometricFrames(cube, timestamps, frame_ids, correction_applied=False)
