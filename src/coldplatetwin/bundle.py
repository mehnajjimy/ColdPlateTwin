"""turn logger data and optional IR frames into the analysis bundle used by the cli and demo."""

import hashlib
import json
from pathlib import Path
import numpy as np

from .analysis import analyze_run
from .calibration import apply_calibrations, calibrations_from_sensor_specs
from .configuration import AnalysisConfig
from .io import RadiometricCSVConfig, read_measurement_csv, read_radiometric_csv
from .roi import circular_roi_statistics
from .schemas import RunMetadata
from .steady import find_steady_state
from .uncertainty import difference_standard_uncertainty


# ---------------------------------------------------------------------------
# small file helpers
# ---------------------------------------------------------------------------

# record where an input file lives and its sha-256 hash
def file_evidence(path):
    path = Path(path)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


# write indented json and refuse nan or infinity
def write_json(path, data):
    """strict json: nan and infinity may never pass as valid measurements."""
    Path(path).write_text(json.dumps(data, indent=2, default=str, allow_nan=False) + "\n")


# ---------------------------------------------------------------------------
# building a result bundle
# ---------------------------------------------------------------------------

# analyze one run and write result.json, calibrated.csv and optionally
# radiometric.npz into a bundle folder
def analyze_files(csv_path, metadata_path, output, config=None, *, ir_path=None, ir_config_path=None, roi_config_path=None):
    """write a portable result bundle without changing raw input files."""
    # load, calibrate and find the steady window
    config = config or AnalysisConfig()
    metadata = RunMetadata.read_json(metadata_path)
    raw = read_measurement_csv(csv_path)
    calibrated = apply_calibrations(raw, calibrations_from_sensor_specs(metadata.sensors))
    steady = find_steady_state(calibrated, config.steady_state)

    # a .json output also gets a bundle folder of the same name beside it.
    # never let an output path land on an input file
    output = Path(output)
    if output.suffix == ".json":
        bundle_dir = output.parent / output.stem
    else:
        bundle_dir = output
    inputs = (csv_path, metadata_path, ir_path, ir_config_path, roi_config_path)
    sources = [Path(p).resolve() for p in inputs if p]
    bundle_files = [bundle_dir / name for name in ("result.json", "calibrated.csv", "radiometric.npz")]
    destinations = [output.resolve(), *bundle_files]
    if any(Path(path).resolve() in sources for path in destinations):
        raise ValueError("Output would overwrite a raw source file")
    bundle_dir.mkdir(parents=True, exist_ok=True)
    evidence = {"logger": file_evidence(csv_path), "metadata": file_evidence(metadata_path)}

    # optional infrared frames
    roi, ir_info, ir_warnings = None, None, []
    if ir_path:
        if not ir_config_path or not roi_config_path or metadata.camera is None:
            raise ValueError("IR analysis requires --ir-config, --roi-config and camera metadata")
        if not metadata.camera.export_is_temperature_corrected:
            raise ValueError("Uncorrected camera exports require vendor calibration; no correction is guessed")

        # read the frames using the parser settings file
        parsing = json.loads(Path(ir_config_path).read_text())
        parsing.pop("classification", None)
        frames = read_radiometric_csv(ir_path, RadiometricCSVConfig(**parsing))

        # read the roi settings and convert the diameter from mm to pixels
        roi_config = json.loads(Path(roi_config_path).read_text())
        unknown = set(roi_config) - {"diameter_mm", "pixel_size_mm", "center_xy", "occlusion_mask_csv"}
        if unknown:
            raise ValueError(f"Unknown ROI configuration fields: {sorted(unknown)}")
        diameter = float(roi_config["diameter_mm"])
        pixel_size = float(roi_config["pixel_size_mm"])
        if not np.isfinite([diameter, pixel_size]).all() or min(diameter, pixel_size) <= 0:
            raise ValueError("ROI physical diameter and pixel scale must be positive")

        # the whole circle must fit inside the frame. each pixel reaches half
        # a pixel past its center, so the edges sit at -0.5 and size - 0.5
        height, width = frames.temperatures_c.shape[1:]
        center = tuple(roi_config.get("center_xy", ((width-1)/2, (height-1)/2)))
        radius = diameter / pixel_size / 2
        if len(center) != 2:
            raise ValueError("The full circular ROI must lie inside the calibrated frame footprint")
        room_to_edge = min(center[0]+0.5, center[1]+0.5, width-0.5-center[0], height-0.5-center[1])
        if room_to_edge < radius:
            raise ValueError("The full circular ROI must lie inside the calibrated frame footprint")

        # optional 0/1 mask of pixels hidden behind wires or fixtures
        occlusion = None
        if roi_config.get("occlusion_mask_csv"):
            mask_path = Path(roi_config_path).parent / roi_config["occlusion_mask_csv"]
            occlusion = np.loadtxt(mask_path, delimiter=",")
            if not np.isin(occlusion, [0, 1]).all():
                raise ValueError("Occlusion mask must contain only 0/1")
            evidence["occlusion"] = file_evidence(mask_path)

        # only timestamped frames inside an accepted steady window count.
        # their mean map gives the roi statistics
        selected = np.array([], dtype=int)
        if frames.timestamps is not None and steady.passed:
            inside = (frames.timestamps >= steady.start) & (frames.timestamps <= steady.end)
            selected = np.flatnonzero(inside)
        if len(selected):
            mean_map = np.ma.mean(frames.temperatures_c[selected], axis=0)
            roi = circular_roi_statistics(mean_map, diameter/pixel_size, center, occlusion)
        elif frames.timestamps is None:
            ir_warnings.append("IR timestamps absent: frames are viewable but excluded from steady thermal metrics.")
        else:
            ir_warnings.append("No IR frames lie inside an accepted averaging interval.")

        # save every frame (masked pixels as nan) and describe them
        np.savez_compressed(bundle_dir / "radiometric.npz",
                            temperatures_c=frames.temperatures_c.filled(np.nan),
                            selected_indices=selected)
        if frames.timestamps is not None:
            timestamps = [stamp.isoformat() for stamp in frames.timestamps]
        else:
            timestamps = None
        ir_info = {
            "file": "radiometric.npz",
            "timestamps": timestamps,
            "accepted_frame_indices": selected.tolist(),
            "parser": parsing,
            "roi_config": roi_config,
            "aggregation": "equal-weight mean of available accepted temperature maps; no invented timing",
            "correction_applied_by_package": False,
        }
        ir_warnings.append("ROI metrics describe the sampled mean map; sparse IR frames do not establish continuous surface stability.")
        evidence["radiometric"] = file_evidence(ir_path)
        evidence["radiometric_parser"] = file_evidence(ir_config_path)
        evidence["roi_config"] = file_evidence(roi_config_path)
    elif ir_config_path or roi_config_path:
        raise ValueError("IR/ROI configuration requires --ir")

    # run the analysis and attach the ir warnings and input file hashes
    result = analyze_run(calibrated, metadata.run_id, metadata.insert_id, metadata.source,
                         roi=roi, metadata=metadata, config=config, steady_result=steady)
    result.warnings.extend(ir_warnings)
    result.provenance["input_files"] = evidence

    # write the bundle. file links inside result.json are relative to the bundle folder
    calibrated.to_csv(bundle_dir / "calibrated.csv", index=False)
    payload = result.as_dict()
    payload["bundle_version"] = "1.1"
    payload["artifacts"] = {"calibrated_csv": "calibrated.csv", "radiometric": ir_info}
    write_json(bundle_dir / "result.json", payload)

    # a .json output gets the same result with links pointing into the bundle folder
    if output.suffix == ".json":
        external = dict(payload)
        if ir_info:
            external_ir = dict(ir_info, file=f"{output.stem}/radiometric.npz")
        else:
            external_ir = None
        external["artifacts"] = {
            "calibrated_csv": f"{output.stem}/calibrated.csv",
            "radiometric": external_ir,
        }
        write_json(output, external)
    return payload


# ---------------------------------------------------------------------------
# reading and comparing bundles
# ---------------------------------------------------------------------------

# load results as a list of (result, folder) pairs
def load_bundles(path):
    """open one analysis json, a bundle folder, or a demo collection."""
    path = Path(path)
    if path.is_dir():
        if (path / "summary.json").exists():
            path = path / "summary.json"
        else:
            path = path / "result.json"
    content = json.loads(path.read_text())

    # a demo summary lists several run bundles
    if "run_bundles" in content:
        bundles = []
        for record in content["run_bundles"]:
            result_path = path.parent / record["result_file"]
            bundles.append((json.loads(result_path.read_text()), result_path.parent))
        return bundles

    if content.get("bundle_version") != "1.1":
        raise ValueError("This result predates the corrected bundle schema; regenerate it")
    return [(content, path.parent)]


# compare the energy residual of each pair of steady runs whose source,
# geometry, flow, power and inlet temperature all match
def matched_comparisons(results, config):
    """compare only like source, geometry, flow, power and inlet conditions."""
    rows = []
    for i, first in enumerate(results):
        for second in results[i+1:]:
            # both runs must have passed the steady-state screen
            if not first["steady_state"]["passed"] or not second["steady_state"]["passed"]:
                continue

            # same source and the same geometry
            a, b = first["metrics"], second["metrics"]
            meta_a = first["provenance"]["metadata"]
            meta_b = second["provenance"]["metadata"]
            if first["source"] != second["source"] or meta_a["geometry_hash"] != meta_b["geometry_hash"]:
                continue

            # flow, power and inlet temperature within the configured tolerances
            limits = (("flow_lpm", config.comparison_flow_tolerance_lpm),
                      ("electrical_power_synchronized_vi_w", config.comparison_power_tolerance_w),
                      ("tin_c", config.comparison_inlet_tolerance_k))
            if any(abs(a[key] - b[key]) > limit for key, limit in limits):
                continue

            metric = "unaccounted_energy_residual_w"
            ua = first["uncertainties"].get(metric)
            ub = second["uncertainties"].get(metric)
            row = {"source": first["source"], "run_a": first["run_id"], "run_b": second["run_id"],
                   "residual_difference_w": a[metric]-b[metric]}

            # the uncertainty is only given when both runs have one
            if ua and ub:
                row["standard_uncertainty_w"] = difference_standard_uncertainty(ua, ub)
            else:
                row["standard_uncertainty_w"] = None
            rows.append(row)
    return rows
