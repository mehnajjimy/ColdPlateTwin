# CAD and models

The Rev A cold-plate CAD is preliminary hardware that isn't approved for machining or rated for pressure. The analysis code doesn't use a CAD kernel, and its hydraulic numbers come from a simple resistance network with loss coefficients nobody has measured. Back to the [README](../README.md).

> [!NOTE]
> <sub>STEP: a common CAD exchange file · CadQuery: Python library the geometry is generated from · FreeCAD: open-source CAD program · BOM: bill of materials · loss coefficient: number that says how much pressure a bend or fitting costs · resistance network: pipe flow treated as connected resistances · kernel: the engine inside CAD software that builds solid shapes</sub>

## Looking at the CAD

Open [`freecad/ColdPlate_RevA.FCStd`](../freecad/ColdPlate_RevA.FCStd) in FreeCAD to look at the imported assembly, or use [the assembled STEP](../exports/step/CP-REV-A_assembly_FI-100.step). The assembly has 51 solids. It is a native import, not a fully parametric FreeCAD feature history.

## Changing the geometry

To change the geometry, edit `cadquery/coldplate/config.py` and follow [the CadQuery regeneration instructions](../cadquery/README.md). CadQuery is where the geometry is generated from.

After a config change you need to regenerate the geometry, check the dimensions and redo the consistency audit. Don't trust any new model output before that.

## Supporting documents

The [dimensioned drawing set](../drawings/coldplate_revA_dimensioned_drawings.pdf), [CAD validation report](../drawings/coldplate_revA_validation_report.pdf) and [bill of materials](../exports/reports/bom.csv) cover the preliminary hardware. [Theory and methods](theory_and_methods.md#corrected-tolerance-and-plate-screening) explains the corrected seal and plate screening that the software uses. The original CAD reports are kept as a record of what was exported at the time.

## How the code uses the CAD

The analysis package doesn't use a CAD kernel. It reads a small SI adapter and doesn't rerun the CAD during a normal analysis.

The hydraulic results come from a simple resistance network with loss coefficients that you can edit and that nobody has measured. It leaves out detailed junction and transfer losses, so don't use it to size a pump.

## What it doesn't show

The Rev A design is still preliminary and [not approved for machining or rated for pressure](../reference/DEPARTURES.md). This repo doesn't set any operating or proof pressure, bolt torque, heater rating or cutoff value.

Sources: cadquery/, freecad/, exports/, drawings/, reference/DEPARTURES.md, src/coldplatetwin/
