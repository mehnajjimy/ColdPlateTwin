"""Import the validated Rev A assembly STEP and save a native FreeCAD document.

Run with FreeCAD's Python runtime:
    freecadcmd create_freecad_model.py INPUT.step OUTPUT.FCStd
"""

from pathlib import Path
import sys

import FreeCAD as App
import Import


def main() -> None:
    here = Path(__file__).resolve().parent
    # FreeCADCmd may treat trailing arguments as documents to open. With no
    # explicit arguments, use the canonical assembly in exports/step.
    if len(sys.argv) >= 3:
        source = Path(sys.argv[-2]).resolve()
        output = Path(sys.argv[-1]).resolve()
    else:
        source = here.parent / "exports" / "step" / "CP-REV-A_assembly_FI-100.step"
        output = here / "ColdPlate_RevA.FCStd"
    if not source.is_file():
        raise FileNotFoundError(source)
    output.parent.mkdir(parents=True, exist_ok=True)

    doc = App.newDocument("ColdPlate_RevA")
    Import.insert(str(source), doc.Name)
    info = doc.addObject("App::FeaturePython", "Package_Information")
    info.addProperty("App::PropertyString", "Status", "Rev_A")
    info.Status = "PRELIMINARY ENGINEERING - NOT MACHINING APPROVED"
    info.addProperty("App::PropertyString", "CoordinateSystem", "Rev_A")
    info.CoordinateSystem = "CP-001 sealing deck z=0; cavity x=y=0; ports on x-axis"
    info.addProperty("App::PropertyString", "SourceSTEP", "Rev_A")
    info.SourceSTEP = source.name
    doc.recompute()
    doc.saveAs(str(output))
    print(f"Saved {output} with {len(doc.Objects)} document objects")


if __name__ == "__main__":
    main()
