"""hand-worked checks of the physics: water, calorimetry, uncertainty, steady state, roi and models."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from coldplatetwin.analysis import analyze_run
from coldplatetwin.geometry import load_geometry
from coldplatetwin.hydraulics import parallel_network, predict_hydraulics, rectangular_darcy_friction_reynolds
from coldplatetwin.metrics import evaluate_metrics, metric_jacobian
from coldplatetwin.properties import enthalpy_rise_j_kg, water_properties
from coldplatetwin.roi import circular_roi_statistics
from coldplatetwin.steady import find_steady_state, time_weights
from coldplatetwin.thermal import ThermalInputs, solve_two_layer, uniform_lumped_solution
from coldplatetwin.uncertainty import (
    UncertaintyInputs,
    delta_t_standard,
    difference_standard_uncertainty,
    propagate_metrics,
)

# heat to water for the constant run in conftest:
# rho(25 degc) * 1 l/min * (h(27) - h(25)) = 997.05 * (1 / 60000) * 8359.2 = 138.909006 w
CONSTANT_RUN_HEAT_W = 138.909006


# --- water properties and calorimetry ---

def test_water_table_and_enthalpy_rise_match_hand_integration():
    """catches a wrong table value, a wrong enthalpy integral or glycol being accepted."""
    water = water_properties(20.0)
    assert water.density_kg_m3 == pytest.approx(998.21)
    assert water.cp_j_kg_k == pytest.approx(4182.0)
    # cp is 4182, 4180 and 4178 at 20, 25 and 30 degc and linear between,
    # so each 5 k step is 5 * mean cp: 20905 then 20895 j/kg
    assert enthalpy_rise_j_kg(20.0, 25.0) == pytest.approx(20905.0)
    assert enthalpy_rise_j_kg(20.0, 30.0) == pytest.approx(41800.0)
    # inside one segment: cp goes 4180 -> 4179.2 from 25 to 27 degc, so 2 * 4179.6
    assert enthalpy_rise_j_kg(25.0, 27.0) == pytest.approx(8359.2)
    with pytest.raises(ValueError, match="pure water"):
        water_properties(25.0, fluid="water-glycol")


def test_constant_run_gives_hand_worked_heat_power_and_energy_balance(constant_frame, metadata):
    """catches wrong calorimetry, density taken at the wrong sensor, or a wrong energy balance."""
    run = (metadata.run_id, metadata.insert_id, metadata.source)
    result = analyze_run(constant_frame, *run, metadata=metadata)
    metrics = result.metrics
    assert metrics["heat_to_water_enthalpy_w"] == pytest.approx(CONSTANT_RUN_HEAT_W)
    assert metrics["electrical_power_synchronized_vi_w"] == pytest.approx(180.0)
    assert metrics["hydraulic_power_w"] == pytest.approx(1000.0 / 60000)
    assert metrics["delta_t_k"] == pytest.approx(2.0)
    assert metrics["unaccounted_energy_residual_w"] == pytest.approx(180.0 - CONSTANT_RUN_HEAT_W)
    assert metrics["energy_closure_ratio_heat_to_water_over_electrical"] == pytest.approx(CONSTANT_RUN_HEAT_W / 180.0)
    assert metrics["mass_flow_kg_s"] == pytest.approx(997.05 / 60000)
    # no roi was given, so there is no thermal resistance
    assert metrics["apparatus_resistance_roi_mean_minus_inlet_over_electrical_k_w"] is None
    assert result.uncertainties["heat_to_water_enthalpy_w"]["value"] == pytest.approx(CONSTANT_RUN_HEAT_W)

    # a flowmeter at the outlet uses rho(27 degc) = 997.05 - 2 * 0.28 = 996.49
    metadata.flow_measurement_location = "outlet"
    outlet = analyze_run(constant_frame, *run, metadata=metadata)
    assert outlet.metrics["heat_to_water_enthalpy_w"] == pytest.approx(996.49 / 60000 * 8359.2)


# --- uncertainty ---

def test_analytic_jacobian_matches_finite_differences():
    """catches a wrong analytical derivative in the uncertainty propagation."""
    values = np.array([[1.0, 24.0, 27.0, 23.0, 7.0, 900.0], [1.1, 24.5, 27.5, 25.0, 8.0, 1100.0]])
    weights = np.array([0.3, 0.7])
    jacobian = metric_jacobian(values, weights, 33)
    # central difference on each of the nine shared errors
    for i in range(9):
        error = np.zeros((1, 9))
        error[0, i] = 1e-5
        plus = evaluate_metrics(values, weights, 33, errors=error)
        minus = evaluate_metrics(values, weights, 33, errors=-error)
        numerical = (plus - minus)[0] / 2e-5
        assert jacobian[:, i] == pytest.approx(numerical, abs=1e-6, rel=2e-4)


def test_bench_uncertainty_keeps_rtd_covariance():
    """catches a wrong sign on the paired rtd covariance or monte carlo disagreeing with the analysis."""
    # 0.05 k on each rtd. independent: sqrt(2 * 0.05**2) = 0.0707107 k
    assert delta_t_standard(UncertaintyInputs(rtd_correlation=0.0)) == pytest.approx(0.0707107, rel=1e-5)
    # correlation 0.8: sqrt(2 * 0.0025 - 2 * 0.8 * 0.0025) = sqrt(0.001) = 0.0316228 k
    assert delta_t_standard(UncertaintyInputs(rtd_correlation=0.8)) == pytest.approx(0.0316228, rel=1e-5)
    result = propagate_metrics(1.0, 997.0, 4180.0, 2.0, 24.0, 7.5, 1000.0, samples=30_000)
    # power = v * i: sqrt((7.5 * 0.02)**2 + (24 * 0.01)**2) = sqrt(0.0801) = 0.283019 w
    assert result["electrical_power_w"]["analytical_standard"] == pytest.approx(0.283019, rel=1e-5)
    for metric in result.values():
        assert metric["monte_carlo_standard"] == pytest.approx(metric["analytical_standard"], rel=0.04)
    with pytest.raises(ValueError, match="nonzero"):
        propagate_metrics(0.0, 997.0, 4180.0, 1.0, 24.0, 0.0, 100.0)


def test_sensor_uncertainty_is_run_constant_and_read_from_metadata(constant_frame, metadata):
    """catches a wrong rectangular conversion, uncertainty shrinking with sample count, or invented defaults."""
    run = (metadata.run_id, metadata.insert_id, metadata.source)
    # a rectangular +-0.03 l/min bound is 0.03 / sqrt(3) standard. hydraulic
    # power is dp * q, so the flow effect is 1000 pa / 60000 * 0.03 / sqrt(3)
    metadata.sensors[0].distribution = "rectangular"
    metadata.sensors[0].stated_bound = 0.03
    dense = analyze_run(constant_frame, *run, metadata=metadata)
    effects = dense.uncertainties["hydraulic_power_w"]["shared_standard_effects"]
    assert effects["flow:flow_lpm"] == pytest.approx(1000 / 60000 * 0.03 / np.sqrt(3))

    # calibration errors are shared by every sample, so half the samples give the same answer
    sparse = analyze_run(constant_frame.iloc[::2], *run, metadata=metadata)
    for name, record in dense.uncertainties.items():
        assert sparse.uncertainties[name]["analytical_standard"] == pytest.approx(record["analytical_standard"])

    # a run compared with itself shares every error, so the difference has none
    residual = dense.uncertainties["unaccounted_energy_residual_w"]
    assert difference_standard_uncertainty(residual, residual) == pytest.approx(0, abs=1e-7)

    # without sensor records no uncertainty is claimed, and a warning says why
    metadata.sensors = []
    metadata.calibration_correlations = []
    missing = analyze_run(constant_frame, *run, metadata=metadata)
    assert missing.uncertainties == {}
    assert any("missing sensor" in warning for warning in missing.warnings)


# --- steady state ---

def test_steady_state_weights_and_rejection_reasons(constant_frame):
    """catches averaging across long gaps, and accepting a window that steps, drifts or loses channels."""
    # trapezoid weights: each neighbouring pair gives half its gap to both samples
    times = np.array([0.0, 1.0, 4.0])
    complete = np.ones(3, dtype=bool)
    assert time_weights(times, complete, 5.0) == pytest.approx([0.5, 2.0, 1.5])
    # the 3 s gap is longer than 2 s, so that pair adds nothing
    assert time_weights(times, complete, 2.0) == pytest.approx([0.5, 0.5, 0.0])
    # a missing middle sample breaks both pairs
    assert time_weights(times, np.array([True, False, True]), 5.0) == pytest.approx([0.0, 0.0, 0.0])

    # a clean run logged at irregular times still passes
    assert find_steady_state(constant_frame.drop(index=np.arange(2, 480, 3))).passed

    # rows 0-300 are the screen and rows 300-480 the average. each defect must fail with a reason
    defects = {}
    frame = constant_frame.copy()
    frame.loc[301:, "tout_c"] += 10
    defects["outlet step"] = frame
    defects["gaps while averaging"] = constant_frame[(constant_frame.index <= 300) | constant_frame.index.isin([301, 390, 480])]
    frame = constant_frame.copy()
    frame.loc[2:298, ["tin_c", "tout_c", "flow_lpm"]] = np.nan
    defects["screen data missing"] = frame
    frame = constant_frame.copy()
    frame["surface_reference_1_c"] += np.arange(481) / 60
    defects["surface drift of 1 k/min"] = frame
    frame = constant_frame.copy()
    frame.loc[301:, "heater_current_a"] += np.sin(np.arange(180)) * 2
    defects["noisy power"] = frame
    frame = constant_frame.copy()
    frame.loc[301:, "flow_lpm"] += 0.2
    defects["flow step"] = frame
    for channel in ("dp_pa", "ambient_c"):
        frame = constant_frame.copy()
        frame.loc[301:, channel] = np.nan
        defects[channel + " missing"] = frame
    for name, frame in defects.items():
        result = find_steady_state(frame)
        assert not result.passed, name
        assert result.reasons, name


# --- radiometric roi ---

def test_circular_roi_counts_and_averages_the_right_pixels():
    """catches pixels on the circle edge being dropped, or invalid and occluded pixels being used."""
    # 5 x 5 image holding 0..24. a 4 px circle on the centre holds the 3 x 3
    # block plus the four pixels exactly 2 px away: 13 pixels
    image = np.arange(25, dtype=float).reshape(5, 5)
    image[2, 2] = np.nan
    occlusion = np.zeros((5, 5), dtype=bool)
    occlusion[1, 2] = True
    result = circular_roi_statistics(image, roi_diameter_px=4.0, occlusion_mask=occlusion)
    assert result.total_roi_pixel_count == 13
    # the nan centre (12) and the occluded pixel (7) are left out
    assert result.valid_pixel_count == 11
    # 2 + 6 + 8 + 10 + 11 + 13 + 14 + 16 + 17 + 18 + 22 = 137
    assert result.mean_c == pytest.approx(137 / 11)
    assert result.maximum_c == 22
    assert result.peak_to_peak_k == 20


# --- reduced-order models ---

def test_hydraulic_models_match_hand_values_and_conserve_mass(tmp_path):
    """catches a wrong friction constant or port loss, flow lost in the network, or cad edits not reaching it."""
    # square duct: 96 * (1 - 1.3553 + 1.9467 - 1.7012 + 0.9564 - 0.2537) = 56.9184
    assert rectangular_darcy_friction_reynolds(0.004, 0.004) == pytest.approx(56.9184, rel=2e-4)
    geometry = load_geometry()
    # fi-000: k = 3 on the 6 mm port. 1 l/min gives v = 0.589463 m/s,
    # so dp = 3 * 997.05 * 0.589463**2 / 2 = 519.66 pa
    plenum = predict_hydraulics(geometry, "FI-000", 1.0)
    assert plenum.screening_pressure_drop_pa == pytest.approx(519.66, rel=1e-4)

    # fi-200: branch flows add back to the total, but they are not all equal
    network = parallel_network(geometry, "FI-200", 1.0, 25.0)
    assert sum(network.branch_flow_lpm) == pytest.approx(1.0, abs=1e-8)
    assert max(network.branch_flow_lpm) - min(network.branch_flow_lpm) > 0.01

    # widening the fi-200 channels in the cad config lowers the fi-200 drop and leaves fi-100 alone
    source = Path(geometry.source_path).read_text()
    config = tmp_path / "config.py"
    config.write_text(source.replace("fi200_channel_width: float = 8.0", "fi200_channel_width: float = 12.0"))
    wider = load_geometry(config)
    assert wider.parallel_channel_width_m == 0.012
    wider_network = parallel_network(wider, "FI-200", 1.0, 25.0)
    assert wider_network.screening_pressure_drop_pa < network.screening_pressure_drop_pa
    assert predict_hydraulics(wider, "FI-100", 0.5) == predict_hydraulics(geometry, "FI-100", 0.5)


def test_thermal_model_conserves_energy_and_damps_fine_patterns():
    """catches heat lost by the solver, a wrong uniform limit, or fine coolant patterns leaking to the surface."""
    geometry = load_geometry()
    # with uniform h the grid must match the two-node answer and lose no heat
    inputs = ThermalInputs(grid_size=15)
    uniform = solve_two_layer(geometry, inputs, "uniform")
    payload_c, cover_c = uniform_lumped_solution(geometry, inputs)
    assert uniform.energy_residual_w == pytest.approx(0.0, abs=1e-8)
    assert np.nanmean(uniform.payload_temperature_c) == pytest.approx(payload_c, abs=1e-8)
    assert np.nanmean(uniform.cover_temperature_c) == pytest.approx(cover_c, abs=1e-8)

    # the same power on a smaller heater makes a hotter peak
    baseline = solve_two_layer(geometry)
    small_heater = solve_two_layer(replace(geometry, heater_diameter_m=0.12))
    assert np.nanmax(small_heater.payload_temperature_c) > np.nanmax(baseline.payload_temperature_c)

    # the plate spreads heat, so a fine h pattern moves the surface far less than a broad one,
    # and the broad-pattern surface settles as the grid is refined
    records = []
    for n in (45, 61, 81):
        inputs = ThermalInputs(grid_size=n)
        plain = solve_two_layer(geometry, inputs).payload_temperature_c
        broad = solve_two_layer(geometry, inputs, "broad").payload_temperature_c
        fine = solve_two_layer(geometry, inputs, "fine").payload_temperature_c
        broad_response = np.nanstd(broad - plain)
        fine_response = np.nanstd(fine - plain)
        assert fine_response < broad_response / 5
        records.append([np.nanmax(broad), np.nanstd(broad), np.nanmax(broad) - np.nanmin(broad), fine_response])
    assert np.abs(np.array(records[-1]) - records[-2]) == pytest.approx(np.zeros(4), abs=0.06)
