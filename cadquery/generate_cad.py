"""Build all CAD, mesh, gasket-outline, BOM, and validation artifacts."""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from pathlib import Path

import cadquery as cq
from cadquery import exporters, importers
from vtkmodules.vtkFiltersCore import vtkFeatureEdges
from vtkmodules.vtkIOGeometry import vtkSTLReader

from coldplate import __version__
from coldplate.analysis import write_results
from coldplate.cad import make_assembly, make_insert, part_library
from coldplate.config import MATERIALS, P


ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
STEP = BUILD / "step"
MESH = BUILD / "mesh"
DXF = BUILD / "gaskets"
REPORTS = BUILD / "reports"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def bbox_tuple(shape: cq.Shape) -> list[float]:
    b = shape.BoundingBox()
    return [b.xlen, b.ylen, b.zlen]


def close(a: float, b: float, abs_tol=2e-4, rel_tol=2e-7) -> bool:
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))


def write_bom(path: Path) -> None:
    rows = [
        ("CP-001", 1, MATERIALS["CP-001"], "Base; 200 x 200 x 25; machined cavity/glands/ports"),
        ("CP-002", 1, MATERIALS["CP-002"], "Common cold-wall cover; 200 x 200 x 5.5"),
        ("FI-000", 1, MATERIALS["FI-000"], "Open-plenum control; use one insert per test"),
        ("FI-100", 1, MATERIALS["FI-100"], "Nine-pass serpentine insert"),
        ("FI-200", 1, MATERIALS["FI-200"], "Eight-channel parallel insert"),
        ("FI-300", 1, MATERIALS["FI-300"], "Tapered-manifold candidate"),
        ("TH-001", 1, MATERIALS["TH-001"], "160 dia x 2 payload; 150 dia analysis ROI"),
        ("CL-001", 1, MATERIALS["CL-001"], "Provisional adjustable payload/heater clamp"),
        ("CL-002", 1, MATERIALS["CL-002"], "Structural perimeter clamp; 166 aperture x 8"),
        ("BR-001", 4, MATERIALS["BR-001"], "Bench bracket; dry underside attachment"),
        ("GS-001", 1, MATERIALS["GS-001"], "AS568-166 candidate; verify supplier lot"),
        ("GS-013", 2, MATERIALS["GS-013"], "AS568-013 transfer face-seal candidates"),
        ("GS-RIB-000", 1, MATERIALS["GS-RIB"], "FI-000 registered perimeter gasket pattern"),
        ("GS-RIB-100", 1, MATERIALS["GS-RIB"], "FI-100 registered strip pattern"),
        ("GS-RIB-200", 1, MATERIALS["GS-RIB"], "FI-200 registered strip pattern"),
        ("GS-RIB-300", 1, MATERIALS["GS-RIB"], "FI-300 registered strip pattern"),
        ("HW-M5X25", 16, "Selected corrosion-compatible fastener TBD", "Modeled 8.5 dia head envelope; torque TBD"),
        ("HW-WASHER-M5", 16, "Selected washer TBD", "10 OD x 5.3 ID x 1 envelope"),
        ("HW-NPT-1/4", 2, "Actual fitting TBD", "1/4-18 NPT candidate; verify thread/fitting envelope"),
        ("HW-PRESSURE-TAP", 2, "Actual fitting TBD", "Flush static tap connected to each transfer center"),
        ("HT-001-ENV", 1, "Provisional heater envelope only", "150 dia x 1 placeholder; no resistive pattern claimed"),
    ]
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["item", "quantity", "material_or_spec", "description_status"])
        writer.writerows(rows)


def export_gasket_dxf(name: str, shape: cq.Shape) -> Path:
    path = DXF / f"{name}.dxf"
    # Export the top edges as a planar cutting outline, translated to z=0.
    top_z = shape.BoundingBox().zmax
    wires = []
    for solid in shape.Solids():
        face = max(solid.Faces(), key=lambda f: f.Center().z)
        wires.extend(face.Wires())
    planar = cq.Compound.makeCompound([wire.translate((0, 0, -top_z)) for wire in wires])
    exporters.export(planar, str(path))
    return path


def main() -> None:
    os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / ".cache"))
    for d in (STEP, MESH, DXF, REPORTS):
        d.mkdir(parents=True, exist_ok=True)

    calculations = write_results(REPORTS / "analysis_results.json")
    write_bom(REPORTS / "bom.csv")
    parts = part_library()
    validations = []
    mesh_validations = []
    outline_validations = []
    files = []
    geometry_checks = {"parts": {}, "explicit_clearances_mm": {}}

    for name, shape in parts.items():
        geometry_checks["parts"][name] = {
            "valid_brep": bool(shape.isValid()),
            "solid_count": len(shape.Solids()),
            "bbox_mm": bbox_tuple(shape),
            "volume_mm3": shape.Volume(),
        }
        if not shape.isValid():
            raise RuntimeError(f"Invalid B-rep: {name}")
        path = STEP / f"{name}.step"
        exporters.export(shape, str(path))
        imported = importers.importStep(str(path)).val()
        source_bbox, imported_bbox = bbox_tuple(shape), bbox_tuple(imported)
        source_volume, imported_volume = shape.Volume(), imported.Volume()
        passed = all(close(a, b) for a, b in zip(source_bbox, imported_bbox)) and close(source_volume, imported_volume, abs_tol=2e-3)
        validations.append(
            {
                "file": path.name,
                "source_solids": len(shape.Solids()),
                "reimported_solids": len(imported.Solids()),
                "source_bbox_mm": source_bbox,
                "reimported_bbox_mm": imported_bbox,
                "source_volume_mm3": source_volume,
                "reimported_volume_mm3": imported_volume,
                "pass": passed,
            }
        )
        if not passed:
            raise RuntimeError(f"STEP round-trip mismatch: {name}")
        files.append(path)

    for variant in ("FI-000", "FI-100", "FI-200", "FI-300"):
        insert, gasket, _ = make_insert(variant)
        mesh_path = MESH / f"{variant}_prototype.stl"
        # Capture exact CAD bounds before meshing; OCC's cached tessellation can
        # make a later non-optimal bounding-box query conservatively larger.
        source_bbox = bbox_tuple(insert)
        exporters.export(insert, str(mesh_path), tolerance=0.05, angularTolerance=0.15)
        reader = vtkSTLReader()
        reader.SetFileName(str(mesh_path))
        reader.Update()
        poly = reader.GetOutput()
        bounds = poly.GetBounds()
        mesh_bbox = [bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]]
        feature_edges = vtkFeatureEdges()
        feature_edges.SetInputData(poly)
        feature_edges.BoundaryEdgesOn()
        feature_edges.NonManifoldEdgesOn()
        feature_edges.FeatureEdgesOff()
        feature_edges.ManifoldEdgesOff()
        feature_edges.Update()
        open_edges = feature_edges.GetOutput().GetNumberOfCells()
        mesh_pass = poly.GetNumberOfCells() > 0 and open_edges == 0 and all(close(a, b, abs_tol=0.08) for a, b in zip(source_bbox, mesh_bbox))
        mesh_validations.append({
            "file": mesh_path.name,
            "triangles": poly.GetNumberOfCells(),
            "open_or_nonmanifold_edges": open_edges,
            "source_bbox_mm": source_bbox,
            "mesh_bbox_mm": mesh_bbox,
            "pass": mesh_pass,
        })
        if not mesh_pass:
            raise RuntimeError(f"STL validation failed: {mesh_path.name}")
        files.append(mesh_path)
        dxf_path = export_gasket_dxf(f"{variant}_gasket_cutting_outline", gasket)
        imported_outline = importers.importDXF(str(dxf_path))
        outline_validations.append({
            "file": dxf_path.name,
            "imported_entities": len(imported_outline.vals()),
            "pass": len(imported_outline.vals()) > 0,
        })
        if not outline_validations[-1]["pass"]:
            raise RuntimeError(f"DXF outline validation failed: {dxf_path.name}")
        files.append(dxf_path)

    assembly_path = STEP / "CP-REV-A_assembly_FI-100.step"
    exploded_path = STEP / "CP-REV-A_exploded_FI-100.step"
    family_path = STEP / "CP-REV-A_insert_family.step"
    make_assembly("FI-100", exploded=False).save(str(assembly_path))
    make_assembly("FI-100", exploded=True).save(str(exploded_path))
    family = cq.Assembly(name="INSERT_FAMILY")
    for i, variant in enumerate(("FI-000", "FI-100", "FI-200", "FI-300")):
        insert, gasket, _ = make_insert(variant)
        family.add(insert.translate(((i - 1.5) * 180, 0, 0)), name=variant)
        family.add(gasket.translate(((i - 1.5) * 180, 0, 0)), name=f"{variant}_GASKET")
    family.save(str(family_path))
    for path in (assembly_path, exploded_path, family_path):
        imported = importers.importStep(str(path)).val()
        validations.append(
            {
                "file": path.name,
                "reimported_solids": len(imported.Solids()),
                "reimported_bbox_mm": bbox_tuple(imported),
                "reimported_volume_mm3": imported.Volume(),
                "pass": len(imported.Solids()) >= (4 if path == family_path else 8),
                "note": "assembly STEP reimport part-count floor and aggregate envelope/volume check",
            }
        )
        if not validations[-1]["pass"]:
            raise RuntimeError(f"Assembly STEP part-count check failed: {path.name}")
        files.append(path)

    connectivity = {
        variant: {
            "fluid_domain_solids": len(make_insert(variant)[2].Solids()),
            "continuous": len(make_insert(variant)[2].Solids()) == 1,
        }
        for variant in ("FI-000", "FI-100", "FI-200", "FI-300")
    }
    if not all(x["continuous"] for x in connectivity.values()):
        raise RuntimeError(f"Disconnected fluid domain: {connectivity}")

    geometry_checks["explicit_clearances_mm"] = {
        "nominal_insert_to_cavity_diametral": P.cavity_diameter - P.insert_od,
        "minimum_insert_to_cavity_diametral": P.cavity_diameter - (P.insert_od + P.insert_od_tol),
        "main_groove_inner_edge_to_cavity_radial_land": (P.main_groove_id - P.cavity_diameter) / 2,
        "main_groove_outer_edge_to_bolt_hole_radial_land": P.bolt_radius - P.tapped_hole_diameter_model / 2 - P.main_groove_od / 2,
        "transfer_groove_inner_edge_to_insert_opening_radial_land": (P.transfer_groove_id - P.insert_transfer_diameter) / 2,
        "thread_envelope_to_base_bottom": P.base_thickness + P.side_port_axis_z - P.npt_thread_envelope_diameter / 2,
        "nominal_drill_to_base_bottom": P.base_thickness + P.side_port_axis_z - P.drilled_passage_diameter / 2,
        "washer_to_outer_edge_at_nearest_axis_extreme": P.base_xy / 2 - P.bolt_radius * __import__("math").cos(__import__("math").radians(P.bolt_offset_deg)) - P.washer_od / 2,
        "clamp_aperture_to_payload_clamp_radial": (P.structural_clamp_aperture - P.payload_clamp_od) / 2,
        "clamp_aperture_to_payload_radial": (P.structural_clamp_aperture - P.payload_diameter) / 2,
    }
    geometry_checks["interference_intent"] = {
        "payload_to_CL001": "intentional annular clamp-contact overlap; actual contact stack awaits heater selection",
        "gaskets_to_cover": "intentional nominal compression represented by installed-height gasket solids",
        "all_other_named_parts": "aggregate envelope reviewed; physical assembly verification still required",
    }
    geometry_path = REPORTS / "cad_geometry_checks.json"
    geometry_path.write_text(json.dumps(geometry_checks, indent=2) + "\n")

    validation_path = REPORTS / "step_roundtrip_validation.json"
    validation_path.write_text(json.dumps({"parts": validations, "fluid_connectivity": connectivity}, indent=2) + "\n")
    mesh_validation_path = REPORTS / "mesh_and_outline_validation.json"
    mesh_validation_path.write_text(json.dumps({"meshes": mesh_validations, "gasket_outlines": outline_validations}, indent=2) + "\n")
    dependencies_path = REPORTS / "dependency_versions.txt"
    dependencies_path.write_text("\n".join([
        f"python={platform.python_version()}",
        f"cadquery={importlib.metadata.version('cadquery')}",
        f"cadquery-ocp={importlib.metadata.version('cadquery-ocp')}",
        f"ezdxf={importlib.metadata.version('ezdxf')}",
        f"numpy={importlib.metadata.version('numpy')}",
    ]) + "\n")
    files.extend([REPORTS / "analysis_results.json", REPORTS / "bom.csv", validation_path, mesh_validation_path, geometry_path, dependencies_path])

    manifest = {
        "package_version": __version__,
        "revision": P.revision,
        "status": "PRELIMINARY ENGINEERING - NOT MACHINING APPROVED",
        "python": sys.version,
        "platform": platform.platform(),
        "cadquery": cq.__version__,
        "coordinate_system": P.datum_note,
        "selected_assembly_insert": "FI-100",
        "analysis_summary": calculations,
        "files": [
            {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in sorted(files)
        ],
    }
    manifest_path = BUILD / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Generated {len(files)} artifacts; manifest: {manifest_path}")


if __name__ == "__main__":
    main()
