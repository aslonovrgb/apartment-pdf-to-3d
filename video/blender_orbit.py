"""Blender: camera orbit around the built apartment for the demo video.

    blender -b out/apartment.blend --python video/blender_orbit.py -- OUT_DIR FRAMES

Uses the isometric camera saved by blender/build_scene.py, renders FRAMES PNG frames
(1920 x 1080, Workbench) while the camera swings around the model.
"""
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
out_dir, frames = argv[0], int(argv[1])
os.makedirs(out_dir, exist_ok=True)

scene = bpy.context.scene
cam = bpy.data.objects["Camera_Iso"]
for ob in bpy.data.collections["Labels"].objects:
    ob.hide_render = True

pts = [ob.matrix_world @ Vector(c) for ob in scene.objects if ob.type == "MESH" for c in ob.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
center = (lo + hi) / 2.0

# pivot at the model centre; the camera sits on the isometric direction and always looks at it
pivot = bpy.data.objects.new("Orbit", None)
scene.collection.objects.link(pivot)
pivot.location = center
tilt = Matrix.Rotation(math.radians(54.7356), 4, "X")
cam.parent = pivot
cam.matrix_parent_inverse = Matrix.Identity(4)
cam.location = tilt @ Vector((0.0, 0.0, 40.0))
cam.rotation_euler = (math.radians(54.7356), 0.0, 0.0)
cam.data.ortho_scale = max(hi.x - lo.x, hi.y - lo.y) * 1.74
cam.data.shift_x, cam.data.shift_y = 0.0, -0.045  # keep the model above the subtitle bar
cam.data.clip_end = 200.0

r = scene.render
r.resolution_x, r.resolution_y, r.resolution_percentage = 1920, 1080, 100
r.image_settings.file_format = "PNG"
r.filepath = os.path.join(out_dir, "")
scene.camera = cam
scene.frame_start, scene.frame_end = 1, frames

pivot.rotation_euler = (0.0, 0.0, math.radians(14.0))
pivot.keyframe_insert("rotation_euler", frame=1)
pivot.rotation_euler = (0.0, 0.0, math.radians(52.0))
pivot.keyframe_insert("rotation_euler", frame=frames)

bpy.ops.render.render(animation=True)
