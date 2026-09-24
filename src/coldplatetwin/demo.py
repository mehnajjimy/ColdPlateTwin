"""reproducible end-to-end demonstration and artifact export."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

# pick the file-only backend before pyplot loads, so the demo never opens a window
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .geometry import load_geometry
from .hydraulics import predict_hydraulics
from .schemas import RunMetadata
from .screening import corrected_screening
from .synthetic import generate_example_set
from .thermal import sensitivity_sweep, solve_two_layer, uniform_lumped_solution
from .configuration import load_config, AnalysisConfig
from .bundle import analyze_files, matched_comparisons, write_json


# ---- figure and doe helpers ----

def _write_figure(fig: plt.Figure, base: Path) -> None:
    """save one figure as PNG and SVG next to each other, then close it."""

    fig.savefig(base.with_suffix(".png"), dpi=180, bbox_inches="tight")
    fig.savefig(base.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def _make_doe(path: Path, seed: int = 20260917, config=None) -> pd.DataFrame:
    """write and return a randomized run order for the proposed doe and development runs."""

    rows: list[dict] = []
    settings = (config or AnalysisConfig()).doe
    rng = np.random.default_rng(seed)

    # each replicated block holds every insert, flow and power once, in shuffled order
    for block in range(1, settings.replicated_blocks + 1):
        block_rows = []
        for insert in ("FI-000", "FI-100", "FI-200", "FI-300"):
            for flow in settings.flow_lpm:
                for power in settings.heater_power_w:
                    block_rows.append({"purpose": "proposed_operating_doe", "block": block, "insert_id": insert,
                                       "flow_lpm": flow, "heater_power_w": power, "hardware_authorization": False})
        for i in rng.permutation(len(block_rows)):
            rows.append(block_rows[i])

    # then one shuffled block 0 at the wider development flow and the highest power
    development = []
    for insert in ("FI-000", "FI-100", "FI-200", "FI-300"):
        development.append({"purpose": "wider_development_envelope", "block": 0, "insert_id": insert,
                            "flow_lpm": settings.development_envelope_max_flow_lpm,
                            "heater_power_w": max(settings.heater_power_w), "hardware_authorization": False})
    for i in rng.permutation(len(development)):
        rows.append(development[i])

    # number the rows in run order and save
    table = pd.DataFrame(rows)
    table.insert(0, "randomized_order", np.arange(1, len(table) + 1))
    table.to_csv(path, index=False)
    return table


def _time_trace_figure(frame: pd.DataFrame, title: str) -> plt.Figure:
    """plot temperatures, flow and electrical power of one run against elapsed minutes."""

    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
    minutes = (frame["timestamp"] - frame["timestamp"].iloc[0]).dt.total_seconds() / 60.0
    axes[0].plot(minutes, frame["tin_c"], label="Inlet")
    axes[0].plot(minutes, frame["tout_c"], label="Outlet")
    axes[0].set_ylabel("Temperature (°C)")
    axes[0].legend()
    axes[1].plot(minutes, frame["flow_lpm"], color="#157a6e")
    axes[1].set_ylabel("Flow (L/min)")
    axes[2].plot(minutes, frame["heater_voltage_v"] * frame["heater_current_a"], color="#b55400")
    axes[2].set_ylabel("Electrical power (W)")
    axes[2].set_xlabel("Elapsed time (min)")
    fig.suptitle(f"SYNTHETIC - {title}")
    fig.tight_layout()
    return fig


# ---- the full demonstration ----

def run_demo(output_dir: str | Path, config: AnalysisConfig | None = None, cad_config=None) -> dict:
    """generate data, analyze it, run the models, export every demo artifact and return the summary."""

    config = config or load_config()
    config.validate()

    # output folders
    output = Path(output_dir)
    data_dir = output / "data" / "synthetic"
    results_dir = output / "results"
    figures_dir = output / "figures"
    for directory in (data_dir, results_dir, figures_dir):
        directory.mkdir(parents=True, exist_ok=True)

    # synthetic runs, the effective config, and parser and ROI settings for the 24x24 IR matrices
    geometry = load_geometry(cad_config)
    csv_paths = generate_example_set(data_dir, geometry, config.seed, config.demo_flow_lpm, config.demo_power_w)
    write_json(output / "effective_config.json", config.as_dict())
    matrix_size = 24
    parser_path = output / "radiometric_config.json"
    roi_path = output / "roi_config.json"
    write_json(parser_path, {"timestamp_column": 0, "frame_column": 1, "data_start_column": 2,
                             "width": matrix_size, "height": matrix_size})
    write_json(roi_path, {"diameter_mm": geometry.roi_diameter_m * 1000,
                          "pixel_size_mm": geometry.payload_diameter_m * 1000 / matrix_size})

    # analyze every run into its own bundle. the invalid run has no IR file.
    results = []
    bundle_records = []
    calibrated_frames: dict[str, pd.DataFrame] = {}
    for csv_path in csv_paths:
        metadata_path = csv_path.with_name(csv_path.name.replace("_raw.csv", "_metadata.json"))
        metadata = RunMetadata.read_json(metadata_path)
        radiometric_path = csv_path.with_name(csv_path.name.replace("_raw.csv", "_radiometric.csv"))
        if radiometric_path.exists():
            ir_path = radiometric_path
            ir_config_path = parser_path
            roi_config_path = roi_path
        else:
            ir_path = None
            ir_config_path = None
            roi_config_path = None
        bundle_dir = output / "runs" / metadata.run_id
        result = analyze_files(csv_path, metadata_path, bundle_dir, config,
                               ir_path=ir_path,
                               ir_config_path=ir_config_path,
                               roi_config_path=roi_config_path)
        results.append(result)
        calibrated = pd.read_csv(bundle_dir / "calibrated.csv", parse_dates=["timestamp"])
        calibrated_frames[metadata.run_id] = calibrated
        bundle_records.append({"run_id": metadata.run_id,
                               "result_file": str((bundle_dir / "result.json").relative_to(output))})

    # metric table of the accepted runs
    valid_results = [item for item in results if item["steady_state"]["passed"]]
    metrics_rows = []
    for item in valid_results:
        row = {"run_id": item["run_id"], "insert_id": item["insert_id"], "source": item["source"]}
        row.update(item["metrics"])
        metrics_rows.append(row)
    metrics = pd.DataFrame(metrics_rows)
    if metrics.empty:
        metrics = pd.DataFrame(columns=["run_id", "insert_id", "source"])
    metrics.to_csv(results_dir / "run_metrics.csv", index=False)

    # one uncertainty row per accepted run and metric
    uncertainty_keys = {"value", "analytical_standard", "monte_carlo_standard", "status"}
    uncertainty_rows = []
    for item in valid_results:
        for metric, values in item["uncertainties"].items():
            row = {"source": item["source"], "run_id": item["run_id"], "metric": metric}
            for key, value in values.items():
                if key in uncertainty_keys:
                    row[key] = value
            uncertainty_rows.append(row)
    uncertainty_table = pd.DataFrame(uncertainty_rows, columns=["source", "run_id", "metric", "value",
                                                                "analytical_standard", "monte_carlo_standard",
                                                                "status"])
    uncertainty_table.to_csv(results_dir / "uncertainties.csv", index=False)

    # hydraulic screen of every insert at the demo flow, as JSON and as a flat CSV
    hydraulics = [predict_hydraulics(geometry, insert, config.demo_flow_lpm,
                                     inputs=config.hydraulic).as_dict()
                  for insert in ("FI-000", "FI-100", "FI-200", "FI-300")]
    (results_dir / "hydraulic_screening.json").write_text(json.dumps(hydraulics, indent=2) + "\n")
    hydraulic_rows = []
    for row in hydraulics:
        flat = {key: value for key, value in row.items()
                if key not in {"branch_flow_lpm", "warnings", "assumptions"}}
        # list and dict fields become text so each insert fits on one CSV row
        flat["branch_flow_lpm"] = json.dumps(row["branch_flow_lpm"])
        flat["warnings"] = " | ".join(row["warnings"])
        flat["assumptions"] = json.dumps(row["assumptions"])
        hydraulic_rows.append(flat)
    pd.DataFrame(hydraulic_rows).to_csv(results_dir / "hydraulic_screening.csv", index=False)

    # thermal model scenario, its sensitivity sweep and the uniform analytical check
    thermal = solve_two_layer(geometry, config.thermal, "broad")
    np.savetxt(results_dir / "thermal_payload_temperature_c.csv", thermal.payload_temperature_c, delimiter=",")
    sensitivity = pd.DataFrame(sensitivity_sweep(geometry, config.thermal))
    sensitivity.to_csv(results_dir / "thermal_sensitivity.csv", index=False)
    analytical_payload, analytical_cover = uniform_lumped_solution(geometry, config.thermal)
    thermal_summary = {
        "classification": "synthetic_model_scenario_not_validation",
        "heat_to_coolant_w": thermal.heat_to_coolant_w,
        "heat_to_environment_w": thermal.heat_to_environment_w,
        "energy_residual_w": thermal.energy_residual_w,
        "uniform_analytical_payload_c": analytical_payload,
        "uniform_analytical_cover_c": analytical_cover,
        "limitations": thermal.limitations,
    }
    (results_dir / "thermal_summary.json").write_text(json.dumps(thermal_summary, indent=2) + "\n")

    # corrected seal, gasket and cover screening, doe manifest and matched comparisons
    screening = corrected_screening(geometry.source_path)
    (results_dir / "corrected_screening_report.json").write_text(json.dumps(screening, indent=2) + "\n")
    doe = _make_doe(results_dir / "proposed_doe_manifest.csv", config.seed, config)
    write_json(results_dir / "matched_comparisons.json", matched_comparisons(results, config))

    # figure: time traces of the first run
    first_run_id = results[0]["run_id"]
    _write_figure(_time_trace_figure(calibrated_frames[first_run_id], first_run_id), figures_dir / "synthetic_time_traces")

    # figure: energy residual per insert
    fig, ax = plt.subplots(figsize=(8, 5))
    if not metrics.empty:
        ordered = metrics.sort_values("insert_id")
        ax.bar(ordered["insert_id"], ordered["unaccounted_energy_residual_w"], color="#bc6c25")
    ax.set_ylabel("Unaccounted energy residual (W)")
    ax.set_title("SYNTHETIC comparison at nominally matched conditions")
    ax.text(0.5, -0.17, "Illustrative generator assumptions; not design evidence", transform=ax.transAxes, ha="center")
    _write_figure(fig, figures_dir / "synthetic_insert_comparison")

    # figure: modelled payload surface temperature
    fig, ax = plt.subplots(figsize=(6, 5))
    image = ax.imshow(thermal.payload_temperature_c, origin="lower", cmap="inferno")
    fig.colorbar(image, ax=ax, label="Payload temperature (°C)")
    ax.set_title("SYNTHETIC MODEL SCENARIO - upper surface")
    ax.set_axis_off()
    _write_figure(fig, figures_dir / "synthetic_thermal_map")

    # figure: heat to water with its standard uncertainty. it reads the saved CSV back.
    fig, ax = plt.subplots(figsize=(8, 5))
    uncertainty_table = pd.read_csv(results_dir / "uncertainties.csv")
    if not uncertainty_table.empty:
        sample = uncertainty_table[uncertainty_table["metric"] == "heat_to_water_enthalpy_w"]
        ax.errorbar(sample["run_id"], sample["value"], yerr=sample["analytical_standard"], fmt="o", capsize=4)
    ax.set_ylabel("Heat to water (W), standard uncertainty")
    ax.set_title("SYNTHETIC uncertainty propagation")
    ax.tick_params(axis="x", rotation=25)
    _write_figure(fig, figures_dir / "synthetic_uncertainty")

    # summary manifest of the whole demonstration
    manifest = {
        "classification": "SYNTHETIC DEMONSTRATION - NOT PHYSICAL VALIDATION",
        "geometry_hash": geometry.configuration_hash,
        "geometry_source": geometry.source_path,
        "runs": results,
        "run_bundles": bundle_records,
        "effective_config": config.as_dict(),
        "analysis_configuration_hash": config.configuration_hash,
        "valid_run_count": len(valid_results),
        "rejected_run_count": len(results) - len(valid_results),
        "doe_rows": len(doe),
        "outputs": {"results": "results", "figures": "figures", "data": "data/synthetic"},
    }
    (output / "summary.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n")
    return manifest
