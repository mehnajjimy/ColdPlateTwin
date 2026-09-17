"""Read Rev A CAD dimensions and convert millimetres to SI units.

This adapter loads only ``cadquery/coldplate/config.py``.  That file contains
plain dataclasses and does not import CadQuery or OCC, so the analysis package
stays lightweight while retaining one geometry source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import importlib.util
import json
import os
import sys
from math import hypot, pi
from pathlib import Path


@dataclass(frozen=True)
class GeometrySI:
    """Small SI-unit view of the CAD dimensions needed by the models."""

    revision: str
    base_size_m: float
    base_thickness_m: float
    cavity_diameter_m: float
    channel_height_m: float
    cover_thickness_m: float
    payload_diameter_m: float
    payload_thickness_m: float
    roi_diameter_m: float
    channel_width_m: float
    parallel_channel_width_m: float
    parallel_centers_y_m: tuple[float, ...]
    fi100_bend_count: int
    drilled_passage_diameter_m: float
    heater_diameter_m: float
    fi100_path_length_m: float
    parallel_channel_length_m: float
    parallel_channel_count: int
    fi200_header_width_m: float
    fi300_header_end_width_m: float
    source_path: str
    configuration_hash: str


def _find_config(explicit_path: str | Path | None = None) -> Path:
    """Locate the CAD configuration without importing the CAD package."""

    candidates: list[Path] = []
    if explicit_path:
        path = Path(explicit_path)
        if not path.is_file():
            raise FileNotFoundError(f"Explicit CAD configuration not found: {path}")
        return path.resolve()
    if os.environ.get("COLDPLATE_CAD_CONFIG"):
        return _find_config(os.environ["COLDPLATE_CAD_CONFIG"])

    # Source-tree execution: walk upward from both this file and the current
    # directory.  This also works from an editable installation.
    for start in (Path(__file__).resolve(), Path.cwd().resolve()):
        candidates.extend(parent / "cadquery/coldplate/config.py" for parent in [start, *start.parents])

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "Rev A config not found. Run inside the ColdPlateTwin repository or set "
        "COLDPLATE_CAD_CONFIG=/path/to/cadquery/coldplate/config.py"
    )


def _load_parameter_object(path: Path):
    """Load the plain-Python configuration module from its file path."""

    spec = importlib.util.spec_from_file_location("_coldplate_rev_a_config", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load CAD configuration: {path}")
    module = importlib.util.module_from_spec(spec)
    # Register temporarily so dataclasses also works with postponed annotations.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module.P


def load_geometry(config_path: str | Path | None = None) -> GeometrySI:
    """Return the model geometry in metres and a reproducibility hash."""

    path = _find_config(config_path)
    p = _load_parameter_object(path)
    mm = 1e-3

    # Reproduce the CAD screening route exactly: nine straight passes, eight
    # semicircular returns and two diagonal feed transitions.
    transition_mm = hypot(p.transfer_x - p.fi100_straight_length / 2,
                          (p.fi100_pass_count - 1) * p.fi100_pitch / 2)
    path_mm = (
        p.fi100_pass_count * p.fi100_straight_length
        + (p.fi100_pass_count - 1) * pi * p.fi100_return_radius
        + 2.0 * transition_mm
    )

    # Hash every CAD field, including fields added in future revisions.
    config_hash = hashlib.sha256(json.dumps(asdict(p), sort_keys=True).encode()).hexdigest()

    return GeometrySI(
        revision=p.revision,
        base_size_m=p.base_xy * mm,
        base_thickness_m=p.base_thickness * mm,
        cavity_diameter_m=p.cavity_diameter * mm,
        channel_height_m=p.channel_height * mm,
        cover_thickness_m=p.cover_thickness * mm,
        payload_diameter_m=p.payload_diameter * mm,
        payload_thickness_m=p.payload_thickness * mm,
        roi_diameter_m=p.roi_diameter * mm,
        channel_width_m=p.fi100_channel_width * mm,
        parallel_channel_width_m=p.fi200_channel_width * mm,
        parallel_centers_y_m=tuple(y * mm for y in p.fi200_centers_y),
        fi100_bend_count=p.fi100_pass_count - 1,
        drilled_passage_diameter_m=p.drilled_passage_diameter * mm,
        heater_diameter_m=p.heater_envelope_diameter * mm,
        fi100_path_length_m=path_mm * mm,
        parallel_channel_length_m=p.fi200_straight_length * mm,
        parallel_channel_count=len(p.fi200_centers_y),
        fi200_header_width_m=p.fi200_header_width * mm,
        fi300_header_end_width_m=p.fi300_header_end_width * mm,
        source_path=str(path),
        configuration_hash=config_hash,
    )
