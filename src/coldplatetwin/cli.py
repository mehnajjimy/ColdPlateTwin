"""command-line interface. each command is a thin wrapper around one package function."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from .demo import run_demo
from .bundle import analyze_files
from .configuration import load_config


def _parser() -> argparse.ArgumentParser:
    """build the coldplate argument parser with its demo, analyze and dashboard commands."""

    parser = argparse.ArgumentParser(prog="coldplate", description="ColdPlateTwin analysis and screening tools")
    commands = parser.add_subparsers(dest="command", required=True)

    # coldplate demo
    demo = commands.add_parser("demo", help="regenerate the complete synthetic demonstration")
    demo.add_argument("--output", type=Path, default=Path("outputs/demo"))
    demo.add_argument("--config", type=Path)
    demo.add_argument("--cad-config", type=Path)

    # coldplate analyze
    analyze = commands.add_parser("analyze", help="analyze an experimental or synthetic logger CSV")
    analyze.add_argument("csv", type=Path)
    analyze.add_argument("metadata", type=Path)
    analyze.add_argument("--output", type=Path, required=True)
    analyze.add_argument("--config", type=Path)
    analyze.add_argument("--ir", type=Path, help="generic corrected temperature-matrix CSV")
    analyze.add_argument("--ir-config", type=Path)
    analyze.add_argument("--roi-config", type=Path, help="physical diameter, pixel scale and optional occlusion mask")

    # coldplate dashboard
    dashboard = commands.add_parser("dashboard", help="launch the local Streamlit dashboard")
    dashboard.add_argument("--data", type=Path, default=Path("outputs/demo"))
    return parser


def main(argv: list[str] | None = None) -> int:
    """run one command and return its exit code."""

    args = _parser().parse_args(argv)

    # demo: build everything and print a short JSON status
    if args.command == "demo":
        summary = run_demo(args.output, load_config(args.config), args.cad_config)
        status = {
            "status": "complete",
            "output": str(args.output),
            "valid_runs": summary["valid_run_count"],
            "rejected_runs": summary["rejected_run_count"],
        }
        print(json.dumps(status, indent=2))
        return 0

    # analyze: exit 2 when the steady-state check rejects the run. the bundle is still written.
    if args.command == "analyze":
        result = analyze_files(args.csv, args.metadata, args.output, load_config(args.config),
                               ir_path=args.ir, ir_config_path=args.ir_config, roi_config_path=args.roi_config)
        print(args.output)
        return 0 if result["steady_state"]["passed"] else 2

    # dashboard: start streamlit on localhost only, with usage stats off, and pass --data to the app
    if args.command == "dashboard":
        app = Path(__file__).with_name("dashboard.py")
        return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app),
                                "--server.address", "127.0.0.1", "--browser.gatherUsageStats", "false",
                                "--", "--data", str(args.data)])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
