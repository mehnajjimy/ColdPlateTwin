"""Independent reproductions of the September 17 review failures."""

from dataclasses import asdict, replace
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from coldplatetwin.analysis import analyze_run
from coldplatetwin.bundle import analyze_files, load_bundles, matched_comparisons
from coldplatetwin.configuration import AnalysisConfig, load_config
from coldplatetwin.demo import _make_doe
from coldplatetwin.geometry import load_geometry
from coldplatetwin.hydraulics import parallel_network, predict_hydraulics
from coldplatetwin.io import read_measurement_csv
from coldplatetwin.metrics import evaluate_metrics, metric_jacobian
from coldplatetwin.properties import enthalpy_rise_j_kg, water_properties
from coldplatetwin.schemas import CalibrationCorrelation, CameraMetadata, RunMetadata, SensorSpec, Synchronization
from coldplatetwin.steady import find_steady_state, time_weights
from coldplatetwin.thermal import solve_two_layer, ThermalInputs
from coldplatetwin.uncertainty import difference_standard_uncertainty


@pytest.fixture
def constant_frame():
    t = np.arange(481)
    return pd.DataFrame({
        "timestamp": pd.Timestamp("2026-01-01T00:00:00Z") + pd.to_timedelta(t, unit="s"),
        "flow_lpm": 1.0, "tin_c": 25.0, "tout_c": 27.0, "dp_pa": 1000.0,
        "ambient_c": 22.0, "heater_voltage_v": 24.0, "heater_current_a": 7.5,
        "surface_reference_1_c": 32.0,
    })


@pytest.fixture
def metadata():
    specifications = [
        ("flow_lpm", .005, "L/min", "flow"), ("tin_c", .05, "K", "pair"),
        ("tout_c", .05, "K", "pair"), ("dp_pa", 25, "Pa", "pressure"),
        ("heater_voltage_v", .02, "V", "voltage"), ("heater_current_a", .01, "A", "current"),
    ]
    return RunMetadata(
        run_id="EXP-fixture", insert_id="FI-200", geometry_hash="a"*64, source="experimental",
        started_at="2026-01-01T00:00:00Z",
        sensors=[SensorSpec(channel, "test fixture", calibration, u, unit) for channel, u, unit, calibration in specifications],
        calibration_correlations=[CalibrationCorrelation("tin_c", "tout_c", .65)],
        camera=CameraMetadata("ir", .95, 22, True, .5, .04),
        synchronization=Synchronization(maximum_channel_skew_s=.05),
        electrical_power_mode="dc")


@pytest.mark.parametrize("defect", ["step", "averaging_gaps", "screen_missing", "surface_drift",
                                    "averaging_power", "averaging_flow", "pressure_missing", "ambient_missing"])
def test_bad_steady_state_is_rejected(constant_frame, defect):
    frame = constant_frame.copy()
    if defect == "step":
        frame.loc[301:, "tout_c"] += 10
    elif defect == "averaging_gaps":
        frame = frame[(frame.index <= 300) | frame.index.isin([301, 390, 480])]
    elif defect == "screen_missing":
        frame.loc[2:298, ["tin_c", "tout_c", "flow_lpm"]] = np.nan
    elif defect == "surface_drift":
        frame["surface_reference_1_c"] += np.arange(481)/60
    elif defect == "averaging_power":
        frame.loc[301:, "heater_current_a"] += np.sin(np.arange(180)) * 2
    elif defect == "averaging_flow":
        frame.loc[301:, "flow_lpm"] += .2
    else:
        frame.loc[301:, "dp_pa" if defect == "pressure_missing" else "ambient_c"] = np.nan
    result = find_steady_state(frame)
    assert not result.passed, result
    assert result.reasons


def test_irregular_stable_samples_and_time_weighted_mean(constant_frame, metadata):
    frame = constant_frame.drop(index=np.arange(2, 480, 3))
    assert find_steady_state(frame).passed
    weights = time_weights(np.array([0., 1., 4.]), np.ones(3, bool), 5)
    assert weights @ np.array([0., 2., 2.]) / weights.sum() == pytest.approx(1.75)
    result = analyze_run(frame, metadata.run_id, metadata.insert_id, metadata.source, metadata=metadata)
    expected = water_properties(25).density_kg_m3 / 60000 * enthalpy_rise_j_kg(25, 27)
    assert result.metrics["heat_to_water_enthalpy_w"] == pytest.approx(expected)
    assert result.uncertainties["heat_to_water_enthalpy_w"]["value"] == pytest.approx(expected)


@pytest.mark.parametrize("field,value", [
    ("flow_unit", "mL/min"), ("pressure_unit", "kPa"), ("temperature_unit", "K"),
    ("insert_id", "FI-999"), ("geometry_hash", ""), ("started_at", "2026-01-01T00:00:00"),
])
def test_invalid_metadata_is_rejected(metadata, field, value):
    setattr(metadata, field, value)
    with pytest.raises(ValueError):
        metadata.validate()


def test_covariance_and_sensor_validation(metadata):
    metadata.calibration_correlations[0].correlation = 1.1
    with pytest.raises(ValueError, match="correlation"):
        metadata.validate()
    metadata.calibration_correlations[0].correlation = .65
    metadata.sensors[0].uncertainty_unit = "mL/min"
    with pytest.raises(ValueError, match="uncertainty_unit"):
        metadata.validate()


@pytest.mark.parametrize("bad", ["oops", np.inf])
def test_invalid_numeric_is_not_silently_missing(tmp_path, constant_frame, bad):
    frame = constant_frame.copy()
    frame["flow_lpm"] = frame.flow_lpm.astype(object)
    frame.loc[30, "flow_lpm"] = bad
    frame.to_csv(tmp_path/"raw.csv", index=False)
    with pytest.raises(ValueError):
        read_measurement_csv(tmp_path/"raw.csv")


def test_metadata_uncertainty_changes_analysis_100fold(tmp_path, constant_frame, metadata):
    constant_frame.to_csv(tmp_path/"raw.csv", index=False)
    metadata.write_json(tmp_path/"meta.json")
    first = analyze_files(tmp_path/"raw.csv", tmp_path/"meta.json", tmp_path/"first")
    for sensor in metadata.sensors:
        sensor.standard_uncertainty *= 100
    metadata.write_json(tmp_path/"meta.json")
    second = analyze_files(tmp_path/"raw.csv", tmp_path/"meta.json", tmp_path/"second")
    key = "heat_to_water_enthalpy_w"
    assert second["uncertainties"][key]["analytical_standard"] > 95 * first["uncertainties"][key]["analytical_standard"]
    assert second["uncertainties"][key]["monte_carlo_valid_fraction"] < 1


def test_missing_experimental_uncertainty_is_explicit(constant_frame, metadata):
    metadata.sensors = []
    metadata.calibration_correlations = []
    result = analyze_run(constant_frame, metadata.run_id, metadata.insert_id, metadata.source, metadata=metadata)
    assert result.uncertainties == {}
    assert any("missing sensor" in warning for warning in result.warnings)


def test_rectangular_bounds_are_converted(constant_frame, metadata):
    metadata.sensors[0].distribution = "rectangular"
    metadata.sensors[0].stated_bound = .03
    result = analyze_run(constant_frame, metadata.run_id, metadata.insert_id, metadata.source, metadata=metadata)
    effects = result.uncertainties["hydraulic_power_w"]["shared_standard_effects"]
    assert effects["flow:flow_lpm"] == pytest.approx(1000/60000 * .03/np.sqrt(3))


def test_calibration_error_does_not_shrink_with_sample_count(constant_frame, metadata):
    dense = analyze_run(constant_frame, metadata.run_id, metadata.insert_id, metadata.source, metadata=metadata)
    sparse = analyze_run(constant_frame.iloc[::2], metadata.run_id, metadata.insert_id, metadata.source, metadata=metadata)
    for key in dense.uncertainties:
        assert dense.uncertainties[key]["analytical_standard"] == pytest.approx(sparse.uncertainties[key]["analytical_standard"])
    u = dense.uncertainties["unaccounted_energy_residual_w"]
    assert difference_standard_uncertainty(u, u) == pytest.approx(0, abs=1e-7)


def test_ir_bundle_selects_accepted_frames_and_propagates_resistance(tmp_path, constant_frame, metadata):
    constant_frame.to_csv(tmp_path/"raw.csv", index=False)
    raw_bytes = (tmp_path/"raw.csv").read_bytes()
    metadata.write_json(tmp_path/"meta.json")
    rows = [[str(constant_frame.timestamp.iloc[t]), *([temperature]*9)]
            for t, temperature in [(100, 20), (350, 30), (400, 34), (480, 32)]]
    rows.append(["2026-01-01T00:08:20Z", *([99]*9)])
    pd.DataFrame(rows).to_csv(tmp_path/"ir.csv", index=False, header=False)
    (tmp_path/"parser.json").write_text(json.dumps({"timestamp_column": 0, "data_start_column": 1, "width": 3, "height": 3}))
    (tmp_path/"roi.json").write_text(json.dumps({"diameter_mm": 2, "pixel_size_mm": 1}))
    result = analyze_files(tmp_path/"raw.csv", tmp_path/"meta.json", tmp_path/"run.json",
                           ir_path=tmp_path/"ir.csv", ir_config_path=tmp_path/"parser.json", roi_config_path=tmp_path/"roi.json")
    assert result["roi"]["mean_c"] == pytest.approx(32)
    assert result["artifacts"]["radiometric"]["accepted_frame_indices"] == [1, 2, 3]
    assert (tmp_path/"raw.csv").read_bytes() == raw_bytes
    assert result["provenance"]["metadata"]["geometry_hash"] == "a"*64
    for key in ("unaccounted_energy_residual_w", "energy_closure_ratio_heat_to_water_over_electrical",
                "apparatus_resistance_roi_mean_minus_inlet_over_electrical_k_w",
                "water_normalized_resistance_roi_mean_minus_inlet_over_heat_to_water_k_w"):
        u = result["uncertainties"][key]
        assert u["analytical_standard"] > 0
        assert u["monte_carlo_standard"] == pytest.approx(u["analytical_standard"], rel=.08)
        assert u["value"] == pytest.approx(result["metrics"][key])
    loaded, root = load_bundles(tmp_path/"run.json")[0]
    assert (root/loaded["artifacts"]["calibrated_csv"]).exists()
    metadata.camera.absolute_accuracy_standard_uncertainty_k = 5
    metadata.write_json(tmp_path/"meta.json")
    larger = analyze_files(tmp_path/"raw.csv", tmp_path/"meta.json", tmp_path/"large",
                           ir_path=tmp_path/"ir.csv", ir_config_path=tmp_path/"parser.json", roi_config_path=tmp_path/"roi.json")
    key = "apparatus_resistance_roi_mean_minus_inlet_over_electrical_k_w"
    assert larger["uncertainties"][key]["analytical_standard"] > 9*result["uncertainties"][key]["analytical_standard"]


def test_analytic_jacobian_matches_same_estimator():
    values = np.array([[1., 24., 27., 23., 7., 900.], [1.1, 24.5, 27.5, 25., 8., 1100.]])
    weights = np.array([.3, .7])
    jacobian = metric_jacobian(values, weights, 33)
    for i in range(9):
        error = np.zeros((1, 9))
        error[0, i] = 1e-5
        numerical = (evaluate_metrics(values, weights, 33, errors=error) -
                     evaluate_metrics(values, weights, 33, errors=-error))[0] / 2e-5
        assert jacobian[:, i] == pytest.approx(numerical, abs=1e-6, rel=2e-4)


def test_cad_parameter_changes_reach_models(tmp_path):
    geometry = load_geometry()
    source = Path(geometry.source_path).read_text()
    config = tmp_path/"config.py"
    config.write_text(source.replace("fi200_channel_width: float = 8.0", "fi200_channel_width: float = 12.0"))
    wider = load_geometry(config)
    assert wider.parallel_channel_width_m == .012
    assert parallel_network(wider, "FI-200", 1, 25).screening_pressure_drop_pa < parallel_network(geometry, "FI-200", 1, 25).screening_pressure_drop_pa
    assert predict_hydraulics(wider, "FI-100", .5) == predict_hydraulics(geometry, "FI-100", .5)
    larger_port = replace(geometry, drilled_passage_diameter_m=.008)
    assert predict_hydraulics(larger_port, "FI-000", 1).screening_pressure_drop_pa < predict_hydraulics(geometry, "FI-000", 1).screening_pressure_drop_pa
    original = solve_two_layer(geometry)
    small_heater = solve_two_layer(replace(geometry, heater_diameter_m=.12))
    assert np.nanmax(small_heater.payload_temperature_c) > np.nanmax(original.payload_temperature_c)


def test_network_rejects_failed_solver(monkeypatch):
    import coldplatetwin.hydraulics as hydraulics
    real_solver = hydraulics.least_squares
    def failed(*args, **kwargs):
        result = real_solver(*args, **kwargs)
        result.success = False
        return result
    monkeypatch.setattr(hydraulics, "least_squares", failed)
    with pytest.raises(RuntimeError, match="converge"):
        hydraulics.parallel_network(load_geometry(), "FI-200", 1, 25)


def test_configured_loss_coefficients_change_prediction(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"hydraulic": {"bend_k": 1.0}}))
    config = load_config(path)
    geometry = load_geometry()
    baseline = predict_hydraulics(geometry, "FI-100", .5)
    changed = predict_hydraulics(geometry, "FI-100", .5, inputs=config.hydraulic)
    assert changed.screening_pressure_drop_pa > baseline.screening_pressure_drop_pa
    with pytest.raises(ValueError):
        predict_hydraulics(geometry, "FI-100", np.nan)


def test_config_is_loaded_and_doe_keeps_blocks(tmp_path, constant_frame):
    path = tmp_path/"config.json"
    path.write_text(json.dumps({"seed": 12, "steady_state": {"screening_window_s": 600},
                               "doe": {"flow_lpm": [.7, 1.2], "heater_power_w": [110], "replicated_blocks": 3}}))
    config = load_config(path)
    assert not find_steady_state(constant_frame, config.steady_state).passed
    table = _make_doe(tmp_path/"doe.csv", config.seed, config)
    operating = table[table.purpose == "proposed_operating_doe"]
    assert len(operating) == 3*4*2
    assert operating.block.is_monotonic_increasing
    assert set(operating.flow_lpm) == {.7, 1.2}
    assert (table.tail(4).purpose == "wider_development_envelope").all()
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path/"missing.json")


def test_thermal_fine_pattern_is_attenuated_across_grids():
    geometry = load_geometry()
    records = []
    for n in (45, 61, 81):
        inputs = ThermalInputs(grid_size=n)
        baseline = solve_two_layer(geometry, inputs)
        broad = solve_two_layer(geometry, inputs, "broad")
        fine = solve_two_layer(geometry, inputs, "fine")
        broad_response = np.nanstd(broad.payload_temperature_c-baseline.payload_temperature_c)
        fine_response = np.nanstd(fine.payload_temperature_c-baseline.payload_temperature_c)
        assert fine_response < broad_response/5
        records.append([np.nanmax(broad.payload_temperature_c), np.nanstd(broad.payload_temperature_c),
                        np.nanmax(broad.payload_temperature_c)-np.nanmin(broad.payload_temperature_c), fine_response])
    assert np.abs(np.array(records[-1])-records[-2]) == pytest.approx(np.zeros(4), abs=.06)


def test_calibrated_values_are_validated(tmp_path, constant_frame, metadata):
    constant_frame.to_csv(tmp_path/"raw.csv", index=False)
    metadata.sensors[0].calibration_offset = -10
    metadata.write_json(tmp_path/"meta.json")
    with pytest.raises(ValueError, match="flow_lpm"):
        analyze_files(tmp_path/"raw.csv", tmp_path/"meta.json", tmp_path/"result")


def test_untimed_ir_is_viewable_but_excluded(tmp_path, constant_frame, metadata):
    constant_frame.to_csv(tmp_path/"raw.csv", index=False)
    metadata.write_json(tmp_path/"meta.json")
    pd.DataFrame([[32]*9]).to_csv(tmp_path/"ir.csv", header=False, index=False)
    (tmp_path/"parser.json").write_text(json.dumps({"width":3,"height":3}))
    (tmp_path/"roi.json").write_text(json.dumps({"diameter_mm":2,"pixel_size_mm":1}))
    result = analyze_files(tmp_path/"raw.csv", tmp_path/"meta.json", tmp_path/"result",
                           ir_path=tmp_path/"ir.csv", ir_config_path=tmp_path/"parser.json", roi_config_path=tmp_path/"roi.json")
    assert result["roi"] is None
    assert result["artifacts"]["radiometric"]["timestamps"] is None
    assert result["artifacts"]["radiometric"]["accepted_frame_indices"] == []


def test_demo_config_changes_seed_models_and_doe(tmp_path):
    from coldplatetwin.demo import run_demo
    config = AnalysisConfig(seed=4, monte_carlo_samples=200, demo_flow_lpm=.8, demo_power_w=100,
                            thermal=ThermalInputs(grid_size=15, heater_power_w=100))
    config.doe.flow_lpm = [.8]
    config.doe.heater_power_w = [100]
    config.doe.replicated_blocks = 1
    summary = run_demo(tmp_path/"demo", config)
    truth_path = next((tmp_path/"demo/data/synthetic").glob("*FI-000*truth.json"))
    truth = json.loads(truth_path.read_text())
    assert truth["seed"] == 4 and truth["nominal_flow_lpm"] == .8
    assert summary["doe_rows"] == 8
    thermal = json.loads((tmp_path/"demo/results/thermal_summary.json").read_text())
    assert thermal["heat_to_coolant_w"] + thermal["heat_to_environment_w"] == pytest.approx(100)


def test_demo_with_no_accepted_runs_still_exports_reasons(tmp_path):
    from coldplatetwin.demo import run_demo
    from coldplatetwin.steady import SteadyStateConfig
    config = AnalysisConfig(steady_state=SteadyStateConfig(screening_window_s=2000),
                            thermal=ThermalInputs(grid_size=7), monte_carlo_samples=100)
    summary = run_demo(tmp_path/"rejected", config)
    assert summary["valid_run_count"] == 0
    assert len(summary["run_bundles"]) == 5
