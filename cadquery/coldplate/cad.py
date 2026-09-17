"""CadQuery geometry for the Rev A preliminary cold-plate package."""

from __future__ import annotations

from math import cos, pi, radians, sin, sqrt

import cadquery as cq

from .config import P


def cylinder(radius: float, height: float, origin=(0, 0, 0), direction=(0, 0, 1)) -> cq.Shape:
    return cq.Solid.makeCylinder(radius, height, cq.Vector(*origin), cq.Vector(*direction))


def annular_solid(od: float, id_: float, height: float, z0: float) -> cq.Shape:
    return cylinder(od / 2, height, (0, 0, z0)).cut(cylinder(id_ / 2, height, (0, 0, z0)))


def box_centered(x: float, y: float, z: float, z0: float = 0.0) -> cq.Shape:
    return cq.Workplane("XY").box(x, y, z, centered=(True, True, False)).translate((0, 0, z0)).val()


def bolt_positions() -> list[tuple[float, float]]:
    return [
        (
            P.bolt_radius * cos(radians(P.bolt_offset_deg + i * 360 / P.bolt_count)),
            P.bolt_radius * sin(radians(P.bolt_offset_deg + i * 360 / P.bolt_count)),
        )
        for i in range(P.bolt_count)
    ]


def obround_xy(length: float, width: float, height: float, z0: float, along_y: bool = False) -> cq.Shape:
    straight = max(0.0, length - width)
    if along_y:
        core = box_centered(width, straight, height, z0)
        ends = [cylinder(width / 2, height, (0, s * straight / 2, z0)) for s in (-1, 1)]
    else:
        core = box_centered(straight, width, height, z0)
        ends = [cylinder(width / 2, height, (s * straight / 2, 0, z0)) for s in (-1, 1)]
    return core.fuse(*ends)


def diagonal_channel(p1: tuple[float, float], p2: tuple[float, float], width: float, height: float, z0: float) -> cq.Shape:
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = x2 - x1, y2 - y1
    length = sqrt(dx * dx + dy * dy)
    angle = 180 / pi * __import__("math").atan2(dy, dx)
    bar = box_centered(length, width, height, z0).rotate((0, 0, 0), (0, 0, 1), angle)
    bar = bar.translate(((x1 + x2) / 2, (y1 + y2) / 2, 0))
    return bar.fuse(
        cylinder(width / 2, height, (x1, y1, z0)),
        cylinder(width / 2, height, (x2, y2, z0)),
    )


def make_base() -> cq.Shape:
    body = box_centered(P.base_xy, P.base_xy, P.base_thickness, -P.base_thickness)
    cavity = cylinder(P.cavity_diameter / 2, P.cavity_depth, (0, 0, -P.cavity_depth))
    body = body.cut(cavity)

    main_groove = annular_solid(P.main_groove_od, P.main_groove_id, P.main_groove_depth, -P.main_groove_depth)
    body = body.cut(main_groove)

    for x, y in bolt_positions():
        body = body.cut(cylinder(P.tapped_hole_diameter_model / 2, P.tapped_hole_depth, (x, y, -P.tapped_hole_depth)))

    # Candidate thread envelopes and nominal drilled passages.
    body = body.cut(cylinder(P.npt_thread_envelope_diameter / 2, P.npt_thread_length_candidate, (-100, 0, P.side_port_axis_z), (1, 0, 0)))
    body = body.cut(cylinder(P.npt_thread_envelope_diameter / 2, P.npt_thread_length_candidate, (100, 0, P.side_port_axis_z), (-1, 0, 0)))
    body = body.cut(cylinder(P.drilled_passage_diameter / 2, 30, (-100, 0, P.side_port_axis_z), (1, 0, 0)))
    body = body.cut(cylinder(P.drilled_passage_diameter / 2, 30, (100, 0, P.side_port_axis_z), (-1, 0, 0)))
    for sx in (-P.transfer_x, P.transfer_x):
        body = body.cut(cylinder(P.drilled_passage_diameter / 2, 9.0, (sx, 0, P.side_port_axis_z)))
        groove = annular_solid(P.transfer_groove_od, P.transfer_groove_id, P.transfer_groove_depth, -P.cavity_depth - P.transfer_groove_depth)
        body = body.cut(groove.translate((sx, 0, 0)))
        # Flush static pressure-tap bore from the front side to the transfer center.
        body = body.cut(cylinder(P.tap_bore_diameter / 2, 100.0, (sx, -100, P.side_port_axis_z), (0, 1, 0)))
        body = body.cut(cylinder(P.tap_thread_model_diameter / 2, 8.0, (sx, -100, P.side_port_axis_z), (0, 1, 0)))

    # Dry underside bracket attachment holes, deliberately remote from the ports.
    for x in (-P.bracket_mount_x, P.bracket_mount_x):
        for y in (-P.bracket_mount_y, P.bracket_mount_y):
            body = body.cut(cylinder(P.bracket_base_hole_diameter / 2, 8.0, (x, y, -P.base_thickness)))

    # Kinematic pair: one round pin and one radial-direction slot mating feature.
    for y in (-70.0, 70.0):
        body = body.fuse(cylinder(P.locator_pin_diameter / 2, P.gasket_support_from_underside, (0, y, -P.cavity_depth)))
    return body


def make_cover() -> cq.Shape:
    cover = box_centered(P.cover_xy, P.cover_xy, P.cover_thickness, 0)
    for x, y in bolt_positions():
        cover = cover.cut(cylinder(P.clearance_hole_diameter / 2, P.cover_thickness, (x, y, 0)))
    return cover


def make_structural_clamp() -> cq.Shape:
    clamp = box_centered(P.structural_clamp_xy, P.structural_clamp_xy, P.structural_clamp_thickness, 0)
    clamp = clamp.cut(cylinder(P.structural_clamp_aperture / 2, P.structural_clamp_thickness, (0, 0, 0)))
    for x, y in bolt_positions():
        clamp = clamp.cut(cylinder(P.clearance_hole_diameter / 2, P.structural_clamp_thickness, (x, y, 0)))
    return clamp


def common_floor() -> cq.Shape:
    floor = cylinder(P.insert_od / 2, P.floor_thickness, (0, 0, P.insert_bottom_z))
    for x in (-P.transfer_x, P.transfer_x):
        floor = floor.cut(cylinder(P.insert_transfer_diameter / 2, P.floor_thickness, (x, 0, P.insert_bottom_z)))
    floor = floor.cut(cylinder((P.locator_pin_diameter + P.locator_clearance) / 2, P.floor_thickness, (0, 70, P.insert_bottom_z)))
    slot = obround_xy(P.radial_slot_length, P.locator_pin_diameter + P.locator_clearance, P.floor_thickness, P.insert_bottom_z, along_y=True)
    floor = floor.cut(slot.translate((0, -70, 0)))
    return floor


def perimeter_rib() -> cq.Shape:
    h = P.gasket_support_from_underside - P.floor_thickness
    return annular_solid(160.0, 152.0, h, P.insert_floor_top_z)


def perimeter_gasket() -> cq.Shape:
    return annular_solid(158.0, 154.0, P.rib_gasket_installed_height, P.rib_support_z)


def fi100_fluid(height: float | None = None, z0: float | None = None) -> cq.Shape:
    h = height if height is not None else P.channel_height
    base_z = z0 if z0 is not None else P.insert_floor_top_z
    w = P.fi100_channel_width
    result = None
    ys = [(i - 4) * P.fi100_pitch for i in range(P.fi100_pass_count)]
    for y in ys:
        bar = box_centered(P.fi100_straight_length, w, h, base_z).translate((0, y, 0))
        result = bar if result is None else result.fuse(bar)
    for i in range(P.fi100_pass_count - 1):
        yc = (ys[i] + ys[i + 1]) / 2
        xc = 48.0 if i % 2 == 0 else -48.0
        ring = annular_solid(20.0, 4.0, h, base_z).translate((xc, yc, 0))
        clip_x = xc + (6.0 if xc > 0 else -6.0)
        clip = box_centered(20.0, 24.0, h, base_z).translate((clip_x, yc, 0))
        result = result.fuse(ring.intersect(clip))
    result = result.fuse(diagonal_channel((-P.transfer_x, 0), (-48, -48), w, h, base_z))
    result = result.fuse(diagonal_channel((48, 48), (P.transfer_x, 0), w, h, base_z))
    for x in (-P.transfer_x, P.transfer_x):
        result = result.fuse(cylinder(P.insert_transfer_diameter / 2, h, (x, 0, base_z)))
    return result


def fi200_fluid(tapered: bool = False, height: float | None = None, z0: float | None = None) -> cq.Shape:
    h = height if height is not None else P.channel_height
    base_z = z0 if z0 is not None else P.insert_floor_top_z
    result = None
    for y in P.fi200_centers_y:
        channel = box_centered(P.fi200_straight_length, P.fi200_channel_width, h, base_z).translate((0, y, 0))
        result = channel if result is None else result.fuse(channel)
    if tapered:
        # Polygon headers: 12 mm depth at center tapering to 6 mm at both ends.
        left_pts = [(-48, -48), (-54, -48), (-60, 0), (-54, 48), (-48, 48)]
        right_pts = [(48, -48), (54, -48), (60, 0), (54, 48), (48, 48)]
        left = cq.Workplane("XY").polyline(left_pts).close().extrude(h).translate((0, 0, base_z)).val()
        right = cq.Workplane("XY").polyline(right_pts).close().extrude(h).translate((0, 0, base_z)).val()
    else:
        left = box_centered(P.fi200_header_width, 96.0, h, base_z).translate((-54, 0, 0))
        right = box_centered(P.fi200_header_width, 96.0, h, base_z).translate((54, 0, 0))
    result = result.fuse(left, right)
    result = result.fuse(diagonal_channel((-P.transfer_x, 0), (-60, 0), 8.0, h, base_z))
    result = result.fuse(diagonal_channel((60, 0), (P.transfer_x, 0), 8.0, h, base_z))
    for x in (-P.transfer_x, P.transfer_x):
        result = result.fuse(cylinder(P.insert_transfer_diameter / 2, h, (x, 0, base_z)))
    return result


def make_insert(variant: str) -> tuple[cq.Shape, cq.Shape, cq.Shape]:
    floor = common_floor()
    h = P.gasket_support_from_underside - P.floor_thickness
    interior = cylinder(80.0, h, (0, 0, P.insert_floor_top_z))
    if variant == "FI-000":
        body = floor.fuse(perimeter_rib())
        fluid = cylinder(76.0, P.channel_height, (0, 0, P.insert_floor_top_z))
        for x in (-P.transfer_x, P.transfer_x):
            fluid = fluid.fuse(cylinder(P.insert_transfer_diameter / 2, P.channel_height, (x, 0, P.insert_floor_top_z)))
        gasket = perimeter_gasket()
    elif variant == "FI-100":
        fluid = fi100_fluid()
        body = floor.fuse(interior.cut(fluid))
        gasket = perimeter_gasket()
        for i, y in enumerate((-42, -30, -18, -6, 6, 18, 30, 42)):
            x0, x1 = (-76, 48) if i % 2 == 0 else (-48, 76)
            strip = box_centered(x1 - x0, P.rib_gasket_width, P.rib_gasket_installed_height, P.rib_support_z).translate(((x0 + x1) / 2, y, 0))
            gasket = gasket.fuse(strip.intersect(cylinder(79, P.rib_gasket_installed_height, (0, 0, P.rib_support_z))))
    elif variant in ("FI-200", "FI-300"):
        fluid = fi200_fluid(tapered=variant == "FI-300")
        body = floor.fuse(interior.cut(fluid))
        gasket = perimeter_gasket()
        for y in (-36, -24, -12, 0, 12, 24, 36):
            strip = box_centered(96.0, P.rib_gasket_width, P.rib_gasket_installed_height, P.rib_support_z).translate((0, y, 0))
            gasket = gasket.fuse(strip)
    else:
        raise ValueError(f"Unknown insert variant {variant}")

    # Preserve transfer and locator openings through any upper polymer generated above.
    for x in (-P.transfer_x, P.transfer_x):
        body = body.cut(cylinder(P.insert_transfer_diameter / 2, P.gasket_support_from_underside, (x, 0, P.insert_bottom_z)))
    body = body.cut(cylinder((P.locator_pin_diameter + P.locator_clearance) / 2, P.gasket_support_from_underside, (0, 70, P.insert_bottom_z)))
    slot = obround_xy(P.radial_slot_length, P.locator_pin_diameter + P.locator_clearance, P.gasket_support_from_underside, P.insert_bottom_z, along_y=True)
    body = body.cut(slot.translate((0, -70, 0)))
    return body, gasket, fluid


def make_payload() -> cq.Shape:
    return cylinder(P.payload_diameter / 2, P.payload_thickness, (0, 0, 0))


def make_payload_clamp() -> cq.Shape:
    clamp = annular_solid(P.payload_clamp_od, P.payload_clamp_id, P.payload_clamp_thickness, 0)
    # Three adjustment slots; details remain provisional pending heater and lead selection.
    for angle in (0, 120, 240):
        slot = box_centered(8.0, 3.5, P.payload_clamp_thickness, 0).translate((77.0, 0, 0)).rotate((0, 0, 0), (0, 0, 1), angle)
        clamp = clamp.cut(slot)
    return clamp


def make_heater_envelope() -> cq.Shape:
    return cylinder(P.heater_envelope_diameter / 2, P.heater_placeholder_thickness, (0, 0, 0))


def make_bracket() -> cq.Shape:
    foot = box_centered(P.bracket_leg_length, P.bracket_width, P.bracket_plate_thickness, 0)
    upright_h = P.bracket_leg_length - P.bracket_plate_thickness
    upright = box_centered(P.bracket_plate_thickness, P.bracket_width, upright_h, P.bracket_plate_thickness).translate((-P.bracket_leg_length / 2 + P.bracket_plate_thickness / 2, 0, 0))
    top = box_centered(P.bracket_leg_length, P.bracket_width, P.bracket_plate_thickness, P.bracket_leg_length - P.bracket_plate_thickness)
    bracket = foot.fuse(upright, top)
    bracket = bracket.cut(cylinder(P.bracket_bench_hole_diameter / 2, P.bracket_plate_thickness, (8, 0, 0)))
    bracket = bracket.cut(cylinder(P.bracket_base_hole_diameter / 2, P.bracket_plate_thickness, (0, 0, P.bracket_leg_length - P.bracket_plate_thickness)))
    return bracket


def make_main_oring() -> cq.Shape:
    center_r = (P.main_or_id + P.main_or_cs) / 2
    return cq.Solid.makeTorus(center_r, P.main_or_cs / 2, cq.Vector(0, 0, -P.main_or_cs / 2), cq.Vector(0, 0, 1), 0, 360)


def make_transfer_orings() -> cq.Shape:
    center_r = (P.transfer_or_id + P.transfer_or_cs) / 2
    rings = []
    for x in (-P.transfer_x, P.transfer_x):
        ring = cq.Solid.makeTorus(center_r, P.transfer_or_cs / 2, cq.Vector(x, 0, -P.cavity_depth - P.transfer_or_cs / 2), cq.Vector(0, 0, 1), 0, 360)
        rings.append(ring)
    return cq.Compound.makeCompound(rings)


def make_screw() -> cq.Shape:
    shaft = cylinder(2.5, P.screw_nominal_length, (0, 0, -P.screw_nominal_length))
    head = cylinder(P.screw_head_diameter / 2, P.screw_head_height, (0, 0, 0))
    return shaft.fuse(head)


def make_washer() -> cq.Shape:
    return annular_solid(P.washer_od, P.washer_id, P.washer_thickness, 0)


def make_fastener_set_assembly_z() -> tuple[cq.Shape, cq.Shape]:
    screws, washers = [], []
    screw = make_screw()
    washer = make_washer()
    for x, y in bolt_positions():
        screws.append(screw.translate((x, y, 13.5)))
        washers.append(washer.translate((x, y, 12.5)))
    return cq.Compound.makeCompound(screws), cq.Compound.makeCompound(washers)


def make_npt_envelope() -> cq.Shape:
    # Conservative cylindrical candidate envelope; final fitting-specific CAD is a release item.
    body = cylinder(P.npt_thread_envelope_diameter / 2, P.npt_thread_length_candidate, (0, 0, 0), (-1, 0, 0))
    hex_body = cq.Workplane("YZ").polygon(6, 19.0).extrude(12.0).val()
    hose = cylinder(6.0, 20.0, (12.0, 0, 0), (1, 0, 0))
    return body.fuse(hex_body, hose)


def make_assembly(selected_variant: str = "FI-100", exploded: bool = False) -> cq.Assembly:
    assy = cq.Assembly(name=f"COLD_PLATE_{P.revision.replace(' ', '_')}")
    dz = 16.0 if exploded else 0.0
    insert, gasket, _ = make_insert(selected_variant)
    assy.add(make_base(), name="CP-001_BASE", color=cq.Color(0.65, 0.68, 0.72))
    assy.add(insert.translate((0, 0, dz)), name=selected_variant, color=cq.Color(0.92, 0.90, 0.75))
    assy.add(gasket.translate((0, 0, dz)), name=f"{selected_variant}_RIB_GASKET", color=cq.Color(0.15, 0.15, 0.15))
    assy.add(make_main_oring().translate((0, 0, dz)), name="GS-001_MAIN_ORING", color=cq.Color(0.12, 0.12, 0.12))
    assy.add(make_transfer_orings().translate((0, 0, dz)), name="GS-013_TRANSFER_ORINGS_2X", color=cq.Color(0.10, 0.10, 0.10))
    assy.add(make_cover().translate((0, 0, 2 * dz)), name="CP-002_COVER", color=cq.Color(0.55, 0.72, 0.88, 0.55))
    assy.add(make_structural_clamp().translate((0, 0, P.cover_thickness + 3 * dz)), name="CL-002_STRUCTURAL_CLAMP", color=cq.Color(0.30, 0.33, 0.36))
    heater_z = P.cover_thickness + 4 * dz
    assy.add(make_heater_envelope().translate((0, 0, heater_z)), name="HEATER_PROVISIONAL_ENVELOPE", color=cq.Color(0.88, 0.55, 0.20))
    payload_z = heater_z + P.heater_placeholder_thickness + (dz if exploded else 0)
    assy.add(make_payload().translate((0, 0, payload_z)), name="TH-001_PAYLOAD", color=cq.Color(0.75, 0.78, 0.82))
    clamp_z = payload_z + (dz if exploded else 0)
    assy.add(make_payload_clamp().translate((0, 0, clamp_z)), name="CL-001_PAYLOAD_CLAMP", color=cq.Color(0.35, 0.38, 0.42))
    if not exploded:
        screws, washers = make_fastener_set_assembly_z()
        assy.add(screws, name="M5X25_SCREWS_16X", color=cq.Color(0.20, 0.20, 0.22))
        assy.add(washers, name="M5_WASHERS_16X", color=cq.Color(0.25, 0.25, 0.28))
        fitting = make_npt_envelope()
        assy.add(fitting.translate((100, 0, P.side_port_axis_z)), name="NPT_RIGHT_ENVELOPE", color=cq.Color(0.38, 0.38, 0.40))
        assy.add(fitting.rotate((0, 0, 0), (0, 0, 1), 180).translate((-100, 0, P.side_port_axis_z)), name="NPT_LEFT_ENVELOPE", color=cq.Color(0.38, 0.38, 0.40))
        bracket = make_bracket()
        for ix, x in enumerate((-P.bracket_mount_x, P.bracket_mount_x)):
            for iy, y in enumerate((-P.bracket_mount_y, P.bracket_mount_y)):
                assy.add(bracket.translate((x, y, -70)), name=f"BR-001_{ix}_{iy}", color=cq.Color(0.45, 0.48, 0.50))
    return assy


def part_library() -> dict[str, cq.Shape]:
    parts = {
        "CP-001_base": make_base(),
        "CP-002_cover": make_cover(),
        "CL-002_structural_clamp": make_structural_clamp(),
        "TH-001_payload": make_payload(),
        "CL-001_payload_clamp": make_payload_clamp(),
        "BR-001_bench_bracket": make_bracket(),
        "GS-001_AS568-166_envelope": make_main_oring(),
        "GS-013_transfer_orings_2x": make_transfer_orings(),
        "HW-M5x25_screw_envelope": make_screw(),
        "HW-M5_washer_envelope": make_washer(),
        "HW-NPT-1_4_candidate_envelope": make_npt_envelope(),
        "HT-001_heater_provisional_envelope": make_heater_envelope(),
    }
    for variant in ("FI-000", "FI-100", "FI-200", "FI-300"):
        body, gasket, fluid = make_insert(variant)
        parts[f"{variant}_insert"] = body
        parts[f"{variant}_rib_gasket"] = gasket
        parts[f"{variant}_fluid_domain"] = fluid
    return parts
