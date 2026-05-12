from pathlib import Path
import argparse
import sys

import bpy
from mathutils import Matrix


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--targets", nargs="+", required=True)
    return parser.parse_args(argv)


def base_name(name):
    return name.split(".")[0]


def vec_tuple(value):
    return tuple(float(v) for v in value)


def matrix_tuple(value):
    return tuple(tuple(float(v) for v in row) for row in value)


def restore_matrix(value):
    return Matrix(value)


def largest_subject_mesh(scene):
    meshes = [
        obj
        for obj in scene.objects
        if obj.type == "MESH"
        and not obj.name.lower().startswith("plane")
        and len(obj.data.vertices) > 0
    ]
    if not meshes:
        return None
    preferred = [obj for obj in meshes if base_name(obj.name) == "surface_contour_subject"]
    if preferred:
        return preferred[0]
    return max(meshes, key=lambda obj: len(obj.data.vertices))


def capture_source(source_path):
    bpy.ops.wm.open_mainfile(filepath=str(Path(source_path).resolve()))
    scene = bpy.context.scene

    camera = scene.camera
    if camera is None:
        raise RuntimeError("Source blend has no active camera.")

    subject = largest_subject_mesh(scene)
    if subject is None:
        raise RuntimeError("Source blend has no subject mesh.")

    lights = {}
    for obj in scene.objects:
        if obj.type != "LIGHT":
            continue
        relative_matrix = camera.matrix_world.inverted() @ obj.matrix_world
        lights[base_name(obj.name)] = {
            "location": vec_tuple(obj.location),
            "rotation_euler": vec_tuple(obj.rotation_euler),
            "scale": vec_tuple(obj.scale),
            "matrix_world": matrix_tuple(obj.matrix_world),
            "relative_matrix": matrix_tuple(relative_matrix),
            "energy": float(obj.data.energy),
            "size": float(getattr(obj.data, "size", 0.0)),
        }

    return {
        "camera": {
            "location": vec_tuple(camera.location),
            "rotation_euler": vec_tuple(camera.rotation_euler),
            "scale": vec_tuple(camera.scale),
            "matrix_world": matrix_tuple(camera.matrix_world),
            "lens": float(camera.data.lens),
            "shift_x": float(camera.data.shift_x),
            "shift_y": float(camera.data.shift_y),
            "sensor_width": float(camera.data.sensor_width),
            "sensor_height": float(camera.data.sensor_height),
            "clip_start": float(camera.data.clip_start),
            "clip_end": float(camera.data.clip_end),
            "type": camera.data.type,
            "ortho_scale": float(camera.data.ortho_scale),
        },
        "subject": {
            "location": vec_tuple(subject.location),
            "rotation_euler": vec_tuple(subject.rotation_euler),
            "scale": vec_tuple(subject.scale),
            "matrix_world": matrix_tuple(subject.matrix_world),
        },
        "lights": lights,
        "resolution": (scene.render.resolution_x, scene.render.resolution_y),
    }


def apply_camera(scene, state):
    camera = scene.camera
    if camera is None:
        bpy.ops.object.camera_add()
        camera = bpy.context.object
        scene.camera = camera

    camera.parent = None
    camera.matrix_parent_inverse = Matrix.Identity(4)
    camera.location = state["location"]
    camera.rotation_mode = "XYZ"
    camera.rotation_euler = state["rotation_euler"]
    camera.scale = state["scale"]
    camera.data.type = state["type"]
    camera.data.lens = state["lens"]
    camera.data.shift_x = state["shift_x"]
    camera.data.shift_y = state["shift_y"]
    camera.data.sensor_width = state["sensor_width"]
    camera.data.sensor_height = state["sensor_height"]
    camera.data.clip_start = state["clip_start"]
    camera.data.clip_end = state["clip_end"]
    camera.data.ortho_scale = state["ortho_scale"]
    camera.matrix_world = restore_matrix(state["matrix_world"])


def apply_subject_transform(scene, state):
    subject = largest_subject_mesh(scene)
    if subject is None:
        return

    subject.parent = None
    subject.matrix_parent_inverse = Matrix.Identity(4)
    subject.location = state["location"]
    subject.rotation_mode = "XYZ"
    subject.rotation_euler = state["rotation_euler"]
    subject.scale = state["scale"]
    subject.matrix_world = restore_matrix(state["matrix_world"])

    # Edge overlay curve points are generated in subject local coordinates.
    # Keep the curve as a child with identity local transform so it follows
    # the subject instead of preserving its old world-space position.
    for obj in scene.objects:
        if obj.type == "CURVE" and "nonmanifold_edge_overlay" in obj.name:
            obj.parent = subject
            obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.location = (0.0, 0.0, 0.0)
            obj.rotation_mode = "XYZ"
            obj.rotation_euler = (0.0, 0.0, 0.0)
            obj.scale = (1.0, 1.0, 1.0)


def apply_lights(scene, lights):
    camera = scene.camera
    for obj in scene.objects:
        if obj.type != "LIGHT":
            continue
        state = lights.get(base_name(obj.name))
        if state is None:
            continue
        relative_matrix = state.get("relative_matrix")
        if camera is not None and relative_matrix is not None:
            obj.parent = camera
            obj.matrix_parent_inverse = Matrix.Identity(4)
            loc, rot, scale = restore_matrix(relative_matrix).decompose()
            obj.location = loc
            obj.rotation_mode = "XYZ"
            obj.rotation_euler = rot.to_euler("XYZ")
            obj.scale = scale
        else:
            obj.parent = None
            obj.location = state["location"]
            obj.rotation_mode = "XYZ"
            obj.rotation_euler = state["rotation_euler"]
            obj.scale = state["scale"]
            obj.matrix_world = restore_matrix(state["matrix_world"])
        obj.data.energy = state["energy"]
        if hasattr(obj.data, "size"):
            obj.data.size = state["size"]


def apply_render_defaults(scene, resolution):
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "16"
    scene.use_nodes = False

    for obj in scene.objects:
        if obj.type == "MESH" and obj.name.lower().startswith("plane"):
            obj.hide_render = True
            obj.hide_viewport = True
            if hasattr(obj, "is_shadow_catcher"):
                obj.is_shadow_catcher = False


def sync_target(target_path, state):
    bpy.ops.wm.open_mainfile(filepath=str(Path(target_path).resolve()))
    scene = bpy.context.scene
    apply_camera(scene, state["camera"])
    apply_subject_transform(scene, state["subject"])
    apply_lights(scene, state["lights"])
    apply_render_defaults(scene, state["resolution"])
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(target_path).resolve()))


def main():
    args = parse_args()
    state = capture_source(args.source)
    for target in args.targets:
        sync_target(target, state)


if __name__ == "__main__":
    main()
