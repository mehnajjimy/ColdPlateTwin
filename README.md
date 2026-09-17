# ColdPlateTwin — Rev A

ColdPlateTwin combines parametric CAD, experiment analysis, and reduced-order thermal–hydraulic models for a water-cooled testbed with interchangeable flow inserts. It turns time-stamped logger data and optional radiometric-temperature matrices into calorimetry, stability checks, uncertainty estimates, and surface-temperature metrics.

![Labeled Blender overview of the proposed ColdPlateTwin experiment](docs/figures/experiment_overview.png)

*Proposed experimental arrangement, rendered in Blender using the Rev A cold-plate CAD. Ancillary equipment and layout are schematic and not to scale; this is not an as-built photograph or a thermal simulation result.*

[Theory and methods](docs/theory_and_methods.md) · [Experiment protocol](docs/experiment_protocol.md) · [CAD assembly](freecad/ColdPlate_RevA.FCStd) · [Blender scene and render source](visualization/README.md)

**Status:** software-tested prototype with preliminary CAD and synthetic examples. Physical calibration, experimental validation, machining approval, and pressure qualification remain outstanding.

## Questions the planned experiment can answer

- Under matched, steady operating conditions, how do inserts change measured heat to water, pressure drop, surface temperature statistics, and their uncertainty?
- Does the measured energy balance close within its uncertainty after accounting for environmental losses and transient storage?
- Which differences remain after accounting for shared sensor calibration effects?

Those are experimental questions. The included thermal calculation imposes sensitivity patterns for the coolant-side heat-transfer coefficient `h`; it does **not** predict `h` from insert geometry or flow, coolant warming, or establish an insert ranking.

## What is in the repository

| Area | What it provides | Status |
|---|---|---|
| `cadquery/` | Regeneration source and shared CAD configuration | Preserved source; regenerate and inspect after changes |
| `freecad/` | Imported 51-solid assembly and conversion script | Native import, not a fully parametric FreeCAD feature history |
| `drawings/`, `exports/` | Rev A drawings, STEP/STL/DXF exports and validation evidence | Preliminary engineering artifacts, not release approval |
| `visualization/` | Editable Blender scene, build script, and metre-scaled CAD mesh | Schematic proposed apparatus |
| `src/coldplatetwin/` | Analysis, stability, uncertainty, hydraulics, thermal sensitivity and dashboard code | Tested offline workflow |
| `configs/demo.json` | Explicit demo/model assumptions and provisional acceptance criteria | Editable analysis configuration |
| `docs/` | [Theory and methods](docs/theory_and_methods.md), [proposed experiment protocol](docs/experiment_protocol.md), and [software verification](docs/verification.md) | Documentation |

## Install and run

Python 3.11–3.14 is supported; Python 3.12 is the reference version used by CI. Installation does not require CAD software, instruments, a GPU, or a paid solver. See [software verification](docs/verification.md) for tested environments and scope.

```sh
cd /path/to/ColdPlateTwin
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dashboard,test]'
coldplate demo --config configs/demo.json --output outputs/demo
python -m pytest
```

On Windows PowerShell, create the environment with `py -m venv .venv` and activate it with `.\.venv\Scripts\Activate.ps1`; the installation and `coldplate` commands are the same.

The default demonstration creates four accepted synthetic runs and one rejected run. Its numbers are fixture checks, not experimental results or a design ranking. Generated output is intentionally ignored by Git; use a fresh directory when inputs change.

![Synthetic time traces from the checked-in demonstration](docs/figures/synthetic_time_traces.png)

*Synthetic logger fixture, not measured apparatus data. It illustrates the calibrated channels and the analysis workflow only.*

![Synthetic imposed-h thermal scenario](docs/figures/synthetic_thermal_map.png)

*Model-only temperature scenario using imposed coolant-side `h`; it is not an IR measurement, CFD result, or insert prediction.*

To inspect the local dashboard after generating/importing a bundle:

```sh
coldplate dashboard --data outputs/demo
```

It binds to localhost (normally port 8501). Stop it with `Ctrl-C`.

## Analyze logger data

Input CSV columns are `timestamp`, `flow_lpm`, `tin_c`, `tout_c`, `dp_pa`, `ambient_c`, `heater_voltage_v`, and `heater_current_a`. Metadata declares UTC ISO-8601 timestamps, units, run provenance, geometry hash, calibrations, synchronization, and uncertainty records. The importer rejects wrong units and malformed numeric values rather than silently converting them.

```sh
coldplate analyze logger.csv metadata.json \
  --config configs/demo.json \
  --output outputs/imported-run
```

For a corrected radiometric temperature-matrix CSV, add a declared parser configuration and physical ROI configuration:

```sh
coldplate analyze logger.csv metadata.json \
  --config configs/demo.json \
  --ir radiometric.csv --ir-config radiometric_config.json --roi-config roi_config.json \
  --output outputs/imported-run
```

Only timestamped IR frames inside the accepted averaging interval contribute to ROI metrics; untimed frames are retained for viewing but are not assigned a time. A passing analysis exits 0. A rejected steady state exits 2 and still writes a diagnostic bundle. Omit all three IR options when no IR export is available. Do not present synthetic fixtures as measurements.

## CAD and model provenance

Open `freecad/ColdPlate_RevA.FCStd` in FreeCAD to inspect the imported assembly, or use [the assembled STEP](exports/step/CP-REV-A_assembly_FI-100.step). For a geometry change, edit `cadquery/coldplate/config.py` and follow [the CadQuery regeneration instructions](cadquery/README.md). CadQuery is the regeneration source; changing the configuration requires regenerated geometry, dimensional checks, and a fresh consistency audit before interpreting new model output.

The [dimensioned drawing set](drawings/coldplate_revA_dimensioned_drawings.pdf), [CAD validation report](drawings/coldplate_revA_validation_report.pdf), and [bill of materials](exports/reports/bom.csv) document the preliminary hardware. The software's corrected seal/plate screening is explained in [Theory and methods](docs/theory_and_methods.md#corrected-tolerance-and-plate-screening); the original CAD reports are preserved as historical export evidence.

The numerical package reads a lightweight SI adapter rather than CAD kernels. It does not rerun CAD during ordinary analysis. Its hydraulic results are reduced resistance-network screens with editable, unmeasured loss coefficients; they omit detailed junction/transfer losses and are not pump-sizing predictions. The Rev A design remains preliminary and [not machining approved or pressure rated](reference/DEPARTURES.md).

## Interpretation limits

- Water properties are interpolated from a rounded 15–70 °C pure-water table; mixtures and out-of-range temperatures fail explicitly.
- Stability thresholds in `configs/demo.json` are provisional acceptance criteria, not safety limits.
- Instrument uncertainty is available only when the required calibrated sensor specifications are supplied. It is not a substitute for calibration or repeatability evidence.
- An upper-surface IR map cannot uniquely identify fine coolant-side `h`: spreading, contact resistance, heater distribution, emissivity/registration, and environmental loss can produce similar surface effects.
- No operating/proof pressure, bolt torque, heater rating, or cutoff value is authorized by this repository. An independent hardware cutoff is required for the planned experiment.

For assumptions, equations, and limits, read [Theory and methods](docs/theory_and_methods.md). For practical data collection, read the [proposed experiment protocol](docs/experiment_protocol.md). Reproducible software checks are summarized in [Verification](docs/verification.md).
