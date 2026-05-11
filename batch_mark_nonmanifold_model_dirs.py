from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


POINTCLOUD_NAME = "gt_pointcloud.ply"
META_NAME = "meta.json"
MARK_SUFFIX = "_red_nonmanifold_mark"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create sibling model folders containing non-manifold red-mark mesh outputs."
    )
    parser.add_argument("--models-root", required=True, help="Directory containing model subfolders.")
    parser.add_argument(
        "--models",
        nargs="+",
        required=True,
        help="Model folder names to process.",
    )
    parser.add_argument(
        "--marker-script",
        default="mark_nonmanifold_red.py",
        help="Path to the mesh marker script.",
    )
    parser.add_argument(
        "--copy-meta",
        action="store_true",
        help="Also copy meta.json into each output folder.",
    )
    return parser.parse_args()


def is_marked_mesh(path: Path) -> bool:
    return path.suffix.lower() == ".ply" and path.stem.endswith(MARK_SUFFIX)


def is_pointcloud(path: Path) -> bool:
    return path.name == POINTCLOUD_NAME


def output_model_dir(source_dir: Path) -> Path:
    return source_dir.with_name(f"{source_dir.name}{MARK_SUFFIX}")


def process_model(source_dir: Path, marker_script: Path, copy_meta: bool):
    if not source_dir.exists():
        raise FileNotFoundError(f"Model folder not found: {source_dir}")

    target_dir = output_model_dir(source_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    pointcloud_src = source_dir / POINTCLOUD_NAME
    if pointcloud_src.exists():
        shutil.copy2(pointcloud_src, target_dir / POINTCLOUD_NAME)

    meta_src = source_dir / META_NAME
    if copy_meta and meta_src.exists():
        shutil.copy2(meta_src, target_dir / META_NAME)

    mesh_files = []
    for path in sorted(source_dir.glob("*.ply")):
        if is_pointcloud(path) or is_marked_mesh(path):
            continue
        mesh_files.append(path)

    for mesh_path in mesh_files:
        output_path = target_dir / mesh_path.name
        cmd = [sys.executable, str(marker_script), "--mesh", str(mesh_path), "--output", str(output_path)]
        subprocess.run(cmd, check=True)

    print(f"[done] {source_dir.name} -> {target_dir}")
    print(f"       pointcloud={'yes' if pointcloud_src.exists() else 'no'} mesh_count={len(mesh_files)}")


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    models_root = Path(args.models_root).resolve()
    marker_script = Path(args.marker_script)
    if not marker_script.is_absolute():
        marker_script = (repo_root / marker_script).resolve()
    if not marker_script.exists():
        raise FileNotFoundError(f"Marker script not found: {marker_script}")

    for model_name in args.models:
        source_dir = models_root / model_name
        process_model(source_dir, marker_script, copy_meta=args.copy_meta)


if __name__ == "__main__":
    main()
