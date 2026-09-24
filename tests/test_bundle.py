"""the analysis bundle: logger plus infrared frames in, result.json and its files out."""

import json

import pandas as pd
import pytest

from coldplatetwin.bundle import analyze_files, load_bundles


def test_ir_bundle_uses_only_timed_frames_inside_the_steady_window(tmp_path, constant_frame, metadata):
    """catches ir frames outside the steady window or without timestamps being used, or lost roi uncertainty."""
    constant_frame.to_csv(tmp_path / "raw.csv", index=False)
    raw_bytes = (tmp_path / "raw.csv").read_bytes()
    metadata.write_json(tmp_path / "meta.json")
    parser = tmp_path / "parser.json"
    parser.write_text(json.dumps({"timestamp_column": 0, "data_start_column": 1, "width": 3, "height": 3}))
    roi = tmp_path / "roi.json"
    roi.write_text(json.dumps({"diameter_mm": 2, "pixel_size_mm": 1}))

    # the averaging window is 300-480 s. frames at 100 s and 500 s are outside it,
    # so the roi mean is the mean of 30, 34 and 32 degc, the last one on the window edge
    rows = []
    for second, temperature in [(100, 20), (350, 30), (400, 34), (480, 32)]:
        rows.append([str(constant_frame.timestamp.iloc[second]), *([temperature] * 9)])
    rows.append(["2026-01-01T00:08:20Z", *([99] * 9)])
    pd.DataFrame(rows).to_csv(tmp_path / "ir.csv", index=False, header=False)
    ir = {"ir_path": tmp_path / "ir.csv", "ir_config_path": parser, "roi_config_path": roi}

    result = analyze_files(tmp_path / "raw.csv", tmp_path / "meta.json", tmp_path / "run.json", **ir)
    assert result["artifacts"]["radiometric"]["accepted_frame_indices"] == [1, 2, 3]
    assert result["roi"]["mean_c"] == pytest.approx(32)
    assert (tmp_path / "raw.csv").read_bytes() == raw_bytes
    assert result["provenance"]["metadata"]["geometry_hash"] == "a" * 64

    # every roi-based metric carries an uncertainty, and monte carlo agrees with the analysis
    for key in ("unaccounted_energy_residual_w", "energy_closure_ratio_heat_to_water_over_electrical",
                "apparatus_resistance_roi_mean_minus_inlet_over_electrical_k_w",
                "water_normalized_resistance_roi_mean_minus_inlet_over_heat_to_water_k_w"):
        record = result["uncertainties"][key]
        assert record["analytical_standard"] > 0
        assert record["monte_carlo_standard"] == pytest.approx(record["analytical_standard"], rel=0.08)
        assert record["value"] == pytest.approx(result["metrics"][key])

    # the .json output points into its bundle folder
    loaded, folder = load_bundles(tmp_path / "run.json")[0]
    assert (folder / loaded["artifacts"]["calibrated_csv"]).exists()

    # a camera accuracy of 5 k instead of 0.5 k must widen the resistance uncertainty
    metadata.camera.absolute_accuracy_standard_uncertainty_k = 5
    metadata.write_json(tmp_path / "meta.json")
    larger = analyze_files(tmp_path / "raw.csv", tmp_path / "meta.json", tmp_path / "large", **ir)
    key = "apparatus_resistance_roi_mean_minus_inlet_over_electrical_k_w"
    assert larger["uncertainties"][key]["analytical_standard"] > 9 * result["uncertainties"][key]["analytical_standard"]

    # frames without timestamps are saved for viewing but never used for the roi
    parser.write_text(json.dumps({"width": 3, "height": 3}))
    pd.DataFrame([[32] * 9]).to_csv(tmp_path / "ir.csv", header=False, index=False)
    untimed = analyze_files(tmp_path / "raw.csv", tmp_path / "meta.json", tmp_path / "untimed", **ir)
    assert untimed["roi"] is None
    assert untimed["artifacts"]["radiometric"]["timestamps"] is None
    assert untimed["artifacts"]["radiometric"]["accepted_frame_indices"] == []
    assert any("IR timestamps absent" in warning for warning in untimed["warnings"])
