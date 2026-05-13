from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Export a cutter object from a .blend and batch-cut all mesh methods in one model folder."
    )
    parser.add_argument("--blend", required=True, help="Source .blend containing the cutter object.")
    parser.add_argument("--source-model-dir", required=True, help="Model directory containing method meshes.")
    parser.add_argument("--target-model-dir", default="", help="Optional explicit output model directory.")
    parser.add_argument("--target-suffix", default="_clean", help="Suffix appended to the source model dirname.")
    parser.add_argument(
        "--cutter-objects",
        nargs="+",
        default=None,
        help="Optional explicit cutter object names inside the blend.",
    )
    parser.add_argument(
        "--cutter-prefix",
        default="Cube",
        help="When --cutter-objects is not given, export all mesh objects whose names start with this prefix.",
    )
    parser.add_argument("--operation", default="DIFFERENCE", choices=["INTERSECT", "DIFFERENCE"])
    parser.add_argument("--cut-mode", default="open", choices=["open", "boolean"])
    parser.add_argument("--solver", default="EXACT", choices=["EXACT", "FAST"])
    parser.add_argument("--method-files", nargs="+", default=None, help="Optional explicit mesh filenames to cut.")
    parser.add_argument("--skip-files", nargs="+", default=["gt_pointcloud.ply"], help="Mesh filenames to leave untouched.")
    parser.add_argument("--blender-exe", default=DEFAULT_BLENDER)
    parser.add_argument("--overwrite", action="store_true", help="Overwrite the target model directory if it exists.")
    return parser.parse_args()


def command_text(cmd: list[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in cmd)


def run(cmd: list[str], cwd: Path):
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {command_text(cmd)}")


def discover_method_files(source_dir: Path, skip_files: set[str]) -> list[str]:
    files = []
    for path in sorted(source_dir.glob("*.ply")):
        if path.name in skip_files:
            continue
        files.append(path.name)
    if not files:
        raise FileNotFoundError(f"No cuttable .ply meshes found under: {source_dir}")
    return files


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    blender_exe = Path(args.blender_exe).resolve()
    blend_path = Path(args.blend).resolve()
    source_dir = Path(args.source_model_dir).resolve()

    if not blender_exe.exists():
        raise FileNotFoundError(f"Blender not found: {blender_exe}")
    if not blend_path.exists():
        raise FileNotFoundError(f"Blend file not found: {blend_path}")
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Source model dir not found: {source_dir}")

    if args.target_model_dir:
        target_dir = Path(args.target_model_dir).resolve()
    else:
        target_dir = source_dir.with_name(source_dir.name + args.target_suffix)

    if target_dir.exists():
        if not args.overwrite:
            raise FileExistsError(f"Target model dir already exists: {target_dir}. Use --overwrite to replace it.")
        resolved_parent = source_dir.parent.resolve()
        if target_dir.parent.resolve() != resolved_parent:
            raise RuntimeError(f"Refusing to overwrite target outside source parent: {target_dir}")
        shutil.rmtree(target_dir)

    method_files = args.method_files or discover_method_files(source_dir, set(args.skip_files))

    with tempfile.TemporaryDirectory(prefix="blend_cutter_") as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        cutter_tag = args.cutter_prefix if not args.cutter_objects else "_".join(args.cutter_objects)
        cutter_path = temp_dir / f"{source_dir.name}_{cutter_tag}.ply"
        cutter_dir = temp_dir / "cutters"

        export_cmd = [
            str(blender_exe),
            "-b",
            "-P",
            str((repo_root / "export_named_object_from_blend.py").resolve()),
            "--",
            "--blend",
            str(blend_path),
            "--output",
            str(cutter_path),
            "--split-output-dir",
            str(cutter_dir),
        ]
        if args.cutter_objects:
            export_cmd.extend(["--objects", *args.cutter_objects])
        else:
            export_cmd.extend(["--name-prefix", str(args.cutter_prefix)])
        run(export_cmd, repo_root)
        cutter_paths = sorted(cutter_dir.glob("*.ply"))
        if not cutter_paths:
            raise FileNotFoundError(f"No cutter files exported under: {cutter_dir}")

        cut_cmd = [
            str(blender_exe),
            "-b",
            "-P",
            str((repo_root / "batch_cut_meshes_with_cutter.py").resolve()),
            "--",
            "--source-model-dir",
            str(source_dir),
            "--target-model-dir",
            str(target_dir),
            "--cutter",
            *[str(path) for path in cutter_paths],
            "--cut-mode",
            str(args.cut_mode),
            "--operation",
            str(args.operation),
            "--solver",
            str(args.solver),
            "--method-files",
            *method_files,
        ]
        run(cut_cmd, repo_root)

    print(f"[done] source={source_dir}")
    print(f"[done] target={target_dir}")
    print(f"[done] mode={args.cut_mode} operation={args.operation}")
    print(f"[done] methods={', '.join(method_files)}")


if __name__ == "__main__":
    main()
