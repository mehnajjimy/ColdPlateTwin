"""shared test data: one steady logger run and the metadata that describes it."""

import numpy as np
import pandas as pd
import pytest

from coldplatetwin.schemas import CalibrationCorrelation, CameraMetadata, RunMetadata, SensorSpec, Synchronization


@pytest.fixture
def constant_frame():
    """481 one-second samples of a perfectly steady run.

    flow 1 l/min, tin 25 degc, tout 27 degc, 24 v * 7.5 a = 180 w, dp 1000 pa.
    the first steady window is a 300 s screen then a 180 s average (rows 300-480).
    """
    seconds = np.arange(481)
    return pd.DataFrame({
        "timestamp": pd.Timestamp("2026-01-01T00:00:00Z") + pd.to_timedelta(seconds, unit="s"),
        "flow_lpm": 1.0,
        "tin_c": 25.0,
        "tout_c": 27.0,
        "dp_pa": 1000.0,
        "ambient_c": 22.0,
        "heater_voltage_v": 24.0,
        "heater_current_a": 7.5,
        "surface_reference_1_c": 32.0,
    })


@pytest.fixture
def metadata():
    """valid experimental metadata with one sensor record per logger channel."""
    # (channel, standard uncertainty, unit, calibration id)
    specifications = [
        ("flow_lpm", 0.005, "L/min", "flow"),
        ("tin_c", 0.05, "K", "pair"),
        ("tout_c", 0.05, "K", "pair"),
        ("dp_pa", 25, "Pa", "pressure"),
        ("heater_voltage_v", 0.02, "V", "voltage"),
        ("heater_current_a", 0.01, "A", "current"),
    ]
    sensors = [SensorSpec(channel, "test fixture", calibration, u, unit)
               for channel, u, unit, calibration in specifications]
    return RunMetadata(
        run_id="EXP-fixture",
        insert_id="FI-200",
        geometry_hash="a" * 64,
        source="experimental",
        started_at="2026-01-01T00:00:00Z",
        sensors=sensors,
        calibration_correlations=[CalibrationCorrelation("tin_c", "tout_c", 0.65)],
        camera=CameraMetadata("ir", 0.95, 22, True, 0.5, 0.04),
        synchronization=Synchronization(maximum_channel_skew_s=0.05),
        electrical_power_mode="dc",
    )
