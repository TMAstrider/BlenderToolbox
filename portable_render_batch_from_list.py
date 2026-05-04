from __future__ import annotations

from pathlib import Path
import argparse
import csv
import json
import subprocess


ITEMS = ("contour", "plastic", "nonmanifold_edges", "nonmanifold_regions")
DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"


def parse_args():
    p = argparse.ArgumentParser(description="Batch render portable no-shadow figures from a CSV list.")
    p.add_argument("--list", default=r"render_presets\portable_noshadow_render_list.csv")
    p.add_argument("--dataset-map", default=r"meshes\dataset_map.json")
    p.add_argument("--output-root", default=r"renders")
    p.add_argument("--blender-exe", default=DEFAULT_BLENDER)
    p.add_argument("--sync-script", default="sync_portable_blend_layout.py")
    p.add_argument("--render-script", default="render_portable_blend_transparent.py")
    p.add_argument("--resolution-x", type=int, default=1100)
    p.add_argument("--resolution-y", type=int, default=1100)
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--skip-rendered-done", action="store_true")
    return p.parse_args()


def load_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_dataset_map(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def norm_str(value):
    return (value or "").strip()


def resolve_model_roots(row: dict, repo_root: Path, output_root: Path) -> list[Path]:
    explicit = norm_str(row.get("output_dir"))
    if explicit:
        p = Path(explicit)
        return [p if p.is_absolute() else (repo_root / p).resolve()]

    dataset = norm_str(row.get("dataset"))
    model = norm_str(row.get("model"))
    if not model:
        raise ValueError("Each row needs a model.")
    if dataset:
        return [(output_root / dataset / model).resolve()]
    return sorted(p.resolve() for p in output_root.glob(f"*/{model}") if p.is_dir())


def resolve_render_dirs(model_root: Path, prefix: str) -> list[Path]:
    if not model_root.exists():
        return []
    if (model_root / f"{prefix}_plastic.blend").exists():
        return [model_root]
    return sorted(
        p.resolve()
        for p in model_root.iterdir()
        if p.is_dir() and (p / f"{prefix}_plastic.blend").exists()
    )


def resolve_prefix(row: dict) -> str:
    prefix = norm_str(row.get("prefix"))
    if prefix:
        return prefix
    model = norm_str(row.get("model"))
    if model:
        return model
    raise ValueError("Each row needs prefix or model.")


def resolve_source_blend(output_dir: Path, prefix: str, row: dict) -> Path:
    explicit = norm_str(row.get("source_blend"))
    if explicit:
        p = Path(explicit)
        return p if p.is_absolute() else (output_dir / p).resolve()
    return (output_dir / f"{prefix}_plastic.blend").resolve()


def run(cmd: list[str], cwd: Path):
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def sync_layout(repo_root: Path, blender_exe: Path, sync_script: Path, source_blend: Path, targets: list[Path]):
    cmd = [
        str(blender_exe),
        "-b",
        "-P",
        str(sync_script),
        "--",
        "--source",
        str(source_blend),
        "--targets",
        *[str(p) for p in targets],
    ]
    run(cmd, repo_root)


def render_one(repo_root: Path, blender_exe: Path, render_script: Path, blend: Path, output: Path,
               resolution_x: int, resolution_y: int):
    cmd = [
        str(blender_exe),
        "-b",
        "-P",
        str(render_script),
        "--",
        "--blend",
        str(blend),
        "--output",
        str(output),
        "--hide-ground",
        "--resolution-x",
        str(resolution_x),
        "--resolution-y",
        str(resolution_y),
        "--save-blend",
        str(blend),
    ]
    run(cmd, repo_root)


def cleanup_blend_backups(output_dir: Path, prefix: str):
    for item in ITEMS:
        backup = output_dir / f"{prefix}_{item}.blend1"
        if backup.exists():
            backup.unlink()


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    blender_exe = Path(args.blender_exe)
    if not blender_exe.is_absolute():
        blender_exe = (repo_root / blender_exe).resolve()
    list_path = (repo_root / args.list).resolve()
    dataset_map_path = (repo_root / args.dataset_map).resolve()
    output_root = (repo_root / args.output_root).resolve()
    sync_script = (repo_root / args.sync_script).resolve()
    render_script = (repo_root / args.render_script).resolve()

    if not blender_exe.exists():
        raise FileNotFoundError(f"Blender not found: {blender_exe}")
    if not list_path.exists():
        raise FileNotFoundError(f"List not found: {list_path}")
    if not sync_script.exists():
        raise FileNotFoundError(f"Sync script not found: {sync_script}")
    if not render_script.exists():
        raise FileNotFoundError(f"Render script not found: {render_script}")

    dataset_map = load_dataset_map(dataset_map_path)
    rows = load_csv(list_path)
    output_root.mkdir(parents=True, exist_ok=True)

    for row in rows:
        dataset = norm_str(row.get("dataset"))
        model = norm_str(row.get("model"))
        rendered = norm_str(row.get("rendered")).lower()
        if rendered == "done" and args.skip_rendered_done:
            continue

        prefix = resolve_prefix(row)
        model_roots = resolve_model_roots(row, repo_root, output_root)
        if not model_roots:
            print(f"[skip] no render model root found for: {model}")
            continue

        rendered_any = False
        for model_root in model_roots:
            render_dirs = resolve_render_dirs(model_root, prefix)
            if not render_dirs:
                print(f"[skip] no method folders with {prefix}_plastic.blend under: {model_root}")
                continue

            for output_dir in render_dirs:
                source_blend = resolve_source_blend(output_dir, prefix, row)
                if not source_blend.exists():
                    print(f"[skip] missing source blend: {source_blend}")
                    continue

                sync_targets = [
                    output_dir / f"{prefix}_contour.blend",
                    output_dir / f"{prefix}_nonmanifold_edges.blend",
                    output_dir / f"{prefix}_nonmanifold_regions.blend",
                ]
                sync_layout(repo_root, blender_exe, sync_script, source_blend, sync_targets)
                cleanup_blend_backups(output_dir, prefix)

                for item in ITEMS:
                    blend = output_dir / f"{prefix}_{item}.blend"
                    png = output_dir / f"{prefix}_{item}.png"
                    if args.skip_existing and png.exists():
                        continue
                    render_one(repo_root, blender_exe, render_script, blend, png, args.resolution_x, args.resolution_y)

                cleanup_blend_backups(output_dir, prefix)
                rendered_any = True
                print(f"[done] {dataset or '*'} / {model} -> {output_dir}")

        if not rendered_any:
            print(f"[skip] no renderable method directory for: {model}")


if __name__ == "__main__":
    main()
