from __future__ import annotations

import json
from pathlib import Path

from coldplatetwin.cli import main
from coldplatetwin.geometry import load_geometry


def test_complete_demo(tmp_path: Path, monkeypatch) -> None:
    # A wheel installed outside the checkout must use the selected CAD path
    # for every stage, including the separate tolerance-screening report.
    cad_config = load_geometry().source_path
    config = Path(__file__).resolve().parents[1] / "configs/demo.json"
    monkeypatch.delenv("COLDPLATE_CAD_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "demo"
    assert main(["demo", "--output", str(output), "--cad-config", cad_config,
                 "--config", str(config)]) == 0
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
