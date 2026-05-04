from pathlib import Path
import argparse
import json
import sys

import bpy


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--look-target", nargs=3, type=float, default=(0.0, 0.0, -0.05))
    return parser.parse_args(argv)


def main():
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.blend).resolve()))

    camera = bpy.context.scene.camera
    if camera is None:
        raise RuntimeError("The blend file does not have an active scene camera.")

    data = {
        "location": [float(v) for v in camera.location],
        "rotation_euler": [float(v) for v in camera.rotation_euler],
        "lens": float(camera.data.lens),
        "clip_start": float(camera.data.clip_start),
        "clip_end": float(camera.data.clip_end),
        "look_target": [float(v) for v in args.look_target],
    }

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
