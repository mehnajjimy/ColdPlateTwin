"""ColdPlateTwin experiment illustration — Blender 5.x scene builder.

Run from this package root, for example:
  blender --background --python build_scene.py -- --preview
  blender --background --python build_scene.py -- --final
The CAD OBJ is imported at its authored metre scale (1.0); all other geometry is schematic.
"""
from pathlib import Path
from math import radians
import sys
import bpy
from mathutils import Vector, Matrix

# ---------------- Editable layout / look controls ----------------
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "render_output"
OBJ_PATH = ROOT / "blender_mesh" / "coldplate_assembly_meters.obj"
MODE = "preview" if "--preview" in sys.argv else "final"
RES = (960, 540) if MODE == "preview" else (1920, 1080)
SAMPLES = 16 if MODE == "preview" else 48

# Component centers, label endpoints, and hose routes are intentionally centralized.
POS = {
    "reservoir": (-1.25, -0.72, 0.15), "pump": (-0.88, -0.67, 0.03),
    "valve": (-0.59, -0.48, 0.06), "flow": (-0.32, -0.42, 0.08),
    "tin": (-0.12, -0.30, 0.09), "tout": (0.38, -0.28, 0.09),
    "rejector": (0.83, -0.48, 0.14), "dp": (0.76, 0.43, 0.08),
    "logger": (1.28, 0.50, 0.02), "supply": (1.28, 0.13, 0.02),
    "camera": (0.00, 0.00, 0.52),
}
LABELS = {
    "IR camera": ((0.00, 0.00, 0.52), (-0.55, 0.46, 0.58)),
    "coldplate test article": ((0.00, 0.00, 0.02), (-0.54, 0.48, 0.22)),
    "Tin PT100": (POS["tin"], (-0.54, -0.08, 0.31)),
    "Tout PT100": (POS["tout"], (0.32, 0.10, 0.32)),
    "flow meter": (POS["flow"], (-0.90, -0.22, 0.28)),
    "pump": (POS["pump"], (-1.30, -0.08, 0.26)),
    "reservoir": (POS["reservoir"], (-1.67, -0.62, 0.54)),
    "heat rejector": (POS["rejector"], (0.78, -0.04, 0.40)),
    "Δp sensor": (POS["dp"], (0.72, 0.56, 0.30)),
    "logger": (POS["logger"], (1.12, 0.61, 0.27)),
    "heater supply": (POS["supply"], (1.25, 0.17, 0.25)),
}

def mat(name, color, metallic=0.0, rough=0.5, emission=None):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = rough
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1)
        bsdf.inputs["Emission Strength"].default_value = 0.5
    return m

def clear_hose_mat():
    """EEVEE-friendly clear polymer: deliberately not expensive ray-traced glass."""
    m = mat("Clear tubing polymer", (0.56, 0.82, 0.92), 0.0, 0.16)
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Alpha"].default_value = 0.18
    transmission = bsdf.inputs.get("Transmission Weight") or bsdf.inputs.get("Transmission")
    if transmission: transmission.default_value = 0.20
    try: m.surface_render_method = 'BLENDED'
    except (AttributeError, TypeError): pass
    return m

METAL = mat("Brushed gray metal", (0.28, 0.31, 0.34), 0.75, 0.32)
DARK = mat("Matte dark polymer", (0.055, 0.065, 0.08), 0.08, 0.6)
BLUE = mat("Water route blue", (0.025, 0.28, 0.72), 0.25, 0.27)
WATER_CORE = mat("Visible blue water in clear tube", (0.015, 0.22, 0.95), 0.05, 0.20, (0.01, 0.10, 0.42))
CLEAR_HOSE = clear_hose_mat()
AMBER = mat("Heater power amber", (0.95, 0.35, 0.03), 0.1, 0.32, (0.9, 0.18, 0.01))
DATA = mat("Data line teal", (0.03, 0.58, 0.54), 0.1, 0.3)
WHITE = mat("Label warm white", (0.93, 0.93, 0.89), 0, 0.55)
INK = mat("Print-safe annotation ink", (0.025, 0.032, 0.040), 0, 0.60)
LEADER = mat("Print-safe annotation leaders", (0.10, 0.12, 0.15), 0, 0.52)
TEXT_BLACK = mat("Pure black print text", (0.0, 0.0, 0.0), 0.0, 1.0)
TRAY = mat("Leak tray", (0.06, 0.12, 0.18), 0.35, 0.4)
RED = mat("Safety red", (0.72, 0.06, 0.035), 0.1, 0.36)
PAYLOAD = mat("Payload matte charcoal", (0.055, 0.06, 0.07), 0.1, 0.72)
WINDOW = mat("Central viewing region", (0.08, 0.19, 0.22), 0.25, 0.16)
PAPER = mat("White print annotation card", (1.0, 1.0, 1.0), 0.0, 0.82, (1.0, 1.0, 1.0))
PAPER.node_tree.nodes.get("Principled BSDF").inputs["Emission Strength"].default_value = 5.0
PAPER.node_tree.nodes.get("Principled BSDF").inputs["Alpha"].default_value = 1.0
PAPER.diffuse_color = (1.0, 1.0, 1.0, 1.0)
PAPER.surface_render_method = 'DITHERED'

def collection(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c

def move_to(obj, coll):
    for c in list(obj.users_collection): c.objects.unlink(obj)
    coll.objects.link(obj)
    return obj

def cube(name, loc, scale, material, coll):
    bpy.ops.mesh.primitive_cube_add(location=loc)
    o = bpy.context.object; o.name = name; o.scale = [v / 2 for v in scale]
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    o.data.materials.append(material); move_to(o, coll)
    bevel = o.modifiers.new("small edge rounds", "BEVEL"); bevel.width = min(scale) * 0.06; bevel.segments = 2
    return o

def cylinder(name, loc, radius, depth, material, coll, rot=None):
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=radius, depth=depth, location=loc)
    o = bpy.context.object; o.name = name
    if rot: o.rotation_euler = rot
    o.data.materials.append(material); move_to(o, coll)
    bevel = o.modifiers.new("small edge rounds", "BEVEL"); bevel.width = min(radius * .12, .008); bevel.segments = 2
    return o

def cone(name, loc, radius1, radius2, depth, material, coll, direction=None):
    bpy.ops.mesh.primitive_cone_add(vertices=20, radius1=radius1, radius2=radius2, depth=depth, location=loc)
    o = bpy.context.object; o.name = name; o.data.materials.append(material); move_to(o, coll)
    if direction: o.rotation_mode = 'QUATERNION'; o.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(Vector(direction).normalized())
    return o

def hose_collar(name, point, direction, coll):
    """A small circular coupling sleeve oriented around the local hose axis."""
    o = cylinder(name, point, .031, .040, METAL, coll)
    o.rotation_mode = 'QUATERNION'
    o.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(Vector(direction).normalized())
    return o

def curve(name, points, material, radius, coll, dashed=False):
    cu = bpy.data.curves.new(name, "CURVE"); cu.dimensions = "3D"; cu.resolution_u = 2; cu.bevel_depth = radius; cu.bevel_resolution = 2
    sp = cu.splines.new("NURBS"); sp.points.add(len(points) - 1)
    for p, co in zip(sp.points, points): p.co = (*co, 1)
    sp.order_u = min(3, len(points)); sp.use_endpoint_u = True
    o = bpy.data.objects.new(name, cu); coll.objects.link(o); o.data.materials.append(material)
    return o

def aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat('-Z', 'Y').to_euler()

def leader_label(text, anchor, position, coll, target_cam, size=.040):
    curve("Leader | " + text, [anchor, position], LEADER, 0.0032, coll)
    bpy.ops.object.text_add(location=position)
    o = bpy.context.object; o.name = "Label | " + text; o.data.body = text; o.data.align_x = 'CENTER'; o.data.size = size; o.data.extrude = .001
    o.data.materials.append(TEXT_BLACK); move_to(o, coll)
    con = o.constraints.new('COPY_ROTATION'); con.target = target_cam
    return o

def info_label(text, position, coll, target_cam, size=.040):
    """Standalone high-contrast copy for the print caption and line-style key."""
    bpy.ops.object.text_add(location=position)
    o = bpy.context.object; o.name = "Print note | " + text.split('\n')[0]
    o.data.body = text; o.data.align_x = 'CENTER'; o.data.size = size; o.data.extrude = .001
    o.data.materials.append(LEADER); move_to(o, coll)
    con = o.constraints.new('COPY_ROTATION'); con.target = target_cam
    return o

def camera_overlay_card(name, cam, center, size, coll, material=PAPER, depth=-1.02):
    """A camera-parented white card: fixed inside the print-safe image area."""
    o = cube(name, (0, 0, 0), (size[0], size[1], .004), material, coll)
    o.parent = cam; o.matrix_parent_inverse = Matrix.Identity(4)
    o.location = (*center, depth); o.rotation_euler = (0, 0, 0)
    return o

def camera_overlay_tag(name, cam, center, size, coll):
    """White label field with a narrow charcoal frame for reliable paper contrast."""
    camera_overlay_card(name + ' border', cam, center, (size[0] + .003, size[1] + .003), coll, LEADER, -1.024)
    return camera_overlay_card(name, cam, center, size, coll, PAPER, -1.020)

def camera_overlay_text(name, text, cam, pos, size, coll):
    """Screen-stable, high-contrast text; local camera coordinates prevent cropping."""
    bpy.ops.object.text_add()
    o = bpy.context.object; o.name = name; o.data.body = text
    o.data.align_x = 'LEFT'; o.data.align_y = 'TOP'; o.data.size = size; o.data.extrude = .0005
    o.data.materials.append(LEADER); move_to(o, coll)
    o.parent = cam; o.matrix_parent_inverse = Matrix.Identity(4)
    o.location = (*pos, -1.00); o.rotation_euler = (0, 0, 0)
    return o

def camera_overlay_auto_tag(name, text, cam, center, size, coll):
    """Create a print tag whose border follows the measured text, not a fixed template width."""
    label = camera_overlay_text(name, text, cam, center, size, coll)
    label.data.align_x = 'CENTER'; label.data.align_y = 'CENTER'
    bpy.context.view_layer.update()
    width = label.dimensions.x + .020
    height = max(label.dimensions.y + .012, .020)
    label.location = (center[0], center[1], -1.00)
    camera_overlay_tag(name + ' tag', cam, center, (width, height), coll)
    return label

def project_to_camera_plane(cam, point):
    """Project a scene point to the camera-local z=-1 annotation plane."""
    local = cam.matrix_world.inverted() @ Vector(point)
    if local.z >= -.001: raise RuntimeError('Callout anchor is behind its camera')
    return Vector((local.x / -local.z, local.y / -local.z, -1.0))

def overlay_arrow_label(text, anchor, cam, center, coll, width=.175, height=.023):
    """White print tag plus a screen-space arrow that terminates at the named scene object."""
    label = camera_overlay_text('Arrow label | ' + text, text, cam, center, .0105, coll)
    label.data.align_x = 'CENTER'; label.data.align_y = 'CENTER'
    bpy.context.view_layer.update()
    width = max(label.dimensions.x + .016, .070)
    height = max(label.dimensions.y + .010, .018)
    label.location = (center[0], center[1], -1.00)
    camera_overlay_tag('Arrow tag | ' + text, cam, center, (width, height), coll)
    end = project_to_camera_plane(cam, anchor)
    half_w, half_h = width / 2, height / 2
    delta = Vector((end.x - center[0], end.y - center[1]))
    if abs(delta.x / half_w) > abs(delta.y / half_h):
        start = Vector((center[0] + (half_w if delta.x >= 0 else -half_w), center[1] + delta.y * half_w / max(abs(delta.x), .0001), -1.0))
    else:
        start = Vector((center[0] + delta.x * half_h / max(abs(delta.y), .0001), center[1] + (half_h if delta.y >= 0 else -half_h), -1.0))
    world_start = cam.matrix_world @ start
    world_end = cam.matrix_world @ end
    curve('Arrow leader | ' + text, [world_start, world_end], LEADER, .0017, coll)
    direction = (world_end - world_start).normalized()
    cone('Arrowhead | ' + text, world_end - direction * .005, .005, 0, .010, LEADER, coll, direction)

def camera(name, loc, target, lens):
    bpy.ops.object.camera_add(location=loc)
    c = bpy.context.object; c.name = name; c.data.lens = lens; aim(c, target); return c

def light(name, loc, energy, size, target):
    bpy.ops.object.light_add(type='AREA', location=loc)
    l = bpy.context.object; l.name = name; l.data.energy = energy; l.data.shape = 'DISK'; l.data.size = size; aim(l, target); return l

def configure_render(scene):
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x, scene.render.resolution_y = RES
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.film_transparent = False
    scene.render.image_settings.color_depth = '8'
    scene.render.resolution_percentage = 100
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.image_settings.compression = 15
    scene.world.color = (0.96, 0.97, 0.98)
    scene.render.filepath = str(OUT / "unused.png")
    scene.view_settings.look = 'AgX - Medium High Contrast'

def build():
    bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.materials, bpy.data.curves, bpy.data.meshes, bpy.data.cameras, bpy.data.lights):
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene; configure_render(scene)
    scene.unit_settings.system = 'METRIC'; scene.unit_settings.length_unit = 'METERS'
    cad = collection('01 ACTUAL REV A CAD — imported at 1.0 m scale')
    equip = collection('02 SCHEMATIC EQUIPMENT')
    tubes = collection('03 WATER AND SENSING TUBING')
    annot = collection('04 LABELS AND LEGEND')
    close_annot = collection('04b CLOSEUP CALLOUTS')
    print_overlay = collection('04c PRINT-SAFE OVERVIEW KEY')
    close_print = collection('04d PRINT-SAFE CLOSEUP KEY')
    arrow_overlay = collection('04e PRINT-SAFE ARROW CALLOUTS')
    env = collection('05 TABLETOP AND LIGHTING')

    # Actual CAD: preserve its object names, local origins, and assembly coordinates.
    before = set(bpy.data.objects)
    bpy.ops.wm.obj_import(filepath=str(OBJ_PATH), global_scale=1.0)
    imported = [o for o in bpy.data.objects if o not in before]
    base = bpy.data.objects.get('CP-001_BASE_000')
    if not base: raise RuntimeError('CP-001_BASE_000 missing after OBJ import')
    width = base.dimensions.x
    if abs(width - 0.200) > 0.002: raise RuntimeError(f'CAD scale check failed: CP-001 base width={width:.6f} m')
    for o in imported:
        move_to(o, cad)
        if o.name.startswith('TH-001'): o.data.materials.append(PAYLOAD)
        elif 'HEATER' in o.name: o.data.materials.append(AMBER)
        elif 'GASKET' in o.name or 'ORING' in o.name: o.data.materials.append(DARK)
        elif 'NPT' in o.name: o.data.materials.append(METAL)
        else: o.data.materials.append(METAL)
    # Clear central viewing region on the upper payload; the Rev A mesh remains untouched.
    cube('Clear central viewing region (schematic)', (0, 0, .0112), (.092, .092, .002), WINDOW, cad)

    # Table + wet tray: all liquid-side equipment is inside the tray; electronics sit to the right.
    cube('Tabletop', (0, 0, -.19), (3.9, 2.8, .10), DARK, env)
    tray = cube('Shallow leak tray — wet zone', (-.22, -.22, -.125), (2.75, 1.75, .055), TRAY, env)
    for x, y, sx, sy in [(-.22,-1.07,2.75,.035),(-.22,.63,2.75,.035),(-1.58,-.22,.035,1.75),(1.14,-.22,.035,1.75)]:
        cube('Leak tray raised rim', (x,y,-.08), (sx,sy,.07), TRAY, env)
    cube('Dry electronics mat', (1.27,.30,-.13), (.95,.82,.025), DARK, env)

    # Equipment primitives, named strictly by function.
    r = POS['reservoir']; cylinder('Reservoir', r, .18, .42, DARK, equip)
    cylinder('Reservoir liquid level band', (r[0],r[1],r[2]-.03), .184, .12, BLUE, equip)
    cylinder('Reservoir fill cap', (r[0],r[1],r[2]+.23), .055, .035, METAL, equip)
    cube('Pump', POS['pump'], (.30,.22,.20), DARK, equip)
    cylinder('Pump motor', (-.88,-.67,.18), .09, .25, METAL, equip, (0,radians(90),0))
    cylinder('Control valve body', POS['valve'], .075, .22, METAL, equip, (radians(90),0,0))
    cone('Control valve handle', (-.59,-.48,.20), .075, 0, .16, RED, equip)
    cylinder('Flow meter body', POS['flow'], .075, .25, METAL, equip, (radians(90),0,0))
    cube('Flow meter display', (-.32,-.53,.11), (.12,.012,.07), DARK, equip)
    for tag, p in [('Tin PT100 mixing section', POS['tin']), ('Tout PT100 mixing section', POS['tout'])]:
        cylinder(tag, p, .055, .24, METAL, equip, (radians(90),0,0)); cone(tag+' probe', (p[0],p[1],p[2]+.10), .017, .017, .13, WHITE, equip)
    cube('Heat rejector', POS['rejector'], (.38,.16,.30), METAL, equip)
    for z in (-.09,-.03,.03,.09): cube('Heat rejector fin', (.83,-.57,.14+z), (.31,.018,.022), DARK, equip)
    cube('Differential-pressure sensor', POS['dp'], (.26,.16,.16), DARK, equip)
    cylinder('Δp sensor port A', (.67,.37,.08), .026,.06, METAL,equip,(radians(90),0,0)); cylinder('Δp sensor port B', (.85,.37,.08), .026,.06, METAL,equip,(radians(90),0,0))
    cube('Logger', POS['logger'], (.34,.22,.18), DARK, equip); cube('Logger display', (1.28,.385,.04), (.19,.012,.075), DATA, equip)
    cube('24 VDC heater supply', POS['supply'], (.38,.24,.20), DARK, equip); cube('Heater supply display', (1.28,.005,.05), (.18,.012,.07), AMBER, equip)

    # Rigid overhead IR camera stand and instrument. Its lens center is roughly 0.50 m above payload.
    for x in (-.34,.34): cylinder('Rigid camera stand upright', (x,.24,.19), .025,.65,METAL,equip)
    cube('Rigid camera stand crossbar', (0,.24,.48), (.82,.045,.045), METAL, equip)
    cube('IR camera', POS['camera'], (.18,.14,.10), DARK, equip)
    cylinder('IR camera lens', (0,-.08,.52), .045,.05, METAL,equip,(radians(90),0,0))
    # Thin outlined field of view, not a laser cone.
    fov=[(-.105,-.105,.014),(.105,-.105,.014),(.105,.105,.014),(-.105,.105,.014),(-.105,-.105,.014)]
    curve('IR camera field-of-view footprint', fov, LEADER, .0022, annot)

    # Exact single main circuit in prompt order. Left and right named NPT envelopes establish inlet/outlet endpoints.
    inlet=(-.132,0,-.014); outlet=(.132,0,-.014)
    routes = [
        ('01 Reservoir → pump', [(-1.25,-.72,.36),(-1.10,-.72,.30),(-1.02,-.67,.13)]),
        ('02 Pump → control valve', [(-.74,-.67,.10),(-.70,-.58,.13),(-.67,-.50,.10)]),
        ('03 Control valve → flow meter', [(-.52,-.47,.09),(-.45,-.44,.10),(-.40,-.42,.08)]),
        ('04 Flow meter → inlet mixing / Tin PT100', [(-.24,-.42,.08),(-.19,-.36,.10),(-.15,-.31,.09)]),
        ('05 Tin PT100 → coldplate inlet (NPT_LEFT_ENVELOPE)', [(-.08,-.30,.09),(-.19,-.18,.10),(-.19,-.03,.05),inlet]),
        ('06 Coldplate outlet (NPT_RIGHT_ENVELOPE) → Tout PT100', [outlet,(.20,-.03,.05),(.25,-.18,.10),(.32,-.28,.09)]),
        ('07 Tout PT100 → heat rejector', [(.44,-.28,.09),(.57,-.36,.14),(.65,-.45,.16)]),
        ('08 Heat rejector → reservoir', [(1.01,-.48,.15),(1.12,-.78,.24),(.82,-1.05,.30),(-.85,-1.05,.35),(-1.18,-.86,.36)]),
    ]
    for name, pts in routes:
        # Two concentric circular curves: transparent polymer wall plus visible water core.
        curve(name + ' | clear circular hose', pts, CLEAR_HOSE, .026, tubes)
        curve(name + ' | water core', pts, WATER_CORE, .015, tubes)
        hose_collar(name + ' | upstream coupling', pts[0], Vector(pts[1])-Vector(pts[0]), tubes)
        hose_collar(name + ' | downstream coupling', pts[-1], Vector(pts[-1])-Vector(pts[-2]), tubes)
    for name, pts in routes[1::2]:
        a,b=Vector(pts[-2]),Vector(pts[-1]); d=b-a; cone('Water route arrow | '+name, a+d*.55, .035,0,.075,BLUE,tubes,d)
    # Separate thin sensing lines from front static taps to Δp sensor; they are not main-flow branches.
    curve('Δp sensing tube A — front static tap', [(-.07,-.102,.010),(-.07,.16,.10),(.67,.34,.10)], DATA,.006,tubes)
    curve('Δp sensing tube B — front static tap', [( .07,-.102,.010),( .07,.20,.12),(.85,.34,.10)], DATA,.006,tubes)
    # Electrical/data lines only, deliberately routed clear of wet equipment.
    curve('24 VDC proposed heater supply line', [(1.12,.13,.04),(.82,.12,.05),(.40,.14,.035),(.05,.12,.012)], AMBER,.008,annot)
    curve('Data line | IR camera to logger', [(0,.05,.53),(.48,.38,.52),(1.12,.48,.12)], DATA,.005,annot)
    curve('Data line | instruments to logger', [(-.15,-.22,.16),(.35,.22,.16),(1.12,.48,.09)], DATA,.004,annot)

    # Render cameras and annotation. Labels face overview camera for final-image legibility.
    overview = camera('CAM_OVERVIEW — isometric', (2.68,-3.05,2.15), (0,-.15,.08), 48)
    closeup = camera('CAM_CLOSEUP — CAD and measurement relationship', (.88,-1.52,.68), (0,0,.055), 58)
    # Direct, arrowed functional callouts for paper. These are camera-plane labels, so none can crop.
    camera_overlay_auto_tag('Arrow callout title', 'COLDPLATE TWIN — PROPOSED EXPERIMENTAL ARRANGEMENT', overview, (0, .196), .018, arrow_overlay)
    arrow_callouts = [
        ('Reservoir', POS['reservoir'], (-.275, .130)),
        ('Pump', POS['pump'], (-.275, .086)),
        ('Control valve', POS['valve'], (-.275, .042)),
        ('Flow meter', POS['flow'], (-.275, -.002)),
        ('Tin PT100', POS['tin'], (-.275, -.046)),
        ('Coldplate test article', (0, 0, .015), (-.275, -.090)),
        ('IR camera', POS['camera'], (.275, .130)),
        ('Tout PT100', POS['tout'], (.275, .086)),
        ('Heat rejector', POS['rejector'], (.275, .042)),
        ('Δp sensor', POS['dp'], (.275, -.002)),
        ('Logger', POS['logger'], (.275, -.046)),
        ('Heater supply • 24 VDC', POS['supply'], (.275, -.090)),
    ]
    for text, anchor, center in arrow_callouts:
        overlay_arrow_label(text, anchor, overview, center, arrow_overlay)
    camera_overlay_auto_tag('Arrow callout key', 'blue = water route   amber = heater power   teal = data / Δp sense', overview, (0, -.185), .0100, arrow_overlay)
    # Put the detailed key in the camera plane rather than around the model: no label can be cropped.
    camera_overlay_tag('Print title tag', overview, (0, .196), (.790, .030), print_overlay)
    camera_overlay_tag('Print subtitle tag', overview, (0, .173), (.790, .018), print_overlay)
    camera_overlay_tag('Print loop tag 1', overview, (0, -.098), (.790, .022), print_overlay)
    camera_overlay_tag('Print loop tag 2', overview, (0, -.121), (.790, .022), print_overlay)
    camera_overlay_tag('Print loop tag 3', overview, (0, -.144), (.790, .022), print_overlay)
    camera_overlay_tag('Print instruments tag', overview, (0, -.166), (.790, .019), print_overlay)
    camera_overlay_tag('Print heater tag', overview, (0, -.187), (.790, .019), print_overlay)
    camera_overlay_tag('Print key tag', overview, (0, -.208), (.790, .019), print_overlay)
    camera_overlay_text('Print title', 'COLDPLATE TWIN — PROPOSED EXPERIMENTAL ARRANGEMENT', overview, (-.375, .205), .018, print_overlay)
    camera_overlay_text('Print subtitle', 'Rev A CAD coldplate • ancillary equipment is schematic and not to scale', overview, (-.375, .181), .011, print_overlay)
    camera_overlay_text('Print loop 1', 'WET LOOP   Reservoir  →  Pump  →  Control valve  →  Flow meter', overview, (-.375, -.088), .014, print_overlay)
    camera_overlay_text('Print loop 2', '               Tin PT100  →  Coldplate test article  →  Tout PT100', overview, (-.375, -.111), .014, print_overlay)
    camera_overlay_text('Print loop 3', '               Heat rejector  →  Reservoir', overview, (-.375, -.134), .014, print_overlay)
    camera_overlay_text('Print instruments', 'INSTRUMENTS   IR camera (~0.50 m above payload)  •  Δp sensor (front static taps)  •  Logger', overview, (-.375, -.157), .0115, print_overlay)
    camera_overlay_text('Print power', 'HEATER   Proposed 24 VDC supply • fused supply • independent heater cutoff', overview, (-.375, -.178), .0115, print_overlay)
    camera_overlay_text('Print key', 'KEY   blue = water route     amber = heater power     teal = data / Δp sense', overview, (-.375, -.199), .0115, print_overlay)
    camera_overlay_tag('Closeup title tag', closeup, (0, .135), (.620, .030), close_print)
    camera_overlay_text('Closeup title', 'COLDPLATE CLOSE-UP — REV A CAD', closeup, (-.290, .144), .015, close_print)
    camera_overlay_tag('Closeup detail tag', closeup, (0, -.095), (.620, .045), close_print)
    camera_overlay_text('Closeup detail 1', 'CAD: left inlet & right outlet fittings • Tin/Tout PT100', closeup, (-.290, -.075), .010, close_print)
    camera_overlay_text('Closeup detail 2', 'Measurement: IR camera ~0.50 m above payload', closeup, (-.290, -.097), .010, close_print)
    # Close-up gets a deliberately sparse, dedicated set of callouts.
    leader_label('actual Rev A CAD', (0,0,.014), (-.22,.16,.19), close_annot, closeup, .024)
    leader_label('inlet • left fitting', inlet, (-.28,-.16,.11), close_annot, closeup, .020)
    leader_label('outlet • right fitting', outlet, (.30,-.08,.13), close_annot, closeup, .020)
    leader_label('IR camera • ~0.50 m above payload', (0,0,.52), (-.24,.30,.45), close_annot, closeup, .020)

    # restrained studio light
    light('Key softbox', (-2,-3,4), 900, 3.0, (0,0,0)); light('Fill softbox', (3,1.5,2.5), 650, 2.5, (0,0,.05)); light('Rim softbox', (-1,2,3), 700, 2.0, (0,0,.1))
    bpy.ops.mesh.primitive_plane_add(size=20, location=(0,0,-.245)); floor=bpy.context.object; floor.name='White print background floor'; floor.data.materials.append(mat('Background',(.97,.98,.99),0,.75)); move_to(floor,env)

    # Save first so both named, editable views are present, then render selected view(s).
    blend = OUT / 'ColdPlateTwin_experiment.blend'
    scene.camera = overview; bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    if MODE == 'preview':
        for o in close_annot.objects: o.hide_render = True
        for o in close_print.objects: o.hide_render = True
        for o in print_overlay.objects: o.hide_render = True
        # Overview labels are applied after render by annotate_overview.ps1 for sharp print typography.
        for o in arrow_overlay.objects: o.hide_render = True
        for o in annot.objects:
            if o.name.startswith('Label |') or o.name.startswith('Leader |') or o.name.startswith('Print note |'): o.hide_render = True
        scene.render.filepath = str(OUT / 'preview_overview.png'); bpy.ops.render.render(write_still=True)
        for o in arrow_overlay.objects: o.hide_render = True
        for o in annot.objects:
            if o.name != 'IR camera field-of-view footprint' and not o.name.startswith('24 VDC') and not o.name.startswith('Data line'): o.hide_render = True
        for o in equip.objects: o.hide_render = not ('IR camera' in o.name or 'Rigid camera stand' in o.name or 'Tin PT100' in o.name or 'Tout PT100' in o.name)
        for o in close_annot.objects: o.hide_render = True
        for o in close_print.objects: o.hide_render = False
        scene.camera = closeup; scene.render.filepath = str(OUT / 'preview_closeup.png'); bpy.ops.render.render(write_still=True)
    else:
        for o in close_annot.objects: o.hide_render = True
        for o in close_print.objects: o.hide_render = True
        for o in print_overlay.objects: o.hide_render = True
        # Overview labels are applied after render by annotate_overview.ps1 for sharp print typography.
        for o in arrow_overlay.objects: o.hide_render = True
        for o in annot.objects:
            if o.name.startswith('Label |') or o.name.startswith('Leader |') or o.name.startswith('Print note |'): o.hide_render = True
        scene.camera = overview; scene.render.filepath = str(OUT / 'experiment_overview_clean.png'); bpy.ops.render.render(write_still=True)
        for o in arrow_overlay.objects: o.hide_render = True
        for o in annot.objects:
            if o.name != 'IR camera field-of-view footprint' and not o.name.startswith('24 VDC') and not o.name.startswith('Data line'): o.hide_render = True
        for o in equip.objects: o.hide_render = not ('IR camera' in o.name or 'Rigid camera stand' in o.name or 'Tin PT100' in o.name or 'Tout PT100' in o.name)
        for o in close_annot.objects: o.hide_render = True
        for o in close_print.objects: o.hide_render = False
        scene.camera = closeup; scene.render.filepath = str(OUT / 'coldplate_closeup.png'); bpy.ops.render.render(write_still=True)
        for o in annot.objects:
            if o.name.startswith('Label |') or o.name.startswith('Leader |') or o.name.startswith('Print note |'): o.hide_render = True
            else: o.hide_render = False
        for o in equip.objects: o.hide_render = False
        for o in close_annot.objects: o.hide_render = True
        for o in print_overlay.objects: o.hide_render = True
        for o in close_print.objects: o.hide_render = True
        for o in arrow_overlay.objects: o.hide_render = True
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    print(f'COMPLETE mode={MODE}; verified CP-001 base width {width:.6f} m; output={OUT}')

if __name__ == '__main__': build()
