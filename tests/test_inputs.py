"""one test per input format: logger csv, radiometric csv, run metadata json and analysis config json."""

import json

import numpy as np
import pandas as pd
import pytest

from coldplatetwin.calibration import AffineCalibration, apply_calibrations
from coldplatetwin.configuration import load_config
from coldplatetwin.demo import _make_doe
from coldplatetwin.geometry import load_geometry
from coldplatetwin.hydraulics import predict_hydraulics
from coldplatetwin.io import RadiometricCSVConfig, read_measurement_csv, read_radiometric_csv
from coldplatetwin.schemas import RunMetadata
from coldplatetwin.steady import find_steady_state


def test_logger_csv_keeps_gaps_rejects_bad_rows_and_calibrates_a_copy(tmp_path, constant_frame):
    """catches bad logger rows being accepted, blanks being filled in, or calibration changing raw data."""
    path = tmp_path / "raw.csv"
    frame = constant_frame.copy()
    frame.loc[5, "dp_pa"] = np.nan
    frame.to_csv(path, index=False)
    raw = read_measurement_csv(path)
    assert np.isnan(raw.loc[5, "dp_pa"])
    assert str(raw.timestamp.dt.tz) == "UTC"

    # calibration shifts a copy: 25 - 0.04 = 24.96 degc, the raw table keeps 25
    calibrated = apply_calibrations(raw, [AffineCalibration("tin_c", "pair", offset=-0.04)])
    assert calibrated.tin_c.iloc[0] == pytest.approx(24.96)
    assert raw.tin_c.iloc[0] == 25.0
    # calibrated values get the same range checks as raw ones
    with pytest.raises(ValueError, match="flow_lpm"):
        apply_calibrations(raw, [AffineCalibration("flow_lpm", "flow", offset=-10.0)])

    # each broken file must be refused with a clear message
    bad_files = []
    bad_files.append((constant_frame.drop(columns="dp_pa"), "Missing required"))
    frame = constant_frame.copy()
    frame.loc[1, "timestamp"] = frame.loc[0, "timestamp"]
    bad_files.append((frame, "Duplicate"))
    frame = constant_frame.copy()
    frame["timestamp"] = frame.timestamp.dt.tz_localize(None)
    bad_files.append((frame, "explicit timezone"))
    for bad_value, message in (("oops", "Malformed"), (np.inf, "Infinite")):
        frame = constant_frame.copy()
        frame["flow_lpm"] = frame.flow_lpm.astype(object)
        frame.loc[30, "flow_lpm"] = bad_value
        bad_files.append((frame, message))
    for frame, message in bad_files:
        frame.to_csv(path, index=False)
        with pytest.raises(ValueError, match=message):
            read_measurement_csv(path)


def test_radiometric_csv_shape_mask_and_timestamps(tmp_path):
    """catches a wrong frame shape, the invalid marker being read as a temperature, or lost timing."""
    path = tmp_path / "ir.csv"
    # timestamp, frame number, then a 3 x 2 frame with one -9999 invalid marker
    path.write_text("2026-01-01T00:00:00Z,0,20,21,-9999,23,24,25\n")
    config = RadiometricCSVConfig(timestamp_column=0, frame_column=1, data_start_column=2, width=3, height=2)
    frames = read_radiometric_csv(path, config)
    assert frames.temperatures_c.shape == (1, 2, 3)
    assert frames.temperatures_c.mask.tolist() == [[[False, False, True], [False, False, False]]]
    assert frames.temperatures_c[0, 1, 2] == 25
    assert frames.timestamps[0] == pd.Timestamp("2026-01-01T00:00:00Z")
    assert frames.frame_ids.tolist() == [0]
    # six values cannot fill a 4 x 2 frame
    with pytest.raises(ValueError, match="Expected 8"):
        read_radiometric_csv(path, RadiometricCSVConfig(data_start_column=2, width=4, height=2))


def test_metadata_json_round_trips_and_rejects_unsafe_fields(tmp_path, metadata):
    """catches metadata with wrong units, ids, hashes, timezones or correlations being accepted."""
    path = tmp_path / "meta.json"
    metadata.write_json(path)
    assert RunMetadata.read_json(path) == metadata

    bad_fields = [
        ("flow_unit", "mL/min"),
        ("pressure_unit", "kPa"),
        ("temperature_unit", "K"),
        ("insert_id", "FI-999"),
        ("geometry_hash", ""),
        ("started_at", "2026-01-01T00:00:00"),
    ]
    for field, value in bad_fields:
        bad = RunMetadata.read_json(path)
        setattr(bad, field, value)
        with pytest.raises(ValueError):
            bad.validate()

    bad = RunMetadata.read_json(path)
    bad.calibration_correlations[0].correlation = 1.1
    with pytest.raises(ValueError, match="correlation"):
        bad.validate()
    bad = RunMetadata.read_json(path)
    bad.sensors[0].uncertainty_unit = "mL/min"
    with pytest.raises(ValueError, match="uncertainty_unit"):
        bad.validate()


def test_config_json_reaches_steady_state_hydraulics_and_doe(tmp_path, constant_frame):
    """catches config file settings being ignored by the steady-state check, the hydraulics or the doe."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "seed": 12,
        "steady_state": {"screening_window_s": 600},
        "hydraulic": {"bend_k": 1.0},
        "doe": {"flow_lpm": [0.7, 1.2], "heater_power_w": [110], "replicated_blocks": 3},
    }))
    config = load_config(path)

    # a 600 s screen plus a 180 s average cannot fit in an 8 minute run
    assert not find_steady_state(constant_frame, config.steady_state).passed

    # bend_k 0.35 -> 1.0 on the 8 fi-100 bends adds 0.65 * 8 = 5.2 velocity heads.
    # 0.5 l/min in the 8 x 4 mm channel is 0.260417 m/s, and one velocity head is
    # 997.05 * 0.260417**2 / 2 = 33.808 pa, so the drop rises by 175.80 pa
    geometry = load_geometry()
    baseline = predict_hydraulics(geometry, "FI-100", 0.5).screening_pressure_drop_pa
    changed = predict_hydraulics(geometry, "FI-100", 0.5, inputs=config.hydraulic).screening_pressure_drop_pa
    assert changed - baseline == pytest.approx(175.80, rel=1e-4)

    # 3 blocks of 4 inserts x 2 flows x 1 power, then 4 development rows
    table = _make_doe(tmp_path / "doe.csv", config.seed, config)
    operating = table[table.purpose == "proposed_operating_doe"]
    assert len(operating) == 3 * 4 * 2
    assert operating.block.is_monotonic_increasing
    assert set(operating.flow_lpm) == {0.7, 1.2}
    assert (table.tail(4).purpose == "wider_development_envelope").all()

    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.json")
