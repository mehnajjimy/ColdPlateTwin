"""end-to-end run of the synthetic demo through the command line."""

import json
from pathlib import Path

from coldplatetwin.cli import main
from coldplatetwin.geometry import load_geometry


def test_demo_command_writes_every_result_from_the_chosen_cad_config(tmp_path, monkeypatch):
    """catches the demo failing, miscounting accepted runs, or depending on the working folder."""
    # run from an unrelated folder with no environment override, the way an
    # installed package would, so every stage must use the --cad-config path
    cad_config = load_geometry().source_path
    config = Path(__file__).resolve().parents[1] / "configs/demo.json"
    monkeypatch.delenv("COLDPLATE_CAD_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "demo"
    assert main(["demo", "--output", str(output), "--cad-config", cad_config, "--config", str(config)]) == 0

    # four clean synthetic runs and one deliberately bad one
    summary = json.loads((output / "summary.json").read_text())
    assert summary["classification"].startswith("SYNTHETIC")
    assert summary["valid_run_count"] == 4
    assert summary["rejected_run_count"] == 1
    for relative in (
        "results/run_metrics.csv",
        "results/uncertainties.csv",
        "results/hydraulic_screening.json",
        "results/thermal_sensitivity.csv",
        "results/proposed_doe_manifest.csv",
        "figures/synthetic_time_traces.png",
        "figures/synthetic_time_traces.svg",
    ):
        assert (output / relative).is_file(), relative
