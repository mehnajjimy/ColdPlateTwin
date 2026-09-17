# Software verification

Publication checks on 2026-09-17 used a fresh macOS ARM64 virtual environment with Python 3.14 and an editable installation of `.[dashboard,test]`.

| Check | Result |
|---|---|
| Complete pytest suite | 48 passed |
| Installed `coldplate demo` command, without a `PYTHONPATH` override | Completed; 4 accepted synthetic runs, 1 rejected run |
| `python -m pip check` | No broken requirements |
| FreeCAD conversion and Blender build scripts | Python syntax checked |
| Published overview and close-up | Byte-identical to the supplied final render package |

The fresh environment resolved NumPy 2.5.3, SciPy 1.18.1, pandas 3.0.5, Matplotlib 3.11.2, Streamlit 1.64.0, and pytest 9.1.1. The package declares Python 3.11–3.14 compatibility; this check does not establish testing on every declared version.

Earlier minimum-dependency verification recorded Python 3.12.14, NumPy 1.26.4, SciPy 1.12.0, pandas 2.2.0, and Matplotlib 3.8.0 in a non-editable wheel environment: 47 tests passed, one optional Streamlit test skipped, and dependency checks passed. The checked-in GitHub workflow exercises minimum and current dependencies on Python 3.12; see its run status for remote results.

From the repository root, after installing the package:

```sh
python -m pytest
python -m pip check
coldplate demo --config configs/demo.json --output outputs/demo
```

Tests cover data validation, stability gates, uncertainty propagation and covariance, timestamped IR selection, configurable synthetic generation, model geometry sensitivity, numerical residuals, dashboard bundles, and the installed command-line workflow.

These checks establish software behavior for tested cases. They do not validate the physical apparatus, sensor calibration, heat-transfer predictions, manufacturing tolerances, or pressure safety. The Blender scene was not rerendered during publication; its supplied images are schematic illustrations. CAD remains preliminary, with historical export checks retained in `exports/reports/` and `drawings/`.
