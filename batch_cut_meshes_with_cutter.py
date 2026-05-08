from __future__ import annotations

import argparse
import json
import shutil
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
        description="Apply the same boolean cutter mesh to multiple source meshes."
    )
    parser.add_argument("--source-model-dir", required=True, help="Directory containing source .ply meshes.")
    parser.add_argument("--target-model-dir", required=True, help="Directory to write the cut meshes into.")
    parser.add_argument("--cutter", required=True, help="Path to cutter mesh, for example .obj/.ply/.stl.")
    parser.add_argument(
        "--operation",
        default="INTERSECT",
        choices=["INTERSECT", "DIFFERENCE"],
        help="Boolean operation to apply. INTERSECT keeps the overlap with the cutter.",
    )
    parser.add_argument(
        "--method-files",
        nargs="+",
        default=["ours_base_config.ply", "deudf_dcudf.ply", "mind.ply"],
        help="Mesh filenames inside the model directory that should receive the cut.",
    )
    parser.add_argument(
        "--solver",
        default="EXACT",
        choices=["EXACT", "FAST"],
        help="Boolean solver. EXACT is slower but safer on messy meshes.",
    )
    return parser.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablock_collection in (
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.objects,
        bpy.data.images,
        bpy.data.curves,
    ):
        for block in list(datablock_collection):
            if block.users == 0:
                datablock_collection.remove(block)


def import_mesh(path: Path):
    path = path.resolve()
    ext = path.suffix.lower()
    bpy.ops.object.select_all(action="DESELECT")
    if ext == ".obj":
        try:
            bpy.ops.wm.obj_import(filepath=str(path))
        except Exception:
            bpy.ops.import_scene.obj(filepath=str(path))
    elif ext == ".ply":
        try:
            bpy.ops.wm.ply_import(filepath=str(path))
        except Exception:
            bpy.ops.import_mesh.ply(filepath=str(path))
    elif ext == ".stl":
        try:
            bpy.ops.wm.stl_import(filepath=str(path))
        except Exception:
            bpy.ops.import_mesh.stl(filepath=str(path))
    else:
        raise ValueError(f"Unsupported mesh format: {path}")

    mesh_objects = [obj for obj in bpy.context.selected_objects if obj.type == "MESH"]
    if not mesh_objects:
        raise RuntimeError(f"No mesh objects imported from: {path}")
    return max(mesh_objects, key=lambda obj: len(obj.data.vertices))


def export_ply(obj, path: Path):
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.wm.ply_export(filepath=str(path), export_selected_objects=True)
    except Exception:
        bpy.ops.export_mesh.ply(filepath=str(path), use_selection=True)


def apply_boolean_cut(mesh_path: Path, cutter_path: Path, output_path: Path, operation: str, solver: str):
    clear_scene()
    mesh_obj = import_mesh(mesh_path)
    mesh_obj.name = "cut_subject"
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    cutter_obj = import_mesh(cutter_path)
    cutter_obj.name = "cut_cutter"
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    bpy.ops.object.select_all(action="DESELECT")
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_obj
    modifier = mesh_obj.modifiers.new(name="BatchCut", type="BOOLEAN")
    modifier.operation = operation
    modifier.solver = solver
    modifier.object = cutter_obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)

    export_ply(mesh_obj, output_path)


def copy_passthrough_files(source_dir: Path, target_dir: Path, edited_files: set[str]):
    target_dir.mkdir(parents=True, exist_ok=True)
    for item in source_dir.iterdir():
        if item.name in edited_files:
            continue
        target = target_dir / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def patch_meta_json(path: Path, target_model_name: str):
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return

    data["model_name"] = target_model_name
    data["model_dirname"] = target_model_name

    methods = data.get("methods")
    if isinstance(methods, dict):
        for payload in methods.values():
            if not isinstance(payload, dict):
                continue
            exported = payload.get("exported_mesh")
            if isinstance(exported, str):
                exported_path = Path(exported)
                payload["exported_mesh"] = str(exported_path.with_name(exported_path.name))

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    args = parse_args()
    source_dir = Path(args.source_model_dir).resolve()
    target_dir = Path(args.target_model_dir).resolve()
    cutter_path = Path(args.cutter).resolve()

    if not source_dir.is_dir():
        raise FileNotFoundError(f"Source model dir not found: {source_dir}")
    if not cutter_path.exists():
        raise FileNotFoundError(f"Cutter file not found: {cutter_path}")

    edited_files = set(args.method_files)
    copy_passthrough_files(source_dir, target_dir, edited_files)

    for filename in args.method_files:
        mesh_path = source_dir / filename
        if not mesh_path.exists():
            print(f"[skip] missing source mesh: {mesh_path}")
            continue
        output_path = target_dir / filename
        print(f"[cut] {mesh_path} -> {output_path}")
        apply_boolean_cut(mesh_path, cutter_path, output_path, args.operation, args.solver)

    patch_meta_json(target_dir / "meta.json", target_dir.name)
    print(f"[done] wrote cut model folder: {target_dir}")


if __name__ == "__main__":
    main()
