# Interchangeable-Insert Water Cold-Plate Testbed - Rev A

**Status: preliminary engineering - not machining approved and not pressure rated.**

This repository is a regenerable CadQuery package for CP-001, CP-002, TH-001,
FI-000/FI-100/FI-200/FI-300, CL-001, CL-002, BR-001, gasket patterns, seal
envelopes, fastener envelopes, assembly exports, prototype meshes, drawings and
engineering screening calculations.

The shared configuration records the Rev A dimensions used to generate these
preliminary artifacts. [Departures](docs/DEPARTURES.md) and the inspection plan
record the remaining design assumptions and release checks.

## Coordinate system

- CP-001 upper sealing deck: `z=0`
- Cavity center: `x=y=0`
- Inlet/outlet axis: x-axis
- All model dimensions: millimetres

## Regeneration

The geometry and calculations share [`coldplate/config.py`](coldplate/config.py).
With Python 3.14 and the dependencies in `requirements.txt`:

```sh
cd cadquery
python -m pip install -r requirements.txt
python smoke_test.py
python generate_cad.py
python generate_documents.py
```

Use a separate virtual environment for CAD regeneration. The analysis package
does not require these heavier CAD dependencies. The checked-in release exports
are in the parent repository's `exports/` and `drawings/` directories; the paths
below describe fresh generator output relative to this `cadquery/` directory.

`smoke_test.py` is the mandatory simple-solid STEP export/reimport gate. The CAD
generator exports and reimports every individual STEP plus the assembly, exploded
assembly and insert-family STEP files. It rejects bounding-box/volume mismatches,
invalid B-reps, insufficient assembly solid counts or disconnected fluid domains.

## Deliverable map

- `coldplate/`: editable configuration, CAD construction and calculations
- `build/step/`: individual parts, hardware/seal envelopes, fluid domains,
  selected FI-100 assembly, exploded assembly and insert family
- `build/mesh/`: FI-000/FI-100/FI-200/FI-300 prototype STL meshes
- `build/gaskets/`: nominal planar DXF gasket cutting outlines
- `build/reports/bom.csv`: bill of materials
- `build/reports/analysis_results.json`: deterministic engineering calculations
- `build/reports/cad_geometry_checks.json`: B-rep, envelope, wall/land and
  interference-intent checks
- `build/reports/step_roundtrip_validation.json`: STEP reimport evidence
- `build/reports/mesh_and_outline_validation.json`: watertight STL and DXF
  reimport evidence
- `build/reports/dependency_versions.txt`: CAD runtime versions
- `build/manifest.json`: SHA-256 package manifest
- `output/pdf/coldplate_revA_dimensioned_drawings.pdf`: six-sheet drawing set
- `output/pdf/coldplate_revA_validation_report.pdf`: calculations, validation,
  departures and release blockers

## Key findings

- FI-100 modeled centerline length is **1120.4 mm**, not an assumed 1.5 m.
- Worst-case channel-height arithmetic is **3.95-4.05 mm**, exactly consuming
  the specified band before flatness; the insert floor must be match-finished to
  the measured common base.
- Hot-insert/cold-base diametral clearance screens at **0.499 mm**, or **0.299 mm**
  after the reserved 0.20 mm growth allowance. Conditioned POM-C measurements
  remain mandatory.
- Pressure-only cover screens reproduce approximately **0.0207 mm** ideal-clamped
  and **0.0829 mm** simply-supported displacement at 30 kPa. These are not contact,
  preload or gasket-reaction solutions.
- Nominal M5x25 engagement is **10.50 mm**, with **10.25-10.75 mm** arithmetic
  range for the specified stack.
- All exported individual parts passed STEP dimension/volume round-trip checks;
  all four modeled fluid domains are single connected solids.

## Release blockers

The original report uses nominal gasket cross-sections and a rounded plate
boundary-condition factor. See the parent repository's
[corrected screening discussion](../docs/theory_and_methods.md#corrected-tolerance-and-plate-screening)
before using its arithmetic. Regeneration preserves the original CAD screening
implementation; the analysis package emits separately versioned corrections.

Before machining or pressure-rating, resolve and physically verify the actual
O-rings and rib-gasket compound/force/durability, clamp preload and nonlinear
opening, conditioned polymer fit and registration, heater/contact/sensor details,
actual fittings and hardware, tool access, leakage, maximum loop pressure and
thermal observability. The PDFs preserve the full inspection and release list.
