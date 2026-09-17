from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from coldplatetwin.analysis import analyze_run
from coldplatetwin.calibration import apply_calibrations, calibrations_from_sensor_specs
from coldplatetwin.geometry import load_geometry
from coldplatetwin.hydraulics import (
    parallel_network,
    rectangular_darcy_friction_reynolds,
)
from coldplatetwin.io import RadiometricCSVConfig, read_measurement_csv, read_radiometric_csv
from coldplatetwin.properties import enthalpy_rise_j_kg, water_properties
from coldplatetwin.roi import circular_roi_statistics
from coldplatetwin.schemas import RunMetadata
from coldplatetwin.steady import SteadyStateConfig, find_steady_state
from coldplatetwin.synthetic import generate_run
from coldplatetwin.thermal import ThermalInputs, solve_two_layer, uniform_lumped_solution
from coldplatetwin.uncertainty import UncertaintyInputs, delta_t_standard, propagate_metrics


def test_geometry_adapter_uses_expected_rev_a_dimensions() -> None:
    geometry = load_geometry()
    assert geometry.base_size_m == pytest.approx(0.200)
    assert geometry.channel_height_m == pytest.approx(0.004)
    assert geometry.fi100_path_length_m == pytest.approx(1.1203994776)
    assert len(geometry.configuration_hash) == 64


def test_reference_water_properties_and_units() -> None:
    properties = water_properties(20.0)
    assert properties.density_kg_m3 == pytest.approx(998.21, abs=0.02)
    assert properties.cp_j_kg_k == pytest.approx(4182.0, abs=0.5)
    assert properties.viscosity_pa_s == pytest.approx(1.002e-3, rel=0.002)
    assert enthalpy_rise_j_kg(20.0, 30.0) == pytest.approx(41_800.0, rel=0.002)
    with pytest.raises(ValueError, match="pure water"):
        water_properties(25.0, fluid="water-glycol")


def test_measurement_csv_rejects_duplicates_and_missing_channels(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    pd.DataFrame({"timestamp": ["2026-01-01T00:00:00Z"]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="Missing required"):
        read_measurement_csv(path)

    complete = {name: [1.0, 1.0] for name in ("flow_lpm", "tin_c", "tout_c", "dp_pa", "ambient_c", "heater_voltage_v", "heater_current_a")}
    complete["timestamp"] = ["2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"]
    pd.DataFrame(complete).to_csv(path, index=False)
    with pytest.raises(ValueError, match="Duplicate"):
        read_measurement_csv(path)


def test_radiometric_shape_and_mask(tmp_path: Path) -> None:
    path = tmp_path / "ir.csv"
    path.write_text("2026-01-01T00:00:00Z,0,20,21,-9999,23,24,25\n")
    frames = read_radiometric_csv(path, RadiometricCSVConfig(timestamp_column=0, frame_column=1, data_start_column=2, width=3, height=2))
    assert frames.temperatures_c.shape == (1, 2, 3)
    assert int(frames.temperatures_c.mask.sum()) == 1
    with pytest.raises(ValueError, match="Expected"):
        read_radiometric_csv(path, RadiometricCSVConfig(data_start_column=2, width=4, height=2))


def test_circular_roi_excludes_invalid_and_occluded_pixels() -> None:
    image = np.arange(25, dtype=float).reshape(5, 5)
    image[2, 2] = np.nan
    occlusion = np.zeros_like(image, dtype=bool)
    occlusion[1, 2] = True
    result = circular_roi_statistics(image, roi_diameter_px=4.0, occlusion_mask=occlusion)
    assert result.valid_pixel_count < result.total_roi_pixel_count
    assert np.isfinite(result.mean_c)


def test_steady_state_selection_and_long_gap_rejection(tmp_path: Path) -> None:
    geometry = load_geometry()
    csv_path = generate_run(tmp_path, geometry, "FI-100", 42)
    frame = read_measurement_csv(csv_path)
    result = find_steady_state(frame)
    assert result.passed
    dropped = frame.drop(frame.index[400:550]).reset_index(drop=True)
    strict = find_steady_state(dropped, SteadyStateConfig(maximum_gap_s=2.0))
    # Later clean windows may pass; no accepted window may cross the long gap.
    if strict.passed:
        assert strict.start > frame.loc[550, "timestamp"]


def test_invalid_synthetic_run_fails_steady_state(tmp_path: Path) -> None:
    geometry = load_geometry()
    csv_path = generate_run(tmp_path, geometry, "FI-100", 99, deliberately_invalid=True)
    result = analyze_run(read_measurement_csv(csv_path), "invalid", "FI-100", "synthetic")
    assert not result.steady_state["passed"]
    assert result.metrics == {}


def test_calibration_coefficients_round_trip_through_metadata(tmp_path: Path) -> None:
    geometry = load_geometry()
    csv_path = generate_run(tmp_path, geometry, "FI-100", 7)
    metadata = RunMetadata.read_json(tmp_path / "SYN-FI-100-007_metadata.json")
    raw = read_measurement_csv(csv_path)
    calibrated = apply_calibrations(raw, calibrations_from_sensor_specs(metadata.sensors))
    assert calibrated["tin_c"].mean() == pytest.approx(raw["tin_c"].mean() - 0.04)
    assert calibrated["dp_pa"].mean() == pytest.approx(raw["dp_pa"].mean() - 20.0)


def test_rtd_covariance_and_monte_carlo_agree() -> None:
    independent = delta_t_standard(UncertaintyInputs(rtd_correlation=0.0))
    paired = delta_t_standard(UncertaintyInputs(rtd_correlation=0.8))
    assert paired < independent
    result = propagate_metrics(1.0, 997.0, 4180.0, 2.0, 24.0, 7.5, 1000.0, samples=30_000)
    for metric in result.values():
        assert metric["monte_carlo_standard"] == pytest.approx(metric["analytical_standard"], rel=0.04)


def test_near_zero_uncertainty_denominator_rejected() -> None:
    with pytest.raises(ValueError, match="nonzero"):
        propagate_metrics(0.0, 997.0, 4180.0, 1.0, 24.0, 0.0, 100.0)


def test_darcy_convention_and_parallel_mass_conservation() -> None:
    assert rectangular_darcy_friction_reynolds(0.004, 0.004) == pytest.approx(56.9184, rel=2e-4)
    geometry = load_geometry()
    result = parallel_network(geometry, "FI-200", 1.0, 25.0)
    assert result.branch_flow_lpm is not None
    assert sum(result.branch_flow_lpm) == pytest.approx(1.0, abs=1e-8)
    assert max(result.branch_flow_lpm) - min(result.branch_flow_lpm) > 0.01


def test_thermal_energy_conservation_and_uniform_limit() -> None:
    geometry = load_geometry()
    inputs = ThermalInputs(grid_size=15)
    result = solve_two_layer(geometry, inputs, "uniform")
    analytical_payload, analytical_cover = uniform_lumped_solution(geometry, inputs)
    assert result.energy_residual_w == pytest.approx(0.0, abs=1e-8)
    assert np.nanmean(result.payload_temperature_c) == pytest.approx(analytical_payload, abs=1e-8)
    assert np.nanmean(result.cover_temperature_c) == pytest.approx(analytical_cover, abs=1e-8)


def test_thermal_grid_convergence() -> None:
    geometry = load_geometry()
    means = []
    # A disk on a Cartesian mesh converges with a small staircase oscillation,
    # so compare successively finer grids instead of demanding monotonic error.
    for grid in (35, 45, 61):
        result = solve_two_layer(geometry, ThermalInputs(grid_size=grid), "broad")
        means.append(float(np.nanmean(result.payload_temperature_c)))
    assert abs(means[-1] - means[-2]) < abs(means[-1] - means[-3])
    assert max(means) - min(means) < 0.04
