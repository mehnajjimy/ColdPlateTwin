"""the dashboard's own app code, driven by streamlit's test runner instead of a browser."""

import json

import pandas as pd
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from coldplatetwin.bundle import analyze_files
from coldplatetwin.schemas import CameraMetadata, RunMetadata


def test_dashboard_switches_runs_and_handles_a_run_without_ir(tmp_path):
    """catches the dashboard crashing, hiding the experimental warning, or showing another run's ir frames."""
    # two experimental runs. only the first one has an ir frame
    t = pd.date_range("2026-01-01", periods=481, freq="s", tz="UTC")
    records = []
    for i in (0, 1):
        metadata = RunMetadata(run_id=f"EXP-{i}", source="experimental", insert_id="FI-200",
                               geometry_hash="a" * 64, started_at="2026-01-01T00:00:00Z",
                               camera=CameraMetadata("ir", 0.95, 22, True, 0.5, 0.04))
        metadata.write_json(tmp_path / f"metadata-{i}.json")
        source = tmp_path / f"raw-{i}.csv"
        pd.DataFrame({"timestamp": t, "flow_lpm": 1, "tin_c": 25 + i, "tout_c": 27 + i, "dp_pa": 1000,
                      "ambient_c": 22, "heater_voltage_v": 24, "heater_current_a": 7.5}).to_csv(source, index=False)
        ir = {}
        if i == 0:
            pd.DataFrame([[str(t[400]), *([32] * 9)]]).to_csv(tmp_path / "ir.csv", header=False, index=False)
            (tmp_path / "parser.json").write_text(json.dumps({"timestamp_column": 0, "data_start_column": 1, "width": 3, "height": 3}))
            (tmp_path / "roi.json").write_text(json.dumps({"diameter_mm": 2, "pixel_size_mm": 1}))
            ir = {"ir_path": tmp_path / "ir.csv", "ir_config_path": tmp_path / "parser.json",
                  "roi_config_path": tmp_path / "roi.json"}
        analyze_files(source, tmp_path / f"metadata-{i}.json", tmp_path / f"run-{i}", **ir)
        records.append({"result_file": f"run-{i}/result.json"})
    (tmp_path / "summary.json").write_text(json.dumps({"run_bundles": records}))

    app = AppTest.from_string(f"from coldplatetwin.dashboard import main\nmain({str(tmp_path)!r})")
    app.run(timeout=30)
    assert not app.exception
    # one box picks the run and one picks its ir frame
    assert len(app.selectbox) == 2
    assert any("EXPERIMENTAL" in warning.value for warning in app.warning)

    # the second run has no ir, so the frame picker goes away and a note says so
    app.selectbox[0].select("EXP-1").run(timeout=30)
    assert not app.exception
    assert len(app.selectbox) == 1
    assert any("No IR frames" in info.value for info in app.info)
