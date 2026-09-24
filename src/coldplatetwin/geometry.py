"""read the rev a cad dimensions and convert millimetres to si units.

only cadquery/coldplate/config.py is loaded. it holds plain dataclasses and
never imports cadquery or occ, so the cad file stays the one geometry source.
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


# --- geometry record ---

@dataclass(frozen=True)
class GeometrySI:
    """the cad dimensions the models need in metres, plus the config path and hash."""

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


# --- finding and loading the cad config ---

def _find_config(explicit_path: str | Path | None = None) -> Path:
    """find the cad config file without importing the cad package."""

    # an explicit path wins, then the environment variable
    if not explicit_path:
        explicit_path = os.environ.get("COLDPLATE_CAD_CONFIG")
    if explicit_path:
        path = Path(explicit_path)
        if not path.is_file():
            raise FileNotFoundError(f"Explicit CAD configuration not found: {path}")
        return path.resolve()

    # otherwise walk up from this file, then from the current folder
    for start in (Path(__file__).resolve(), Path.cwd().resolve()):
        for folder in [start, *start.parents]:
            candidate = folder / "cadquery/coldplate/config.py"
            if candidate.is_file():
                return candidate.resolve()
    raise FileNotFoundError(
        "Rev A config not found. Run inside the ColdPlateTwin repository or set "
        "COLDPLATE_CAD_CONFIG=/path/to/cadquery/coldplate/config.py"
    )


def _load_parameter_object(path: Path):
    """load the plain python config module from its path and return its P object."""

    spec = importlib.util.spec_from_file_location("_coldplate_rev_a_config", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load CAD configuration: {path}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses needs the module registered while it runs, so add it for a moment
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module.P


# --- converting to si ---

def load_geometry(config_path: str | Path | None = None) -> GeometrySI:
    """return the model geometry in metres plus a hash of the cad config."""

    path = _find_config(config_path)
    p = _load_parameter_object(path)
    mm = 1e-3

    # fi-100 path length, same route as the cad: straight passes, semicircular
    # returns between them and two diagonal feed transitions
    transition_mm = hypot(p.transfer_x - p.fi100_straight_length / 2,
                          (p.fi100_pass_count - 1) * p.fi100_pitch / 2)
    path_mm = (
        p.fi100_pass_count * p.fi100_straight_length
        + (p.fi100_pass_count - 1) * pi * p.fi100_return_radius
        + 2.0 * transition_mm
    )

    # hash every cad field, so any change to the config changes the hash
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
