"""Mandatory CadQuery STEP round-trip smoke test for the Rev A package."""

from pathlib import Path

import cadquery as cq
from cadquery import exporters, importers


def main() -> None:
    out = Path("build/smoke")
    out.mkdir(parents=True, exist_ok=True)
    source = cq.Workplane("XY").box(20.0, 30.0, 10.0, centered=(True, True, False))
    step_path = out / "cq_smoke_box.step"
    exporters.export(source, str(step_path))
    loaded = importers.importStep(str(step_path)).val()
    bb = loaded.BoundingBox()
    dims = (bb.xlen, bb.ylen, bb.zlen)
    expected = (20.0, 30.0, 10.0)
    assert all(abs(a - b) < 1e-6 for a, b in zip(dims, expected)), (dims, expected)
    assert abs(loaded.Volume() - 6000.0) < 1e-5, loaded.Volume()
    print(
        "PASS simple solid STEP round trip: "
        f"dimensions={dims}, volume={loaded.Volume():.6f} mm^3"
    )


if __name__ == "__main__":
    main()
