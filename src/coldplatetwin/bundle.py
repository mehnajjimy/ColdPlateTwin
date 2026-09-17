"""Common logger + optional IR -> analysis bundle used by CLI and demo."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

from .analysis import analyze_run
from .calibration import apply_calibrations, calibrations_from_sensor_specs
from .configuration import AnalysisConfig
from .io import RadiometricCSVConfig, read_measurement_csv, read_radiometric_csv
from .roi import circular_roi_statistics
from .schemas import RunMetadata
from .steady import find_steady_state
from .uncertainty import difference_standard_uncertainty


def file_evidence(path):
    path = Path(path)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def write_json(path, data):
    """Strict JSON: NaN/Infinity may never masquerade as valid measurements."""
    Path(path).write_text(json.dumps(data, indent=2, default=str, allow_nan=False) + "\n")


def analyze_files(csv_path, metadata_path, output, config=None, *, ir_path=None, ir_config_path=None, roi_config_path=None):
    """Write a portable result bundle without changing raw input files."""
    config = config or AnalysisConfig()
    metadata = RunMetadata.read_json(metadata_path)
    raw = read_measurement_csv(csv_path)
    calibrated = apply_calibrations(raw, calibrations_from_sensor_specs(metadata.sensors))
    steady = find_steady_state(calibrated, config.steady_state)
    output = Path(output)
    bundle_dir = output.parent / output.stem if output.suffix == ".json" else output
    sources = [Path(p).resolve() for p in (csv_path, metadata_path, ir_path, ir_config_path, roi_config_path) if p]
    destinations = [output.resolve(), *(bundle_dir / name for name in ("result.json", "calibrated.csv", "radiometric.npz"))]
    if any(Path(path).resolve() in sources for path in destinations):
        raise ValueError("Output would overwrite a raw source file")
    bundle_dir.mkdir(parents=True, exist_ok=True)
    evidence = {"logger": file_evidence(csv_path), "metadata": file_evidence(metadata_path)}
    roi, ir_info, ir_warnings = None, None, []
    if ir_path:
        if not ir_config_path or not roi_config_path or metadata.camera is None:
            raise ValueError("IR analysis requires --ir-config, --roi-config and camera metadata")
        if not metadata.camera.export_is_temperature_corrected:
            raise ValueError("Uncorrected camera exports require vendor calibration; no correction is guessed")
        parsing = json.loads(Path(ir_config_path).read_text())
        parsing.pop("classification", None)
        frames = read_radiometric_csv(ir_path, RadiometricCSVConfig(**parsing))
        roi_config = json.loads(Path(roi_config_path).read_text())
        unknown = set(roi_config) - {"diameter_mm", "pixel_size_mm", "center_xy", "occlusion_mask_csv"}
        if unknown:
            raise ValueError(f"Unknown ROI configuration fields: {sorted(unknown)}")
        diameter = float(roi_config["diameter_mm"])
        pixel_size = float(roi_config["pixel_size_mm"])
        if not np.isfinite([diameter, pixel_size]).all() or min(diameter, pixel_size) <= 0:
            raise ValueError("ROI physical diameter and pixel scale must be positive")
        height, width = frames.temperatures_c.shape[1:]
        center = tuple(roi_config.get("center_xy", ((width-1)/2, (height-1)/2)))
        radius = diameter / pixel_size / 2
        if len(center) != 2 or min(center[0]+0.5, center[1]+0.5, width-0.5-center[0], height-0.5-center[1]) < radius:
            raise ValueError("The full circular ROI must lie inside the calibrated frame footprint")
        occlusion = None
        if roi_config.get("occlusion_mask_csv"):
            mask_path = Path(roi_config_path).parent / roi_config["occlusion_mask_csv"]
            occlusion = np.loadtxt(mask_path, delimiter=",")
            if not np.isin(occlusion, [0, 1]).all():
                raise ValueError("Occlusion mask must contain only 0/1")
            evidence["occlusion"] = file_evidence(mask_path)
        selected = np.array([], dtype=int)
        if frames.timestamps is not None and steady.passed:
            selected = np.flatnonzero((frames.timestamps >= steady.start) & (frames.timestamps <= steady.end))
        if len(selected):
            mean_map = np.ma.mean(frames.temperatures_c[selected], axis=0)
            roi = circular_roi_statistics(mean_map, diameter/pixel_size, center, occlusion)
        elif frames.timestamps is None:
            ir_warnings.append("IR timestamps absent: frames are viewable but excluded from steady thermal metrics.")
        else:
            ir_warnings.append("No IR frames lie inside an accepted averaging interval.")
        np.savez_compressed(bundle_dir / "radiometric.npz",
                            temperatures_c=frames.temperatures_c.filled(np.nan),
                            selected_indices=selected)
        ir_info = {
            "file": "radiometric.npz",
            "timestamps": [stamp.isoformat() for stamp in frames.timestamps] if frames.timestamps is not None else None,
            "accepted_frame_indices": selected.tolist(), "parser": parsing, "roi_config": roi_config,
            "aggregation": "equal-weight mean of available accepted temperature maps; no invented timing",
            "correction_applied_by_package": False,
        }
        ir_warnings.append("ROI metrics describe the sampled mean map; sparse IR frames do not establish continuous surface stability.")
        for name, path in (("radiometric", ir_path), ("radiometric_parser", ir_config_path), ("roi_config", roi_config_path)):
            evidence[name] = file_evidence(path)
    elif ir_config_path or roi_config_path:
        raise ValueError("IR/ROI configuration requires --ir")
    result = analyze_run(calibrated, metadata.run_id, metadata.insert_id, metadata.source,
                         roi=roi, metadata=metadata, config=config, steady_result=steady)
    result.warnings.extend(ir_warnings)
    result.provenance["input_files"] = evidence
    calibrated.to_csv(bundle_dir / "calibrated.csv", index=False)
    payload = result.as_dict()
    payload["bundle_version"] = "1.1"
    payload["artifacts"] = {"calibrated_csv": "calibrated.csv", "radiometric": ir_info}
    write_json(bundle_dir / "result.json", payload)
    if output.suffix == ".json":
        external = dict(payload)
        external["artifacts"] = {
            "calibrated_csv": f"{output.stem}/calibrated.csv",
            "radiometric": (dict(ir_info, file=f"{output.stem}/radiometric.npz") if ir_info else None),
        }
        write_json(output, external)
    return payload


def load_bundles(path):
    """Open one analysis JSON, a bundle directory, or a demo collection."""
    path = Path(path)
    if path.is_dir():
        path = path / ("summary.json" if (path / "summary.json").exists() else "result.json")
    content = json.loads(path.read_text())
    if "run_bundles" in content:
        return [(json.loads((path.parent / record["result_file"]).read_text()),
                 (path.parent / record["result_file"]).parent) for record in content["run_bundles"]]
    if content.get("bundle_version") != "1.1":
        raise ValueError("This result predates the corrected bundle schema; regenerate it")
    return [(content, path.parent)]


def matched_comparisons(results, config):
    """Compare only like source, geometry, flow, power and inlet conditions."""
    rows = []
    for i, first in enumerate(results):
        for second in results[i+1:]:
            if not first["steady_state"]["passed"] or not second["steady_state"]["passed"]:
                continue
            a, b = first["metrics"], second["metrics"]
            meta_a, meta_b = first["provenance"]["metadata"], second["provenance"]["metadata"]
            if first["source"] != second["source"] or meta_a["geometry_hash"] != meta_b["geometry_hash"]:
                continue
            limits = (("flow_lpm", config.comparison_flow_tolerance_lpm),
                      ("electrical_power_synchronized_vi_w", config.comparison_power_tolerance_w),
                      ("tin_c", config.comparison_inlet_tolerance_k))
            if any(abs(a[key] - b[key]) > limit for key, limit in limits):
                continue
            metric = "unaccounted_energy_residual_w"
            ua, ub = first["uncertainties"].get(metric), second["uncertainties"].get(metric)
            rows.append({"source": first["source"], "run_a": first["run_id"], "run_b": second["run_id"],
                         "residual_difference_w": a[metric]-b[metric],
                         "standard_uncertainty_w": difference_standard_uncertainty(ua, ub) if ua and ub else None})
    return rows
