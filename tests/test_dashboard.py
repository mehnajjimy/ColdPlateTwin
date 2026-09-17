"""Exercise the dashboard's actual application code without a browser driver."""

from pathlib import Path
import json
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest
from coldplatetwin.bundle import analyze_files
from coldplatetwin.schemas import RunMetadata, CameraMetadata


def test_dashboard_switches_run_data_and_handles_missing_ir(tmp_path):
    records = []
    for i in (0, 1):
        metadata = RunMetadata(run_id=f"EXP-{i}", source="experimental", insert_id="FI-200",
                               geometry_hash="a"*64, started_at="2026-01-01T00:00:00Z",
                               camera=CameraMetadata("ir", .95, 22, True, .5, .04))
        source = tmp_path/f"raw-{i}.csv"
        t = pd.date_range("2026-01-01", periods=481, freq="s", tz="UTC")
        frame = pd.DataFrame({"timestamp": t, "flow_lpm": 1, "tin_c": 25+i, "tout_c": 27+i,
                              "dp_pa": 1000, "ambient_c": 22, "heater_voltage_v": 24, "heater_current_a": 7.5})
        frame.to_csv(source, index=False)
        metadata.write_json(tmp_path/f"metadata-{i}.json")
        kwargs = {}
        if i == 0:
            pd.DataFrame([[str(t[400]), *([32]*9)]]).to_csv(tmp_path/"ir.csv", header=False, index=False)
            (tmp_path/"parser.json").write_text(json.dumps({"timestamp_column":0,"data_start_column":1,"width":3,"height":3}))
            (tmp_path/"roi.json").write_text(json.dumps({"diameter_mm":2,"pixel_size_mm":1}))
            kwargs = dict(ir_path=tmp_path/"ir.csv", ir_config_path=tmp_path/"parser.json", roi_config_path=tmp_path/"roi.json")
        analyze_files(source, tmp_path/f"metadata-{i}.json", tmp_path/f"run-{i}", **kwargs)
        records.append({"result_file":f"run-{i}/result.json"})
    (tmp_path/"summary.json").write_text(json.dumps({"run_bundles": records}))
    app = AppTest.from_string(f"from coldplatetwin.dashboard import main\nmain({str(tmp_path)!r})")
    app.run(timeout=30)
    assert not app.exception
    assert len(app.selectbox) == 2  # Run and its own frame.
    assert any("EXPERIMENTAL" in warning.value for warning in app.warning)
    app.selectbox[0].select("EXP-1").run(timeout=30)
    assert not app.exception
    assert len(app.selectbox) == 1
    assert any("No IR frames" in info.value for info in app.info)
