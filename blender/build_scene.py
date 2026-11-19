"""Build apartment.blend (and top / isometric renders) from plan.json.

    blender -b --factory-startup --python blender/build_scene.py -- --plan data/plan.json --out out

Called by build.py after validation. Geometry in plan.json is in millimetres,
the Blender scene is in metres. Every object carries the plan.json ID as its
name and as the custom property `plan_id`.
"""
import argparse
import math
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from aptplan import geometry as g  # noqa: E402
from aptplan.layout import door_swings, wall_end_extensions, wall_pieces  # noqa: E402
from aptplan.model import load_plan_unchecked  # noqa: E402

MM = 0.001
RES_X, RES_Y = 1800, 1300

# colours are linear RGBA (Workbench "Material" colour mode uses diffuse_color)
PALETTE = {
    "wall": (0.80, 0.79, 0.76, 1.0),
    "wall_exterior": (0.62, 0.60, 0.57, 1.0),
    "floor_balcony": (0.55, 0.56, 0.58, 1.0),
    "door": (0.42, 0.27, 0.15, 1.0),
    "swing": (0.25, 0.25, 0.28, 1.0),
    "frame": (0.95, 0.95, 0.95, 1.0),
    "glass": (0.45, 0.70, 0.90, 0.35),
    "label": (0.08, 0.08, 0.10, 1.0),
    "cabinet": (0.93, 0.93, 0.91, 1.0),
    "counter": (0.20, 0.20, 0.22, 1.0),
    "plinth": (0.15, 0.15, 0.15, 1.0),
    "fabric": (0.30, 0.42, 0.55, 1.0),
    "wood": (0.55, 0.38, 0.22, 1.0),
    "linen": (0.95, 0.94, 0.90, 1.0),
    "ceramic": (0.97, 0.97, 0.98, 1.0),
    "appliance": (0.75, 0.76, 0.78, 1.0),
    "generic": (0.65, 0.62, 0.58, 1.0),
}
FLOOR_TINTS = [
    (0.93, 0.86, 0.72, 1.0), (0.82, 0.90, 0.80, 1.0), (0.80, 0.86, 0.94, 1.0),
    (0.94, 0.82, 0.80, 1.0), (0.88, 0.84, 0.94, 1.0), (0.94, 0.92, 0.78, 1.0),
    (0.80, 0.92, 0.92, 1.0), (0.90, 0.88, 0.86, 1.0),
]


# --------------------------------------------------------------------------- helpers

def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--plan", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--no-render", action="store_true")
    return p.parse_args(argv)


_MATS = {}


def material(name, rgba):
    if name in _MATS:
        return _MATS[name]
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = rgba
    try:
        mat.use_nodes = True  # deprecated (always on) in newer Blender versions
    except Exception:
        pass
    tree = getattr(mat, "node_tree", None)
    if tree is not None:
        bsdf = tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = rgba
            if rgba[3] < 1.0 and "Alpha" in bsdf.inputs:
                bsdf.inputs["Alpha"].default_value = rgba[3]
    if rgba[3] < 1.0:
        for attr, value in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
            try:
                setattr(mat, attr, value)
                break
            except Exception:
                continue
    _MATS[name] = mat
    return mat


def collection(name):
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


class MeshBuilder:
    def __init__(self):
        self.verts = []
        self.faces = []
        self.face_mats = []
        self.mats = []

    def _mat_index(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def prism(self, poly_mm, z0_mm, z1_mm, mat):
        poly = [(x * MM, y * MM) for x, y in g.ensure_ccw(poly_mm)]
        n = len(poly)
        b = len(self.verts)
        z0, z1 = z0_mm * MM, z1_mm * MM
        self.verts += [(x, y, z0) for x, y in poly] + [(x, y, z1) for x, y in poly]
        mi = self._mat_index(mat)
        self.faces.append(tuple(b + i for i in reversed(range(n))))
        self.faces.append(tuple(b + n + i for i in range(n)))
        for i in range(n):
            j = (i + 1) % n
            self.faces.append((b + i, b + j, b + n + j, b + n + i))
        self.face_mats += [mi] * (n + 2)

    def build(self, name, col, props=None):
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.verts, [], self.faces)
        for mat in self.mats:
            me.materials.append(mat)
        for poly, mi in zip(me.polygons, self.face_mats):
            poly.material_index = mi
        me.validate()
        me.update()
        ob = bpy.data.objects.new(name, me)
        col.objects.link(ob)
        for k, v in (props or {}).items():
            ob[k] = v
        return ob


def wall_box(w, s0, s1, n0, n1):
    """Rectangle along wall `w` between stations s0..s1 and normal offsets n0..n1 (mm)."""
    a, b = w.point_at(s0), w.point_at(s1)
    n = w.normal
    return [g.add(a, g.mul(n, n0)), g.add(b, g.mul(n, n0)), g.add(b, g.mul(n, n1)), g.add(a, g.mul(n, n1))]


def local_box(center, rot_deg, x0, x1, y0, y1):
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [g.add(center, g.rotate(p, rot_deg)) for p in pts]


# --------------------------------------------------------------------------- builders

def build_walls(plan, col):
    ext = wall_end_extensions(plan)
    for w in sorted(plan.walls, key=lambda w: w.id):
        mb = MeshBuilder()
        mat = material("Wall exterior" if w.kind == "exterior" else "Wall", PALETTE["wall_exterior" if w.kind == "exterior" else "wall"])
        for s0, s1, z0, z1 in wall_pieces(plan, w, ext[w.id]):
            mb.prism(wall_box(w, s0, s1, -w.thickness / 2, w.thickness / 2), z0, z1, mat)
        mb.build(w.id, col, {"plan_id": w.id, "kind": w.kind, "thickness_mm": w.thickness, "source": w.source})


def build_floors(plan, col):
    interior = 0
    for z in sorted(plan.zones, key=lambda z: z.id):
        if z.kind == "balcony":
            mat = material("Floor balcony", PALETTE["floor_balcony"])
        else:
            mat = material(f"Floor {interior % len(FLOOR_TINTS)}", FLOOR_TINTS[interior % len(FLOOR_TINTS)])
            interior += 1
        mb = MeshBuilder()
        mb.prism(z.polygon, -50.0, 0.0, mat)
        mb.build(f"Floor_{z.id}", col, {"plan_id": z.id, "zone_name": z.name, "kind": z.kind,
                                        "area_m2": round(g.polygon_area(z.polygon) / 1e6, 2)})


def build_openings(plan, doors_col, windows_col):
    walls = plan.walls_by_id
    leaf_t = 40.0
    for o in sorted(plan.openings, key=lambda o: o.id):
        w = walls[o.wall_id]
        a, b = o.offset, o.offset + o.width
        if o.type == "window":
            mb = MeshBuilder()
            frame = material("Window frame", PALETTE["frame"])
            glass = material("Glass", PALETTE["glass"])
            p, d = 50.0, 35.0  # profile width, half depth
            mb.prism(wall_box(w, a, a + p, -d, d), o.sill, o.head, frame)
            mb.prism(wall_box(w, b - p, b, -d, d), o.sill, o.head, frame)
            mb.prism(wall_box(w, a + p, b - p, -d, d), o.sill, o.sill + p, frame)
            mb.prism(wall_box(w, a + p, b - p, -d, d), o.head - p, o.head, frame)
            mb.build(f"{o.id}_frame", windows_col, {"plan_id": o.id, "type": o.type})
            gb = MeshBuilder()
            gb.prism(wall_box(w, a + p, b - p, -5.0, 5.0), o.sill + p, o.head - p, glass)
            gb.build(f"{o.id}_glass", windows_col, {"plan_id": o.id, "type": o.type,
                                                    "width_mm": o.width, "height_mm": o.height})
        elif o.type == "door":
            mb = MeshBuilder()
            arc = MeshBuilder()
            steps = 24
            mat = material("Door swing", PALETTE["swing"])
            for sw in door_swings(w, o):
                # leaf opened 90 degrees, lying along the hinge jamb
                p0 = sw.hinge
                p1 = g.add(p0, g.mul(sw.open_dir, sw.radius))
                q = g.mul(sw.closed_dir, leaf_t)
                leaf = [p0, p1, g.add(p1, q), g.add(p0, q)]
                mb.prism(leaf, o.sill, o.head - 10.0, material("Door", PALETTE["door"]))
                # swing arc on the floor (visible in the top view)
                r0, r1 = sw.radius - 12.0, sw.radius
                for k in range(steps):
                    t0 = math.radians(sw.start_deg + (sw.end_deg - sw.start_deg) * k / steps)
                    t1 = math.radians(sw.start_deg + (sw.end_deg - sw.start_deg) * (k + 1) / steps)
                    quad = [(sw.hinge[0] + r * math.cos(t), sw.hinge[1] + r * math.sin(t))
                            for r, t in ((r0, t0), (r1, t0), (r1, t1), (r0, t1))]
                    arc.prism(quad, 2.0, 4.0, mat)
            mb.build(o.id, doors_col, {"plan_id": o.id, "type": o.type, "width_mm": o.width,
                                       "height_mm": o.height, "hinge": o.hinge, "swing": o.swing,
                                       "leaves": o.leaves})
            arc.build(f"{o.id}_swing", doors_col, {"plan_id": o.id})


def furniture_parts(f):
    """Boxes (x0, x1, y0, y1, z0, z1, material) in local mm; back of the item is +Y."""
    W, D, H = f.width, f.depth, f.height
    hw, hd = W / 2, D / 2
    t = f.type
    P = []

    def legs(z1, s=45.0, inset=30.0):
        return [(sx * (hw - inset) - s / 2, sx * (hw - inset) + s / 2,
                 sy * (hd - inset) - s / 2, sy * (hd - inset) + s / 2, 0.0, z1, "wood")
                for sx in (-1, 1) for sy in (-1, 1)]

    if t == "kitchen":
        base = min(860.0, H)
        P += [(-hw, hw, -hd + 50, hd, 0, 100, "plinth"), (-hw, hw, -hd, hd, 100, base, "cabinet"),
              (-hw, hw, -hd - 20, hd, base, base + 40, "counter")]
        if H > 1500:
            P.append((-hw, hw, hd - 350, hd, 1450, H, "cabinet"))
    elif t == "sofa":
        arm, back = min(200.0, W * 0.12), min(220.0, D * 0.25)
        P += [(-hw + arm, hw - arm, -hd, hd - back, 0, 430, "fabric"), (-hw, hw, hd - back, hd, 0, H, "fabric"),
              (-hw, -hw + arm, -hd, hd, 0, 620, "fabric"), (hw - arm, hw, -hd, hd, 0, 620, "fabric")]
    elif t in ("table", "desk"):
        P += [(-hw, hw, -hd, hd, H - 40, H, "wood")] + legs(H - 40)
    elif t == "chair":
        P += [(-hw, hw, -hd, hd, 430, 470, "wood"), (-hw, hw, hd - 40, hd, 470, H, "wood")] + legs(430, 35.0, 20.0)
    elif t == "bed":
        P += [(-hw, hw, -hd, hd, 0, 300, "wood"), (-hw + 20, hw - 20, -hd + 20, hd - 80, 300, max(H, 320), "linen"),
              (-hw, hw, hd - 60, hd, 0, 950, "wood")]
    elif t == "wardrobe":
        P += [(-hw, hw, -hd, hd, 0, H, "cabinet"), (-2, 2, -hd - 2, -hd, 50, H - 50, "plinth")]
    elif t == "nightstand":
        P += [(-hw, hw, -hd, hd, 0, H, "wood")]
    elif t == "bathtub":
        P += [(-hw, hw, -hd, hd, 0, H, "ceramic")]
    elif t == "shower":
        P += [(-hw, hw, -hd, hd, 0, 60, "ceramic")]
    elif t == "toilet":
        P += [(-hw, hw, -hd, hd - 180, 0, 400, "ceramic"), (-hw, hw, hd - 180, hd, 0, H, "ceramic")]
    elif t == "sink":
        P += [(-hw, hw, -hd, hd, 0, H, "cabinet"), (-hw + 40, hw - 40, -hd + 40, hd - 60, H, H + 20, "ceramic")]
    elif t in ("washer", "fridge", "stove", "dishwasher"):
        P += [(-hw, hw, -hd, hd, 0, H, "appliance")]
    elif t == "tv_stand":
        P += [(-hw, hw, -hd, hd, 0, H, "wood")]
    else:
        P += [(-hw, hw, -hd, hd, 0, H, "generic")]
    return P


def build_furniture(plan, col):
    for f in sorted(plan.furniture, key=lambda f: f.id):
        mb = MeshBuilder()
        for x0, x1, y0, y1, z0, z1, mk in furniture_parts(f):
            mb.prism(local_box(f.center, f.rotation, x0, x1, y0, y1), z0, z1, material(mk.capitalize(), PALETTE[mk]))
        mb.build(f"{f.id}_{f.type}", col, {"plan_id": f.id, "type": f.type, "zone": f.zone_id,
                                           "size_mm": f"{f.width:.0f}x{f.depth:.0f}x{f.height:.0f}"})


def build_labels(plan, col):
    mat = material("Label", PALETTE["label"])
    for z in sorted(plan.zones, key=lambda z: z.id):
        x, y = g.label_point(z.polygon)
        curve = bpy.data.curves.new(f"Label_{z.id}", "FONT")
        curve.body = f"{z.name}\n{g.polygon_area(z.polygon) / 1e6:.2f} м²"
        curve.align_x = "CENTER"
        curve.align_y = "CENTER"
        curve.size = 0.26
        ob = bpy.data.objects.new(f"Label_{z.id}", curve)
        ob.location = (x * MM, y * MM, 0.01)
        ob.data.materials.append(mat)
        ob["plan_id"] = z.id
        col.objects.link(ob)


# --------------------------------------------------------------------------- cameras & render

def scene_bounds(plan):
    pts = []
    for w in plan.walls:
        pts += g.segment_rect(w.start, w.end, w.thickness)
    for z in plan.zones:
        pts += z.polygon
    x0, y0, x1, y1 = g.bbox(pts)
    zmax = max([w.height for w in plan.walls] + [2700.0])
    return x0 * MM, y0 * MM, x1 * MM, y1 * MM, zmax * MM


def add_camera(name, col, rot, bounds, margin=1.08):
    from mathutils import Euler, Vector
    x0, y0, x1, y1, z1 = bounds
    cam_data = bpy.data.cameras.new(name)
    cam_data.type = "ORTHO"
    cam = bpy.data.objects.new(name, cam_data)
    col.objects.link(cam)
    cam.rotation_euler = Euler(rot, "XYZ")
    m = cam.rotation_euler.to_matrix()
    right, up, view = m @ Vector((1, 0, 0)), m @ Vector((0, 1, 0)), m @ Vector((0, 0, -1))
    corners = [Vector((x, y, z)) for x in (x0, x1) for y in (y0, y1) for z in (0.0, z1)]
    us = [c.dot(right) for c in corners]
    vs = [c.dot(up) for c in corners]
    ds = [c.dot(view) for c in corners]
    w, h = max(us) - min(us), max(vs) - min(vs)
    aspect = RES_X / RES_Y
    cam_data.ortho_scale = max(w, h * aspect) * margin
    centre = right * ((max(us) + min(us)) / 2) + up * ((max(vs) + min(vs)) / 2) + view * min(ds)
    cam.location = centre - view * 30.0
    cam_data.clip_start = 0.1
    cam_data.clip_end = 30.0 + (max(ds) - min(ds)) + 10.0
    return cam


def setup_render(scene):
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = RES_X
    scene.render.resolution_y = RES_Y
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    sh = scene.display.shading
    sh.light = "STUDIO"
    try:
        sh.studio_light = "paint.sl"  # soft, even light: no black faces in the isometric view
    except Exception:
        pass
    sh.color_type = "MATERIAL"
    sh.show_cavity = True
    sh.show_object_outline = True
    sh.show_shadows = False
    try:
        scene.display.render_aa = "16"
    except Exception:
        pass
    world = bpy.data.worlds.new("World")
    world.color = (1.0, 1.0, 1.0)
    scene.world = world
    try:
        scene.view_settings.view_transform = "Standard"
    except Exception:
        pass


def render(scene, cam, path):
    scene.camera = cam
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


# --------------------------------------------------------------------------- main

def main():
    args = parse_args()
    plan = load_plan_unchecked(args.plan)
    os.makedirs(args.out, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "Apartment"
    us = scene.unit_settings
    us.system = "METRIC"
    us.scale_length = 1.0
    us.length_unit = "METERS"
    scene["plan_json"] = os.path.basename(args.plan)
    scene["schema_version"] = plan.schema_version
    scene["project"] = plan.project.get("name", "")

    cols = {name: collection(name) for name in ("Walls", "Floors", "Windows", "Doors", "Furniture", "Labels", "Cameras")}
    build_walls(plan, cols["Walls"])
    build_floors(plan, cols["Floors"])
    build_openings(plan, cols["Doors"], cols["Windows"])
    build_furniture(plan, cols["Furniture"])
    build_labels(plan, cols["Labels"])

    bounds = scene_bounds(plan)
    cam_top = add_camera("Camera_Top", cols["Cameras"], (0.0, 0.0, 0.0), bounds, margin=1.06)
    cam_iso = add_camera("Camera_Iso", cols["Cameras"], (math.radians(54.7356), 0.0, math.radians(35.0)), bounds)
    setup_render(scene)

    if not args.no_render:
        out_dir = os.path.abspath(args.out)
        labels = list(cols["Labels"].objects)
        # top view: flat plan colours, labels lifted above furniture,
        # walls drawn dark like a plan (the saved scene keeps the 3D colours)
        scene.display.shading.light = "FLAT"
        for ob in labels:
            ob.location.z = bounds[4] + 0.05
        wall_mats = [m for m in bpy.data.materials if m.name.startswith("Wall")]
        saved = {m.name: tuple(m.diffuse_color) for m in wall_mats}
        for m in wall_mats:
            m.diffuse_color = (0.09, 0.09, 0.095, 1.0) if m.name == "Wall exterior" else (0.27, 0.27, 0.28, 1.0)
        render(scene, cam_top, os.path.join(out_dir, "top.png"))
        for m in wall_mats:
            m.diffuse_color = saved[m.name]
        # isometric view: studio light, labels hidden (they would float in the air)
        scene.display.shading.light = "STUDIO"
        for ob in labels:
            ob.location.z = 0.01
            ob.hide_render = True
        render(scene, cam_iso, os.path.join(out_dir, "iso.png"))
        for ob in labels:
            ob.hide_render = False

    scene.camera = cam_iso
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(os.path.abspath(args.out), "apartment.blend"))
    print(f"[blender] objects: {len(bpy.data.objects)}; saved {args.out}/apartment.blend")


if __name__ == "__main__":
    main()
