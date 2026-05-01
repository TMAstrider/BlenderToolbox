from pathlib import Path
import argparse
import json
import sys

import bpy
from mathutils import Vector

DEFAULT_LOOK_TARGET = (0.0, 0.0, -0.05)
DEFAULT_CAMERA_LOCATION = (4.9, -6.55, 3.95)
DEFAULT_CAMERA_FIT_MARGIN = 0.82


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []

    parser = argparse.ArgumentParser(
        description="Export the active Blender scene camera to a reusable JSON override."
    )
    parser.add_argument("--output", required=True, type=str, help="Path to output JSON file.")
    parser.add_argument(
        "--mode",
        type=str,
        default="directional_fit",
        choices=["directional_fit", "exact"],
        help="Export a rough position hint with unified auto-fit, or the exact camera transform.",
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()
    camera = bpy.context.scene.camera
    if camera is None:
        raise ValueError("No active scene camera found.")

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    default_target = Vector(DEFAULT_LOOK_TARGET)
    camera_forward = (camera.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))).normalized()
    focus_t = (default_target - camera.location).dot(camera_forward)
    if focus_t <= 0.0:
        focus_t = (default_target - camera.location).length
    estimated_look_target = camera.location + camera_forward * focus_t

    default_direction = default_target - Vector(DEFAULT_CAMERA_LOCATION)
    default_rotation = default_direction.to_track_quat("-Z", "Y").to_euler()
    same_location = all(abs(float(a) - float(b)) <= 1e-5 for a, b in zip(camera.location, DEFAULT_CAMERA_LOCATION))
    same_rotation = all(abs(float(a) - float(b)) <= 1e-5 for a, b in zip(camera.rotation_euler, default_rotation))
    same_lens = abs(float(camera.data.lens) - 58.0) <= 1e-5
    matches_default_camera = same_location and same_rotation and same_lens

    if args.mode == "exact":
        payload = {
            "location": [float(v) for v in camera.location],
            "rotation_euler": [float(v) for v in camera.rotation_euler],
            "lens": float(camera.data.lens),
            "clip_start": float(camera.data.clip_start),
            "clip_end": float(camera.data.clip_end),
        }
    else:
        payload = {
            "position_hint": [float(v) for v in camera.location],
            "look_target": [float(v) for v in estimated_look_target],
            "lens": float(camera.data.lens),
            "fit_margin": DEFAULT_CAMERA_FIT_MARGIN,
        }

    payload["export_mode"] = args.mode
    payload["exact_location"] = [float(v) for v in camera.location]
    payload["exact_rotation_euler"] = [float(v) for v in camera.rotation_euler]
    payload["exact_lens"] = float(camera.data.lens)
    payload["clip_start"] = float(camera.data.clip_start)
    payload["clip_end"] = float(camera.data.clip_end)
    payload["matches_default_camera"] = bool(matches_default_camera)
    payload["estimated_look_target"] = [float(v) for v in estimated_look_target]

    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")

    print(f"Saved camera override: {output_path}")


if __name__ == "__main__":
    main()
