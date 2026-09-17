"""Deterministic synthetic logger and radiometric data.

Synthetic truth is written to a separate file and is never passed into the
analysis functions.  It is useful for software recovery checks only.
"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .geometry import GeometrySI
from .schemas import CalibrationCorrelation, CameraMetadata, RunMetadata, SensorSpec, Synchronization


def _insert_factor(insert_id: str) -> float:
    """Illustrative factors; they are not experimental rankings."""

    return {"FI-000": 0.72, "FI-100": 0.88, "FI-200": 0.84, "FI-300": 0.85}[insert_id]


def generate_run(
    output_dir: str | Path,
    geometry: GeometrySI,
    insert_id: str,
    seed: int,
    deliberately_invalid: bool = False,
    flow_target: float = 1.0,
    power_target: float = 180.0,
) -> Path:
    """Create one 20-minute, one-hertz synthetic experiment."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    n = 20 * 60
    t = np.arange(n, dtype=float)
    start = pd.Timestamp("2026-01-15T14:00:00Z") + pd.Timedelta(days=seed % 365)
    timestamps = start + pd.to_timedelta(t, unit="s")

    warm = 1.0 - np.exp(-t / 150.0)
    flow = flow_target + 0.0025 * rng.normal(size=n)
    voltage = np.full(n, 24.0) + 0.02 * rng.normal(size=n)
    current = (power_target / 24.0) * (1.0 + 0.003 * rng.normal(size=n))
    tin = 22.0 + 0.10 * np.sin(t / 400.0) + 0.015 * rng.normal(size=n)

    # Heat-to-water is intentionally lower than electrical input.  The
    # remainder represents storage during warm-up and environmental losses.
    heat_to_water = power_target * _insert_factor(insert_id) * warm
    mass_flow = flow / 60_000.0 * 997.5
    tout = tin + heat_to_water / (mass_flow * 4180.0) + 0.018 * rng.normal(size=n)
    # These are illustrative fixture values near the reduced-model scale.  They
    # are not measurements and do not assert a winning insert.
    dp_base = {"FI-000": 550.0, "FI-100": 1_800.0, "FI-200": 650.0, "FI-300": 650.0}[insert_id]
    dp = dp_base * (flow / flow_target) ** 1.85 + 15.0 * rng.normal(size=n)
    ambient = 21.5 + 0.03 * np.sin(t / 300.0) + 0.02 * rng.normal(size=n)

    if deliberately_invalid:
        # Long missing interval is retained as missing data.  Analysis should
        # reject the run rather than fill this gap silently.
        tout[500:] = np.nan
        run_id = f"SYN-{insert_id}-INVALID"
    else:
        run_id = f"SYN-{insert_id}-{seed:03d}"

    table = pd.DataFrame(
        {
            "timestamp": timestamps.astype(str),
            "flow_lpm": flow,
            "tin_c": tin + 0.04,
            "tout_c": tout - 0.03,
            "dp_pa": dp + 20.0,
            "ambient_c": ambient,
            "heater_voltage_v": voltage,
            "heater_current_a": current,
            "surface_reference_1_c": tin + 8.0 * warm + 0.03 * rng.normal(size=n),
        }
    )
    csv_path = output_dir / f"{run_id}_raw.csv"
    table.to_csv(csv_path, index=False)

    metadata = RunMetadata(
        run_id=run_id,
        insert_id=insert_id,
        geometry_hash=geometry.configuration_hash,
        source="synthetic",
        started_at=start.isoformat().replace("+00:00", "Z"),
        sensors=[
            SensorSpec("tin_c", "synthetic PT100", "SYN-PAIR-01", 0.05, "K", calibration_offset=-0.04),
            SensorSpec("tout_c", "synthetic PT100", "SYN-PAIR-01", 0.05, "K", calibration_offset=0.03),
            SensorSpec("flow_lpm", "synthetic flow", "SYN-FLOW-01", 0.005, "L/min"),
            SensorSpec("dp_pa", "synthetic differential pressure", "SYN-DP-01", 25.0, "Pa", calibration_offset=-20.0),
            SensorSpec("heater_voltage_v", "synthetic DC voltmeter", "SYN-V-01", 0.02, "V"),
            SensorSpec("heater_current_a", "synthetic DC ammeter", "SYN-I-01", 0.01, "A"),
            SensorSpec("ambient_c", "synthetic ambient probe", "SYN-AMBIENT-01", 0.1, "K"),
            SensorSpec("surface_reference_1_c", "synthetic contact probe", "SYN-SURFACE-01", 0.1, "K"),
        ],
        synchronization=Synchronization(maximum_channel_skew_s=0.05),
        camera=CameraMetadata("SYN-IR-01", 0.95, 21.5, True, 0.5, 0.04),
        raw_files=[csv_path.name],
        notes=["SYNTHETIC DATA - NOT PHYSICAL VALIDATION"],
        calibration_correlations=[CalibrationCorrelation("tin_c", "tout_c", 0.65)],
        electrical_power_mode="dc",
    )
    metadata.write_json(output_dir / f"{run_id}_metadata.json")

    truth = {
        "classification": "synthetic_truth_do_not_use_as_analysis_input",
        "seed": seed,
        "nominal_electrical_power_w": power_target,
        "illustrative_heat_to_water_fraction": _insert_factor(insert_id),
        "nominal_flow_lpm": flow_target,
        "deliberately_invalid": deliberately_invalid,
    }
    (output_dir / f"{run_id}_truth.json").write_text(json.dumps(truth, indent=2) + "\n")

    # One generic temperature-matrix fixture: each row is one frame followed
    # by 24x24 calibrated temperatures.  Missing pixels use -9999.
    if not deliberately_invalid:
        size = 24
        axis = np.linspace(-1.0, 1.0, size)
        xx, yy = np.meshgrid(axis, axis)
        base = 30.0 + 2.5 * (xx**2 + yy**2) + 0.6 * np.sin(3 * xx)
        rows = []
        for frame_id, seconds in enumerate(range(600, n, 60)):
            image = base + 0.05 * rng.normal(size=(size, size))
            image[0, 0] = -9999.0
            rows.append([str(timestamps[seconds]), frame_id, *image.ravel()])
        pd.DataFrame(rows).to_csv(output_dir / f"{run_id}_radiometric.csv", index=False, header=False)
    return csv_path


def generate_example_set(output_dir: str | Path, geometry: GeometrySI, seed: int = 20260917,
                         flow_lpm: float = 1.0, power_w: float = 180.0) -> list[Path]:
    """Generate four valid insert cases and one deliberately invalid run."""

    paths = [generate_run(output_dir, geometry, insert_id, seed + i, flow_target=flow_lpm, power_target=power_w)
             for i, insert_id in enumerate(("FI-000", "FI-100", "FI-200", "FI-300"))]
    paths.append(generate_run(output_dir, geometry, "FI-100", seed + 4, deliberately_invalid=True,
                              flow_target=flow_lpm, power_target=power_w))
    return paths
