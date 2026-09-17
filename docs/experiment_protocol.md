# Proposed experiment protocol

This is a practical data-collection plan, not a safety authorization. No as-built or physical-validation evidence is included in this repository. Select rated hardware, obtain institutional/lab approval, and use an independent heater cutoff before applying power. This repository does not specify operating/proof pressure, bolt torque, heater rating, or a cutoff setpoint.

## 1. Pre-test records and dimensional inspection

1. Assign a run ID, insert ID, operator, date/time zone, CAD geometry hash, and assembly revision.
2. Inspect and record the relevant measured dimensions, flatness/condition observations, seal lot and supplier tolerances, insert fit, port/fitting selection, and any departures. Do not treat nominal CAD dimensions as as-built measurements.
3. Record selected heater, insulation/coating, electrical isolation, leads, fittings, pressure boundary components, and independent cutoff. Their ratings and installation instructions come from their manufacturers and local safety process, not this software.
4. Record flowmeter location, sensor serials/calibration IDs, calibration dates, units, synchronization method, camera configuration, pixel scale, ROI geometry, and occlusions.

The original release blockers remain active: gasket/clamp behavior, conditioned polymer fit, actual fittings, leakage, local gauge pressure, heater/contact details, and thermal observability have not been qualified.

## 2. Instrument pair calibration

Before comparative runs, calibrate or verify the inlet/outlet temperature pair together over the intended measurement range. Record the post-calibration standard uncertainty for flow, inlet/outlet temperature, voltage, current, and differential pressure; record distribution type, bound where relevant, calibration IDs, and defensible pair correlations. Do not use an assumed default in place of missing records.

Establish timestamp time zones and synchronization across logger, heater power, flow/pressure, and camera. Verify the actual vendor radiometric export: corrected-temperature status, absolute accuracy, emissivity/reflection workflow, frame dimensions, timing, registration, and occlusion mask. A colored image is not a valid numerical temperature matrix.

## 3. Unheated checks

With no heater input, perform a controlled leakage and bypass check using the lab-approved hardware procedure. Record visible leakage, flow path observations, inlet/outlet/differential-pressure behavior, and ambient condition. Treat a bypass path, unstable flow, missing channels, or a suspect seal as a stop-and-resolve condition—not a value for the analysis pipeline to repair.

Keep the distinction between test-section differential pressure and maximum local gauge pressure: the first may be logged for hydraulic power; neither software output establishes the latter.

## 4. Low-power baseline

Run a low-power, conservative baseline only within the selected hardware limits. Log the required channels continuously: `timestamp`, `flow_lpm`, `tin_c`, `tout_c`, `dp_pa`, `ambient_c`, `heater_voltage_v`, and `heater_current_a`; add surface-reference channels where available. Capture corrected radiometric matrices only after the camera workflow is established.

Use the configured screen as a data-quality gate, not a safety controller. The default configuration checks a 300 s screen followed by a 180 s average and their combined 480 s span, with 90% complete-channel coverage, ≤5 s gaps, ≤0.03 K/min thermal slope, ≤0.3 K thermal step, and ≤1% flow/power CV. It also requires flow above 0.05 L/min and power above 5 W for the screening metric. All values are provisional and must be justified or revised in the saved configuration for the actual test.

## 5. Comparative steady-state runs

1. Select a declared operating matrix after hardware qualification. The checked-in configuration generates a **proposed DOE manifest** with 0.5, 1.0, and 1.5 L/min and 100, 175, and 250 W levels; it is not a fixture-run condition or a physical authorization. The default generated synthetic runs instead use 1.0 L/min and 180 W.
2. Hold the same documented boundary conditions for each comparison: coolant source condition, selected flow, power command/measurement, ambient condition, insulation state, sensor configuration, camera setup, and assembly procedure.
3. Start logging before the expected steady period. Do not manually crop data to force acceptance; retain raw data and metadata.
4. Let the analysis choose the first interval that passes all three stability spans. A rejection exits with a diagnostic bundle; investigate the recorded reason rather than relabeling the run.
5. For optional IR, include only timestamped frames in the accepted averaging interval for thermal metrics. Preserve untimed frames separately and never invent their times.

## 6. Randomization, replication, and holds

Use randomized insert order within each contiguous replicated operating block. Keep development-envelope trials separate from confirmatory comparison blocks. The default synthetic demonstration has two blocks of 36 DOE rows plus four separately appended development rows; it is an example of bookkeeping, not physical evidence.

Replicate enough times to expose repeatability and systematic drift. Include matched boundary-condition repeats and, before a performance statement, reserve held-out runs. When sensor calibration IDs are shared, carry their covariance into A−B uncertainty; do not claim calibration bias cancels without evidence.

## 7. Analysis and release of results

Run analysis against an explicit saved configuration and archive, together, the raw CSV, metadata, effective configuration/hash, calibrated trace, accepted/rejected diagnostics, input hashes, and optional IR parser/ROI files. A typical command is:

```sh
coldplate analyze logger.csv metadata.json \
  --config configs/demo.json \
  --ir radiometric.csv --ir-config radiometric_config.json --roi-config roi_config.json \
  --output outputs/run
```

Report at minimum: accepted interval; heat to water; electrical and hydraulic power; energy residual and closure; flow, temperatures, and test-section differential pressure; ROI usable pixels/mean/maximum/standard deviation/peak-to-peak where valid; uncertainty status and standard uncertainties; calibration IDs/correlations; and all warnings/applicability messages. Clearly label synthetic fixtures, imposed-`h` thermal scenarios, and reduced hydraulic screens as such.

Do not infer a fine coolant-side heat-transfer map or select a winning insert from upper-surface IR alone. Interpret results only after checking energy closure, uncertainty completeness, replicate consistency, sensor/calibration provenance, hardware observations, and the documented model limits in [theory and methods](theory_and_methods.md).

## Run record checklist

| Record group | Required examples |
|---|---|
| Identity | Run ID, insert, operator, UTC timestamps, assembly/CAD hash |
| Boundary conditions | Coolant source condition, flow setpoint and measured flow, ambient, power command and measured V/I |
| Instruments | Serial/calibration IDs, post-calibration uncertainty, correlations, synchronization, flowmeter location |
| Hardware observations | Seal/fit condition, leakage/bypass observations, insulation/contact state, anomalies and stop reasons |
| IR (if used) | Corrected-export declaration, camera accuracy, frame timing, pixel scale, ROI/occlusion files, registration notes |
| Analysis provenance | Raw-file hashes, configuration/hash, accepted/rejected diagnostics, software version, output-bundle path |

Physical evidence still needed includes calibrated sensor behavior, actual camera export validation, contact/heater characterization, leakage and local-pressure qualification, and replicated comparisons under matched conditions.
