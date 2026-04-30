import argparse
import json
import math
import sys

import bpy


def deg(v):
    return round(v * 180.0 / math.pi, 6)


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out")
    return parser.parse_args(argv)


def main():
    args = parse_args()
    obj = bpy.context.active_object
    # exclude shadow-catcher plane; prefer active object, else first non-plane mesh
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.name != "Plane"]
    mesh = obj if obj is not None and obj.type == "MESH" and obj.name != "Plane" else (meshes[0] if meshes else None)
    cam = bpy.context.scene.camera
    scene = bpy.context.scene

    payload = {}

    if mesh is not None:
        loc = tuple(round(v, 6) for v in mesh.location)
        rot = tuple(deg(v) for v in mesh.rotation_euler)
        scale = tuple(round(v, 6) for v in mesh.scale)
        payload["mesh"] = {
            "object_name": mesh.name,
            "location": list(loc),
            "rotation": list(rot),
            "scale": list(scale),
        }
        print(f"Mesh object: {mesh.name}")
        print(f"mesh.location = {loc}")
        print(f"mesh.rotation = {rot}")
        print(f"mesh.scale = {scale}")
        print(
            '{"location": [%s], "rotation": [%s], "scale": [%s]}'
            % (
                ", ".join(str(v) for v in loc),
                ", ".join(str(v) for v in rot),
                ", ".join(str(v) for v in scale),
            )
        )

    if cam is None:
        raise RuntimeError("No camera found in scene.")

    cam_loc = tuple(round(v, 6) for v in cam.location)
    cam_rot = tuple(deg(v) for v in cam.rotation_euler)
    focal = round(cam.data.lens, 6)
    payload["camera"] = {
        "object_name": cam.name,
        "location": list(cam_loc),
        "rotation": list(cam_rot),
        "focal_length": focal,
    }
    print(f"Camera object: {cam.name}")
    print(f"camera.location = {cam_loc}")
    print(f"camera.rotation = {cam_rot}")
    print(f"camera.focal_length = {focal}")
    print(
        '{"camera_location": [%s], "camera_rotation": [%s], "camera_focal_length": %s}'
        % (
            ", ".join(str(v) for v in cam_loc),
            ", ".join(str(v) for v in cam_rot),
            focal,
        )
    )

    shading = scene.display.shading
    payload["scene"] = {
        "render_engine": scene.render.engine,
        "workbench_light": shading.light,
        "workbench_color_type": shading.color_type,
        "workbench_single_color": [round(float(v), 6) for v in shading.single_color[:3]],
        "workbench_studio_light": shading.studio_light,
        "workbench_rotate_z": round(float(shading.studiolight_rotate_z), 6),
        "workbench_intensity": round(float(shading.studiolight_intensity), 6),
        "workbench_background_alpha": round(float(shading.studiolight_background_alpha), 6),
        "workbench_background_blur": round(float(shading.studiolight_background_blur), 6),
        "workbench_show_shadows": bool(shading.show_shadows),
        "workbench_show_cavity": bool(shading.show_cavity),
        "workbench_show_specular": bool(shading.show_specular_highlight),
        "workbench_cavity_type": shading.cavity_type,
        "workbench_ridge_factor": round(float(shading.curvature_ridge_factor), 6),
        "workbench_valley_factor": round(float(shading.curvature_valley_factor), 6),
    }
    print(json.dumps(payload, ensure_ascii=False))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
