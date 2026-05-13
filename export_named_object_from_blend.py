from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []

    parser = argparse.ArgumentParser(
        description="Open a .blend file and export one or more mesh objects as a standalone cutter mesh."
    )
    parser.add_argument("--blend", required=True, help="Path to the source .blend file.")
    parser.add_argument(
        "--objects",
        nargs="+",
        default=None,
        help="Explicit object names inside the blend. If omitted, --name-prefix is used.",
    )
    parser.add_argument(
        "--name-prefix",
        default="Cube",
        help="Export all mesh objects whose names start with this prefix when --objects is not given.",
    )
    parser.add_argument("--output", required=True, help="Output mesh path, supports .obj/.ply/.stl.")
    parser.add_argument(
        "--split-output-dir",
        default="",
        help="Optional directory. When set, export each source object as its own .ply file and ignore --output.",
    )
    return parser.parse_args(argv)


def export_selected_mesh(output_path: Path):
    ext = output_path.suffix.lower()
    if ext == ".obj":
        try:
            bpy.ops.wm.obj_export(filepath=str(output_path), export_selected_objects=True)
        except Exception:
            bpy.ops.export_scene.obj(filepath=str(output_path), use_selection=True)
        return
    if ext == ".ply":
        try:
            bpy.ops.wm.ply_export(filepath=str(output_path), export_selected_objects=True)
        except Exception:
            bpy.ops.export_mesh.ply(filepath=str(output_path), use_selection=True)
        return
    if ext == ".stl":
        try:
            bpy.ops.wm.stl_export(filepath=str(output_path), export_selected_objects=True)
        except Exception:
            bpy.ops.export_mesh.stl(filepath=str(output_path), use_selection=True)
        return
    raise ValueError(f"Unsupported output format: {output_path}")


def duplicate_with_applied_world_transform(source):
    duplicate = source.copy()
    duplicate.data = source.data.copy()
    bpy.context.scene.collection.objects.link(duplicate)

    bpy.ops.object.select_all(action="DESELECT")
    duplicate.select_set(True)
    bpy.context.view_layer.objects.active = duplicate
    bpy.ops.object.convert(target="MESH")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return bpy.context.view_layer.objects.active


def collect_source_objects(args):
    if args.objects:
        sources = []
        for name in args.objects:
            source = bpy.data.objects.get(name)
            if source is None:
                raise KeyError(f"Object not found in blend: {name}")
            if source.type != "MESH":
                raise TypeError(f"Object is not a mesh: {name} ({source.type})")
            sources.append(source)
        return sources

    prefix = args.name_prefix or "Cube"
    sources = sorted(
        [
            obj
            for obj in bpy.data.objects
            if obj.type == "MESH" and obj.name.startswith(prefix)
        ],
        key=lambda obj: obj.name,
    )
    if not sources:
        raise KeyError(f"No mesh objects found with prefix: {prefix}")
    return sources


def main():
    args = parse_args()
    blend_path = Path(args.blend).resolve()
    output_path = Path(args.output).resolve()

    if not blend_path.exists():
        raise FileNotFoundError(f"Blend file not found: {blend_path}")

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))

    sources = collect_source_objects(args)

    if args.split_output_dir:
        split_dir = Path(args.split_output_dir).resolve()
        split_dir.mkdir(parents=True, exist_ok=True)
        exported_paths = []
        for source in sources:
            duplicate = duplicate_with_applied_world_transform(source)
            output = split_dir / f"{source.name.replace('.', '_')}.ply"
            export_selected_mesh(output)
            exported_paths.append(output)
            bpy.data.objects.remove(duplicate, do_unlink=True)
        print(f"[export] {len(exported_paths)} object(s) -> {split_dir}")
        for path in exported_paths:
            print(f"[export-path] {path}")
        print("[export] sources=" + ", ".join(obj.name for obj in sources))
        return

    duplicates = [duplicate_with_applied_world_transform(source) for source in sources]

    bpy.ops.object.select_all(action="DESELECT")
    for duplicate in duplicates:
        duplicate.select_set(True)
    bpy.context.view_layer.objects.active = duplicates[0]
    if len(duplicates) > 1:
        bpy.ops.object.join()
    exported = bpy.context.view_layer.objects.active
    exported.name = "export_cutter"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    export_selected_mesh(output_path)
    print(f"[export] {len(sources)} object(s) -> {output_path}")
    print("[export] sources=" + ", ".join(obj.name for obj in sources))


if __name__ == "__main__":
    main()
