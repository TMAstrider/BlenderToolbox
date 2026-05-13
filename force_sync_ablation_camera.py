from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Matrix


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Force-copy camera/light rig from one blend to ablation targets.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--targets", nargs="+", required=True)
    return parser.parse_args(argv)


def matrix_tuple(value):
    return tuple(tuple(float(v) for v in row) for row in value)


def restore_matrix(value):
    return Matrix(value)


def capture(source_path: Path):
    bpy.ops.wm.open_mainfile(filepath=str(source_path.resolve()))
    scene = bpy.context.scene
    camera = scene.camera
    if camera is None:
        raise RuntimeError(f"No active camera in {source_path}")
    lights = {}
    for obj in scene.objects:
        if obj.type != "LIGHT":
            continue
        lights[obj.name.split(".")[0]] = {
            "matrix_world": matrix_tuple(obj.matrix_world),
            "energy": float(obj.data.energy),
            "size": float(getattr(obj.data, "size", 0.0)),
            "parent_to_camera": obj.parent == camera,
            "relative_to_camera": matrix_tuple(camera.matrix_world.inverted() @ obj.matrix_world),
        }
    return {
        "camera_matrix": matrix_tuple(camera.matrix_world),
        "camera_lens": float(camera.data.lens),
        "camera_shift_x": float(camera.data.shift_x),
        "camera_shift_y": float(camera.data.shift_y),
        "camera_sensor_width": float(camera.data.sensor_width),
        "camera_sensor_height": float(camera.data.sensor_height),
        "camera_clip_start": float(camera.data.clip_start),
        "camera_clip_end": float(camera.data.clip_end),
        "camera_type": camera.data.type,
        "camera_ortho_scale": float(camera.data.ortho_scale),
        "lights": lights,
    }


def apply(target_path: Path, state: dict):
    bpy.ops.wm.open_mainfile(filepath=str(target_path.resolve()))
    scene = bpy.context.scene
    camera = scene.camera
    if camera is None:
        raise RuntimeError(f"No active camera in {target_path}")

    camera.parent = None
    camera.matrix_parent_inverse = Matrix.Identity(4)
    camera.data.type = state["camera_type"]
    camera.data.lens = state["camera_lens"]
    camera.data.shift_x = state["camera_shift_x"]
    camera.data.shift_y = state["camera_shift_y"]
    camera.data.sensor_width = state["camera_sensor_width"]
    camera.data.sensor_height = state["camera_sensor_height"]
    camera.data.clip_start = state["camera_clip_start"]
    camera.data.clip_end = state["camera_clip_end"]
    camera.data.ortho_scale = state["camera_ortho_scale"]
    camera.matrix_world = restore_matrix(state["camera_matrix"])

    for obj in scene.objects:
        if obj.type != "LIGHT":
            continue
        light_state = state["lights"].get(obj.name.split(".")[0])
        if light_state is None:
            continue
        if light_state["parent_to_camera"]:
            obj.parent = camera
            obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.matrix_basis = restore_matrix(light_state["relative_to_camera"])
        else:
            obj.parent = None
            obj.matrix_world = restore_matrix(light_state["matrix_world"])
        obj.data.energy = light_state["energy"]
        if hasattr(obj.data, "size"):
            obj.data.size = light_state["size"]

    bpy.ops.wm.save_as_mainfile(filepath=str(target_path.resolve()))


def main():
    args = parse_args()
    state = capture(Path(args.source))
    for target in args.targets:
        apply(Path(target), state)


if __name__ == "__main__":
    main()
