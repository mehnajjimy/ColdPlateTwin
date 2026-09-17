"""Create dimensioned drawing and validation-report PDFs from shared parameters."""

from __future__ import annotations

import json
import hashlib
from math import cos, pi, radians, sin
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A3, A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from coldplate.analysis import calculate
from coldplate.config import P


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "pdf"
REPORTS = ROOT / "build" / "reports"
OUT.mkdir(parents=True, exist_ok=True)


def title_block(c: canvas.Canvas, sheet: str, title: str, scale: str = "NTS") -> None:
    w, h = landscape(A3)
    c.setStrokeColor(colors.HexColor("#23384D"))
    c.setLineWidth(0.5)
    c.rect(10 * mm, 10 * mm, w - 20 * mm, h - 20 * mm)
    c.line(10 * mm, 28 * mm, w - 10 * mm, 28 * mm)
    c.line(w - 120 * mm, 10 * mm, w - 120 * mm, 28 * mm)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(14 * mm, 20 * mm, title)
    c.setFont("Helvetica", 8)
    c.drawString(14 * mm, 14 * mm, "STATUS: PRELIMINARY ENGINEERING - NOT MACHINING APPROVED")
    c.drawString(w - 116 * mm, 20 * mm, f"SHEET {sheet}   SCALE {scale}   UNITS mm")
    c.drawString(w - 116 * mm, 14 * mm, "REV A   INSPECTION NEAR 20 C")
    c.setFillColor(colors.HexColor("#C43B3B"))
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(w - 14 * mm, h - 16 * mm, "RELEASE ITEMS OPEN - SEE VALIDATION REPORT")
    c.setFillColor(colors.black)


def arrow(c: canvas.Canvas, x1, y1, x2, y2, text: str, offset=0) -> None:
    c.setStrokeColor(colors.HexColor("#304A62"))
    c.setFillColor(colors.HexColor("#304A62"))
    c.setLineWidth(0.45)
    c.line(x1, y1, x2, y2)
    ang = __import__("math").atan2(y2 - y1, x2 - x1)
    for x, y, a in ((x1, y1, ang), (x2, y2, ang + pi)):
        c.line(x, y, x + 3 * mm * cos(a + 0.35), y + 3 * mm * sin(a + 0.35))
        c.line(x, y, x + 3 * mm * cos(a - 0.35), y + 3 * mm * sin(a - 0.35))
    c.setFont("Helvetica", 8)
    c.drawCentredString((x1 + x2) / 2, (y1 + y2) / 2 + 2 * mm + offset, text)
    c.setFillColor(colors.black)


def notes(c: canvas.Canvas, x: float, y: float, lines: list[str], width=100 * mm) -> None:
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x, y, "NOTES")
    c.setFont("Helvetica", 7.4)
    yy = y - 5 * mm
    for i, line in enumerate(lines, 1):
        words = line.split()
        chunks, current = [], ""
        for word in words:
            if c.stringWidth(current + " " + word, "Helvetica", 7.4) > width:
                chunks.append(current)
                current = word
            else:
                current = (current + " " + word).strip()
        chunks.append(current)
        for j, chunk in enumerate(chunks):
            prefix = f"{i}. " if j == 0 else "   "
            c.drawString(x, yy, prefix + chunk)
            yy -= 3.8 * mm


def draw_top_base(c: canvas.Canvas, ox: float, oy: float, s: float) -> None:
    c.setLineWidth(0.6)
    c.rect(ox - 100 * s, oy - 100 * s, 200 * s, 200 * s)
    c.circle(ox, oy, 82.5 * s)
    c.circle(ox, oy, P.main_groove_od / 2 * s)
    c.circle(ox, oy, P.main_groove_id / 2 * s)
    for i in range(P.bolt_count):
        a = radians(P.bolt_offset_deg + i * 360 / P.bolt_count)
        c.circle(ox + P.bolt_radius * cos(a) * s, oy + P.bolt_radius * sin(a) * s, 2.1 * s)
    for x in (-P.transfer_x, P.transfer_x):
        c.circle(ox + x * s, oy, P.insert_transfer_diameter / 2 * s)
        c.circle(ox + x * s, oy, P.transfer_groove_od / 2 * s)
    c.setDash(2, 2)
    c.line(ox - 110 * s, oy, ox + 110 * s, oy)
    c.line(ox, oy - 110 * s, ox, oy + 110 * s)
    c.setDash()


def draw_insert_variant(c: canvas.Canvas, ox: float, oy: float, s: float, variant: str) -> None:
    c.circle(ox, oy, P.insert_od / 2 * s)
    c.circle(ox, oy, 80 * s)
    if variant == "FI-000":
        c.setFont("Helvetica", 7)
        c.drawCentredString(ox, oy, "OPEN PLENUM")
    elif variant == "FI-100":
        ys = [(i - 4) * 12 for i in range(9)]
        for i, y in enumerate(ys):
            c.line(ox - 48 * s, oy + y * s, ox + 48 * s, oy + y * s)
            if i < 8:
                x = ox + (48 if i % 2 == 0 else -48) * s
                c.arc(x - 6 * s, oy + (y + 6 - 6) * s, x + 6 * s, oy + (y + 12 + 6) * s, -90 if i % 2 == 0 else 90, 180)
    else:
        for y in P.fi200_centers_y:
            c.rect(ox - 48 * s, oy + (y - 4) * s, 96 * s, 8 * s)
        c.rect(ox - 60 * s, oy - 48 * s, 12 * s, 96 * s)
        c.rect(ox + 48 * s, oy - 48 * s, 12 * s, 96 * s)
        if variant == "FI-300":
            c.setFont("Helvetica", 6.5)
            c.drawCentredString(ox, oy - 69 * s, "TAPER 12 AT FEED TO 6 AT ENDS")
    for x in (-70, 70):
        c.circle(ox + x * s, oy, 3.6 * s)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(ox, oy + 90 * s, variant)


def create_drawings(path: Path) -> None:
    size = landscape(A3)
    c = canvas.Canvas(str(path), pagesize=size)
    w, h = size

    title_block(c, "1/6", "CP-REV-A GENERAL ARRANGEMENT")
    draw_top_base(c, 108 * mm, 155 * mm, 0.82 * mm)
    arrow(c, 26 * mm, 45 * mm, 190 * mm, 45 * mm, "200.00 +/-0.10")
    # Parametric section stack.
    x0, y0, sw = 235 * mm, 72 * mm, 0.75 * mm
    c.setFillColor(colors.HexColor("#B8C0C8")); c.rect(x0, y0, 200 * sw, 25 * sw, fill=1)
    c.setFillColor(colors.HexColor("#E6DDAD")); c.rect(x0 + 18.2 * sw, y0 + 20 * sw, 163.6 * sw, 3.5 * sw, fill=1)
    c.setFillColor(colors.HexColor("#9FC0D8")); c.rect(x0, y0 + 25 * sw, 200 * sw, 5.5 * sw, fill=1)
    c.setFillColor(colors.HexColor("#555B61")); c.rect(x0, y0 + 30.5 * sw, 17 * sw, 8 * sw, fill=1); c.rect(x0 + 183 * sw, y0 + 30.5 * sw, 17 * sw, 8 * sw, fill=1)
    c.setFillColor(colors.HexColor("#D5D9DD")); c.rect(x0 + 20 * sw, y0 + 31.5 * sw, 160 * sw, 2 * sw, fill=1)
    c.setFillColor(colors.black)
    for z, label in ((0, "CP-001 BASE"), (25, "z=0 SEALING DECK"), (30.5, "CP-002 COVER 5.50"), (38.5, "CL-002 8.00")):
        c.setFont("Helvetica", 7); c.drawString(x0 + 205 * sw, y0 + z * sw, label)
    c.setFont("Helvetica-Bold", 8); c.drawString(x0, y0 + 44 * sw, "SECTION A-A (ASSEMBLED)")
    # Exploded schematic, with layers separated for identification.
    ex, ey, ew = 255 * mm, 132 * mm, 0.60 * mm
    c.setFont("Helvetica-Bold", 8); c.drawString(ex, ey + 69 * mm, "EXPLODED VIEW (SCHEMATIC)")
    layers = [
        ("CL-002", 200, 8, colors.HexColor("#555B61")),
        ("TH-001 / CL-001", 164, 4, colors.HexColor("#D5D9DD")),
        ("HEATER ENVELOPE", 150, 1, colors.HexColor("#D88C3A")),
        ("CP-002", 200, 5.5, colors.HexColor("#9FC0D8")),
        ("FI-100 + GASKET", 163.6, 3.5, colors.HexColor("#E6DDAD")),
        ("CP-001", 200, 25, colors.HexColor("#B8C0C8")),
    ]
    yy = ey + 54 * mm
    for label, width, thick, fill in layers:
        layer_h = min(6 * mm, max(2.2 * mm, thick * 0.30 * mm))
        c.setFillColor(fill); c.rect(ex, yy, width * ew, layer_h, fill=1)
        c.setFillColor(colors.black); c.setFont("Helvetica", 6.5); c.drawString(ex + width * ew + 3 * mm, yy, label)
        yy -= 10 * mm
    notes(c, 235 * mm, 245 * mm, [
        P.datum_note + ".",
        "Assembly shown with FI-100. FI-000, FI-200 and FI-300 exchange without changing the base, cover or transfer interface.",
        "Thirty kPa gauge is an analysis load case only, not a certified rating.",
        "No heater or sensor holes penetrate CP-002. Heater envelope, coating, sensors and interface resistance remain unresolved.",
        "Camera line of sight to the centered 150 diameter ROI is unobstructed.",
    ], 145 * mm)
    c.showPage()

    title_block(c, "2/6", "CP-001 BASE - DIMENSIONED PRELIMINARY")
    draw_top_base(c, 125 * mm, 155 * mm, 0.88 * mm)
    arrow(c, 37 * mm, 47 * mm, 213 * mm, 47 * mm, "200.00 +/-0.10")
    arrow(c, 125 * mm, 65 * mm, 197.6 * mm, 65 * mm, "R82.50 +0.025/-0")
    arrow(c, 125 * mm, 58 * mm, 207.7 * mm, 58 * mm, "GROOVE OD 176.35 +0.05/-0")
    c.setFont("Helvetica-Bold", 8); c.drawString(255 * mm, 235 * mm, "SECTION A-A")
    c.rect(255 * mm, 125 * mm, 130 * mm, 16.25 * mm)
    c.rect(272 * mm, 138 * mm, 96 * mm, 3.25 * mm)
    c.line(255 * mm, 141.25 * mm, 385 * mm, 141.25 * mm)
    arrow(c, 390 * mm, 125 * mm, 390 * mm, 141.25 * mm, "25.00 +/-0.10", 0)
    arrow(c, 373 * mm, 138 * mm, 373 * mm, 141.25 * mm, "5.00 +/-0.02", 0)
    c.setFont("Helvetica", 7.5)
    c.drawString(255 * mm, 112 * mm, "SIDE PORT AXES y=0, z=-14; candidate 1/4-18 NPT")
    c.drawString(255 * mm, 106 * mm, "INTERNAL DRILLS 6 nominal; vertical transfers x=+/-70")
    c.drawString(255 * mm, 100 * mm, "TRANSFER GLANDS: OD 14.38, width 2.50, depth 1.35")
    notes(c, 255 * mm, 85 * mm, [
        "Material 6061 aluminum; use stress-relieved stock where available. Starting stock 203.2 x 203.2 x 25.4 nominal.",
        "Deck flatness target 0.02; pocket-floor flatness target 0.03. Inspect without artificially flattening part.",
        "Main gland width 3.70 +/-0.05, depth 2.12 +/-0.02, bottom R0.30 nominal, axis position diameter 0.05 relative to cavity axis.",
        "Sealing face Ra <=0.8 micrometre; gland Ra <=1.6 micrometre.",
        "Two static taps are modeled from the front edge to the defined transfer centers. Select actual fittings before release.",
    ], 145 * mm)
    c.showPage()

    title_block(c, "3/6", "CP-002 COVER AND CL-002 STRUCTURAL CLAMP")
    for ox, label, aperture in ((115 * mm, "CP-002 COVER", None), (300 * mm, "CL-002 STRUCTURAL CLAMP", 166.0)):
        c.rect(ox - 75 * mm, 80 * mm, 150 * mm, 150 * mm)
        if aperture:
            c.circle(ox, 155 * mm, aperture / 2 * 0.75 * mm)
        for i in range(16):
            a = radians(11.25 + i * 22.5)
            c.circle(ox + 94 * cos(a) * 0.75 * mm, 155 * mm + 94 * sin(a) * 0.75 * mm, 2.75 * 0.75 * mm)
        c.setFont("Helvetica-Bold", 9); c.drawCentredString(ox, 245 * mm, label)
    arrow(c, 44.5 * mm, 65 * mm, 185.5 * mm, 65 * mm, "PCD 188 BASIC - 16 EQ SP @ 22.5 deg; OFFSET 11.25 deg")
    notes(c, 225 * mm, 65 * mm, [
        "Cover 200 x 200 x 5.50 +/-0.05; water-facing flatness 0.03; face parallelism 0.03.",
        "Clamp 200 x 200 x 8.00 +/-0.10; aperture diameter 166.00 +0.10/-0.00.",
        "Both parts: clearance holes diameter 5.50 +0.10/-0.00; position diameter 0.10 to assembly datums.",
        "Modeled M5x25 plus 1 mm washer stack gives 10.25-10.75 engagement. Verify actual screw, washer, thread runout and drill point.",
        "Tightening torque is intentionally unspecified pending material, lubrication, preload and gasket-reaction definition.",
    ], 175 * mm)
    c.showPage()

    title_block(c, "4/6", "COMMON INSERT INTERFACE AND FLOW VARIANTS")
    centers = [(72, 185), (190, 185), (308, 185), (72, 83)]
    for (x, y), variant in zip(centers, ("FI-000", "FI-100", "FI-200", "FI-300")):
        draw_insert_variant(c, x * mm, y * mm, 0.60 * mm, variant)
    notes(c, 175 * mm, 102 * mm, [
        "Common circumscribed insert OD 163.60 +/-0.05; nominal floor 1.00 +/-0.03; machined POM-C final candidate.",
        "PETG meshes are prototypes and do not inherit machined-part tolerances.",
        "Round locator at y=+70 and radial slot at y=-70 control rotation while permitting radial expansion about center.",
        "FI-100 nominal CAD centerline length is reported in the validation report; it is not assumed to be 1.5 m.",
        "FI-300 remains a tapered-manifold candidate until hydraulic modeling demonstrates improvement.",
        "All variants use isolated transfer face seals, a perimeter rib seal and positively registered internal strip seals.",
    ], 210 * mm)
    c.showPage()

    title_block(c, "5/6", "TH-001, CL-001 AND BR-001")
    c.circle(105 * mm, 155 * mm, 80 * mm)
    c.circle(105 * mm, 155 * mm, 75 * mm)
    c.setFont("Helvetica-Bold", 9); c.drawCentredString(105 * mm, 247 * mm, "TH-001 PAYLOAD / ROI")
    arrow(c, 25 * mm, 62 * mm, 185 * mm, 62 * mm, "PAYLOAD DIA 160.00")
    arrow(c, 30 * mm, 53 * mm, 180 * mm, 53 * mm, "ANALYSIS ROI DIA 150.00 - KEEP CLEAR")
    c.circle(285 * mm, 155 * mm, 82 * mm)
    c.circle(285 * mm, 155 * mm, 75.25 * mm)
    c.setFont("Helvetica-Bold", 9); c.drawCentredString(285 * mm, 247 * mm, "CL-001 PROVISIONAL CLAMP")
    c.setFont("Helvetica", 8); c.drawString(220 * mm, 57 * mm, "OD 164; ID 150.5; thickness 4; 3 adjustment slots")
    c.setFont("Helvetica-Bold", 9); c.drawString(342 * mm, 230 * mm, "BR-001")
    c.rect(342 * mm, 170 * mm, 45 * mm, 30 * mm); c.rect(342 * mm, 125 * mm, 6 * mm, 75 * mm)
    c.circle(375 * mm, 185 * mm, 4 * mm)
    c.setFillColor(colors.white); c.setStrokeColor(colors.HexColor("#8293A3")); c.rect(205 * mm, 82 * mm, 200 * mm, 45 * mm, fill=1, stroke=1); c.setFillColor(colors.black)
    notes(c, 210 * mm, 120 * mm, [
        "Payload 160 diameter x 2.00 +/-0.05 aluminum; coating and contact-sensor locations TBD.",
        "Heater is represented only by a 150 diameter x 1 envelope. Resistive pattern, thickness, lead exit, mounting and interface resistance are not invented.",
        "CL-001 is separate from CL-002 and preserves the 150 diameter camera ROI.",
        "BR-001 uses dry underside attachment holes at x,y=+/-75, 8 deep, remote from wet passages. Verify bench fasteners and hose clearance in the installed rig.",
    ], 190 * mm)
    c.showPage()

    title_block(c, "6/6", "SEALS, GASKETS AND INSPECTION PLAN")
    data = [
        ["Feature", "Nominal / tolerance", "Inspection"],
        ["AS568-166 candidate", "171.12 ID x 2.62 CS", "Supplier cert + optical / calibrated fixture"],
        ["Main gland", "OD 176.35 +0.05/-0; W 3.70 +/-0.05; D 2.12 +/-0.02", "CMM/vision OD-position; depth mic; profilometer"],
        ["AS568-013 candidate", "10.82 ID x 1.78 CS", "Supplier cert; lot verification"],
        ["Transfer gland", "OD 14.38 +0.05/-0; W 2.50 +/-0.05; D 1.35 +/-0.02", "Optical comparator/CMM; depth mic"],
        ["Rib support plane", "3.50 +/-0.03 above insert underside", "CMM height map after conditioning"],
        ["Gasket strip", "2.00 +/-0.05 W x 2.00 +/-0.05 free", "Incoming thickness/width and force-deflection lot test"],
        ["Installed gap", "1.35 to 1.75", "Feeler/replica or displacement mapping under controlled preload"],
        ["Cover opening", "additional <=0.10; local seal <=0.03", "Loaded DIC / displacement probes at 30 kPa case"],
    ]
    table = Table(data, colWidths=[42 * mm, 98 * mm, 118 * mm], rowHeights=[8 * mm] + [13 * mm] * 8)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#23384D")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("FONT", (0, 1), (-1, -1), "Helvetica", 7),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#8293A3")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF2F5")]),
    ]))
    table.wrapOn(c, w, h); table.drawOn(c, 25 * mm, 104 * mm)
    notes(c, 292 * mm, 244 * mm, [
        "Use the supplied DXF outlines as preliminary cutting geometry only; preserve separate strips where flow passages must remain open.",
        "Nominal 25 percent rib-gasket compression is geometric. Actual compound force, bulging, compression set and durability remain release checks.",
        "Flatness, thickness, position and assembled opening are distinct inspections; do not substitute one for another.",
        "Drawing dimensions override scale. Ordinary unspecified machined dimensions +/-0.10.",
    ], 105 * mm)
    c.save()


def fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, list):
        return " to ".join(fmt(v) for v in value)
    return str(value)


def create_validation_report(path: Path) -> None:
    results = calculate()
    step_validation = json.loads((REPORTS / "step_roundtrip_validation.json").read_text())
    mesh_validation = json.loads((REPORTS / "mesh_and_outline_validation.json").read_text())
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=10))
    styles.add(ParagraphStyle(name="Tiny", parent=styles["BodyText"], fontSize=6.6, leading=8))
    styles.add(ParagraphStyle(name="Status", parent=styles["Heading2"], textColor=colors.HexColor("#B22E2E"), alignment=TA_CENTER))
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
                            title="Rev A Cold-Plate Validation Report")
    story = [
        Paragraph("Interchangeable-Insert Water Cold-Plate Testbed", styles["Title"]),
        Paragraph("Rev A Preliminary Engineering Validation Report", styles["Heading2"]),
        Paragraph("NOT MACHINING APPROVED", styles["Status"]),
        Spacer(1, 4 * mm),
        Paragraph("Scope", styles["Heading2"]),
        Paragraph("This report records deterministic dimensional screening, CAD checks, export/reimport checks, inspection intent, departures and unresolved physical release work. The model is regenerable from one shared parameter file used by both CAD and calculations.", styles["BodyText"]),
        Spacer(1, 3 * mm),
        Table([
            ["Datum / axis", P.datum_note],
            ["Load case", "30 kPa coolant gauge pressure (analysis only)"],
            ["Ordinary tolerance", "+/-0.10 mm unless overridden"],
            ["Temperature range", "20-60 C component envelope"],
            ["Selected assembly", "FI-100; all four inserts exported individually"],
        ], colWidths=[42 * mm, 130 * mm], style=[("GRID", (0,0), (-1,-1), 0.4, colors.grey), ("BACKGROUND", (0,0),(0,-1), colors.HexColor("#E8EEF3")), ("FONT", (0,0),(-1,-1), "Helvetica", 8), ("VALIGN", (0,0),(-1,-1), "TOP")]),
    ]
    for section, values in results.items():
        if not isinstance(values, dict):
            continue
        story += [Spacer(1, 4 * mm), Paragraph(section.replace("_", " ").title(), styles["Heading2"])]
        rows = [["Check", "Result"]] + [[
            Paragraph(k.replace("_", " "), styles["Tiny"]),
            Paragraph(fmt(v), styles["Tiny"]),
        ] for k, v in values.items()]
        table = Table(rows, colWidths=[72 * mm, 100 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0),(-1,0), colors.HexColor("#23384D")), ("TEXTCOLOR", (0,0),(-1,0), colors.white),
            ("FONT", (0,0),(-1,0), "Helvetica-Bold", 8), ("FONT", (0,1),(-1,-1), "Helvetica", 7.2),
            ("GRID", (0,0),(-1,-1), 0.35, colors.HexColor("#8293A3")), ("VALIGN", (0,0),(-1,-1), "TOP"),
            ("ROWBACKGROUNDS", (0,1),(-1,-1), [colors.white, colors.HexColor("#F2F5F7")]),
        ]))
        story.append(table)

    story += [PageBreak(), Paragraph("STEP Export/Reimport Validation", styles["Heading1"]),
              Paragraph("Every individual STEP and each assembly STEP was reimported. Individual files were checked against source bounding dimensions and volume. Assembly files were checked for a minimum expected solid count plus aggregate envelope and volume.", styles["BodyText"])]
    rows = [["File", "Src", "Reimport", "Volume mm3", "Result"]]
    for item in step_validation["parts"]:
        rows.append([item["file"], str(item.get("source_solids", "-")), str(item["reimported_solids"]), f"{item['reimported_volume_mm3']:.2f}", "PASS" if item["pass"] else "FAIL"])
    table = Table(rows, colWidths=[75 * mm, 16 * mm, 20 * mm, 36 * mm, 18 * mm], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#23384D")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONT",(0,0),(-1,0),"Helvetica-Bold",7),("FONT",(0,1),(-1,-1),"Helvetica",5.8),("GRID",(0,0),(-1,-1),0.3,colors.grey),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F2F5F7")])]))
    story.append(table)
    story += [Spacer(1, 4 * mm), Paragraph("Fluid connectivity", styles["Heading2"])]
    for variant, state in step_validation["fluid_connectivity"].items():
        story.append(Paragraph(f"{variant}: {state['fluid_domain_solids']} connected fluid solid - {'PASS' if state['continuous'] else 'FAIL'}", styles["Small"]))
    story += [Spacer(1, 3 * mm), Paragraph("Prototype mesh and gasket-outline validation", styles["Heading2"])]
    for state in mesh_validation["meshes"]:
        story.append(Paragraph(f"{state['file']}: {state['triangles']} triangles, {state['open_or_nonmanifold_edges']} open/non-manifold edges - {'PASS' if state['pass'] else 'FAIL'}", styles["Small"]))
    for state in mesh_validation["gasket_outlines"]:
        story.append(Paragraph(f"{state['file']}: {state['imported_entities']} imported outline entities - {'PASS' if state['pass'] else 'FAIL'}", styles["Small"]))

    departures = [
        ["Item", "Departure / interpretation", "Engineering reason"],
        ["References", "No separate review or original plan was attached; this package uses the pasted Rev A brief as the controlling input.", "Avoid inventing absent source requirements."],
        ["FI-100 feeds", "Two diagonal feed transitions join the +/-70 transfer centers to the first/last 96 mm pass.", "Maintains a continuous path inside the usable disk without crossing intermediate passages."],
        ["FI-100 length", f"CAD centerline screening length {results['flow']['fi100_cad_centerline_path_length_mm']:.1f} mm, not 1.5 m.", "Measured from the modeled routing definition."],
        ["Static taps", "Two 1.5 mm bores with 5 mm thread envelopes run from the front side to the transfer centers.", "Defines flush upstream/downstream measurement locations without penetrating CP-002."],
        ["Locator", "Round pin at y=+70 and radial slot/pin at y=-70 instead of a central pin.", "Avoids the active central flow/ROI while providing one constrained and one expansion-permitting datum."],
        ["CL-001", "Envelope-level ring with three adjustment slots only.", "Actual heater thickness, lead exit and mounting remain unresolved; no false detail added."],
        ["NPT fittings", "Conservative cylindrical/hex envelope, not supplier-specific thread geometry.", "Actual fitting was not selected."],
        ["Gasket corners", "CAD cutting outlines are nominal planar geometry without die-cut corner compensation.", "Supplier/process-specific compensation is not yet available."],
    ]
    story += [PageBreak(), Paragraph("Specification Departures and Interpretations", styles["Heading1"])]
    wrapped_departures = [departures[0]] + [
        [Paragraph(str(cell), styles["Tiny"]) for cell in row] for row in departures[1:]
    ]
    t = Table(wrapped_departures, colWidths=[28 * mm, 72 * mm, 72 * mm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#23384D")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONT",(0,0),(-1,0),"Helvetica-Bold",7),("FONT",(0,1),(-1,-1),"Helvetica",6.4),("GRID",(0,0),(-1,-1),0.35,colors.grey),("VALIGN",(0,0),(-1,-1),"TOP"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F2F5F7")])]))
    story.append(t)

    release = [
        "Select and lot-verify main and transfer O-rings; recalculate Parker axial-gland squeeze, circumferential fit, volume fill, swelling and thermal effects using supplied tolerances.",
        "Select rib-gasket compound and retention process; test force/deflection, lateral bulging, movement, compression set and durability at temperature and coolant exposure.",
        "Run contact/nonlinear structural analysis or a load test including gasket reaction, fastener preload, cover/clamp/base compliance and thermal distortion. Confirm additional opening <=0.10 mm and local main-seal opening <=0.03 mm.",
        "Condition representative POM-C material and measure OD, locator displacement, port registration and gasket registration over 20-60 C.",
        "Select heater, define resistive pattern, thickness, lead exit, electrical isolation, mounting, coating, sensor locations, clamp contacts and thermal interface resistance.",
        "Select actual M5 hardware, washer and NPT fittings; verify full thread depth, drill-point clearance, engagement, passage intersections, torque/preload method and tool access.",
        "Pressure/leak test the assembled loop; determine maximum achievable loop pressure and explicitly establish the operating rating separately from the 30 kPa analysis case.",
        "Demonstrate thermal observability and camera access with the real heater, coating, sensors, hoses, brackets and optical setup.",
    ]
    story += [Spacer(1, 5 * mm), Paragraph("Physical Release Checks Still Required", styles["Heading1"])]
    for i, item in enumerate(release, 1):
        story.append(Paragraph(f"{i}. {item}", styles["Small"]))
        story.append(Spacer(1, 1.5 * mm))
    story += [Spacer(1, 4 * mm), Paragraph("Conclusion", styles["Heading1"]),
              Paragraph("The package is suitable as a regenerable preliminary engineering assembly and prototype basis. It is explicitly not machining-approved or pressure-rated. The unresolved seal, structural clamp and heater-interface items above are release blockers, not optional refinements.", styles["BodyText"])]

    def footer(canv, doc_):
        canv.saveState(); canv.setFont("Helvetica", 7); canv.setFillColor(colors.grey)
        canv.drawString(16 * mm, 8 * mm, "Rev A preliminary - not machining approved")
        canv.drawRightString(A4[0] - 16 * mm, 8 * mm, f"Page {doc_.page}")
        canv.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def main() -> None:
    drawings = OUT / "coldplate_revA_dimensioned_drawings.pdf"
    report = OUT / "coldplate_revA_validation_report.pdf"
    create_drawings(drawings)
    create_validation_report(report)
    manifest_path = ROOT / "build" / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        listed = {item["path"]: item for item in manifest.get("files", [])}
        for path in (drawings, report):
            rel = str(path.relative_to(ROOT))
            new_entry = {
                    "path": rel,
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            if rel in listed:
                listed[rel].update(new_entry)
            else:
                manifest["files"].append(new_entry)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Created PDFs in {OUT}")


if __name__ == "__main__":
    main()
