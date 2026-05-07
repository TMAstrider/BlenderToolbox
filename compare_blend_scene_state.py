from pathlib import Path
import argparse
import json
import sys

import bpy
from mathutils import Vector


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def object_bounds(obj):
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    min_v = [min(c[i] for c in corners) for i in range(3)]
    max_v = [max(c[i] for c in corners) for i in range(3)]
    center = [(min_v[i] + max_v[i]) * 0.5 for i in range(3)]
    size = [max_v[i] - min_v[i] for i in range(3)]
    return {
        "min": [float(v) for v in min_v],
        "max": [float(v) for v in max_v],
        "center": [float(v) for v in center],
        "size": [float(v) for v in size],
    }


def main():
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.blend).resolve()))

    scene = bpy.context.scene
    cam = scene.camera
    camera = None
    if cam:
        camera = {
            "name": cam.name,
            "location": [float(v) for v in cam.location],
            "rotation_euler": [float(v) for v in cam.rotation_euler],
            "scale": [float(v) for v in cam.scale],
            "lens": float(cam.data.lens),
            "shift_x": float(cam.data.shift_x),
            "shift_y": float(cam.data.shift_y),
            "sensor_width": float(cam.data.sensor_width),
            "sensor_height": float(cam.data.sensor_height),
            "type": cam.data.type,
            "clip_start": float(cam.data.clip_start),
            "clip_end": float(cam.data.clip_end),
        }

    meshes = []
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        meshes.append(
            {
                "name": obj.name,
                "hide_render": bool(obj.hide_render),
                "location": [float(v) for v in obj.location],
                "rotation_euler": [float(v) for v in obj.rotation_euler],
                "scale": [float(v) for v in obj.scale],
                "bounds": object_bounds(obj),
                "vertex_count": len(obj.data.vertices),
                "material_names": [slot.material.name if slot.material else "" for slot in obj.material_slots],
            }
        )

    output = {
        "blend": str(Path(args.blend).resolve()),
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "film_transparent": bool(scene.render.film_transparent),
        "camera": camera,
        "meshes": meshes,
    }

    Path(args.output).resolve().write_text(json.dumps(output, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
