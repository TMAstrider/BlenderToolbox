"""
render_from_list.py

Read render_list.csv and process models in two phases:

  Phase 1 — Generate .blend:  for rows where blend=todo, run make_adjust_scene.py
  Phase 2 — Render:           for rows where blend=done, launch parallel Blender renders.

Models with rendered=done are skipped.
Models with clean=yes use ours_mls_clean.ply instead of ours_mls.ply.
Strip images are built per-dataset using the strip_order from dataset_map.json.

Usage:
    python render_from_list.py \
        --list        meshes/render_list.csv \
        --meshes-root meshes \
        --output-root renders \
        --adjust-root adjust_scenes \
        --preset-file render_presets/cycles_flat_ao_strip.json \
        [--max-parallel 2]
"""

import argparse
import csv
import json
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from PIL import Image

from render_eval_batch import append_flag, load_preset


BLENDER_EXE = r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--list",         default=r"meshes\render_list.csv")
    p.add_argument("--meshes-root",  required=True,
                   help="Base meshes/ directory (resolved via dataset_map.json)")
    p.add_argument("--dataset-map",  default=r"meshes\dataset_map.json")
    p.add_argument("--adjust-root",  default=r"adjust_scenes")
    p.add_argument("--output-root",  required=True,
                   help="Base renders/ directory (output goes to <output-root>/<dataset_output_subdir>/<model>)")
    p.add_argument("--preset-file",  default=r"render_presets\cycles_flat_ao_strip.json")
    p.add_argument("--blender-exe",  default=BLENDER_EXE)
    p.add_argument("--render-script",  default="render_eval_set.py")
    p.add_argument("--export-script",  default="export_selected_transform.py")
    p.add_argument("--make-script",    default="make_adjust_scene.py")
    p.add_argument("--max-parallel", type=int, default=2)
    return p.parse_args()


def find_adjust_blend(adjust_root: Path, dataset: str, model: str) -> Path | None:
    search_dir = adjust_root / dataset / model
    if not search_dir.exists():
        candidates = list(adjust_root.glob(f"{dataset}/*{model.replace('__', '_')}*"))
        if candidates:
            search_dir = candidates[0]
    blends = [p for p in search_dir.glob("*.blend") if not p.suffix == ".blend1"] if search_dir.exists() else []
    return blends[0] if blends else None


def resolve_model_dir(meshes_root: Path, dataset: str, model: str, dataset_map: dict | None) -> Path | None:
    if dataset_map and dataset in dataset_map:
        ds = dataset_map[dataset]
        ds_dir = ds["dir"] if isinstance(ds, dict) else ds
        return meshes_root / ds_dir / "models" / model
    return meshes_root / model


def get_dataset_output_subdir(dataset_map: dict | None, dataset: str) -> str:
    if dataset_map and dataset in dataset_map:
        ds = dataset_map[dataset]
        if isinstance(ds, dict):
            return ds.get("output_subdir", dataset)
    return dataset


def extract_adjust_data(repo_root: Path, blender_exe: Path, export_script: Path,
                        adjust_blend: Path, json_out: Path) -> dict:
    cmd = [str(blender_exe), str(adjust_blend), "-b", "-P", str(export_script),
           "--", "--json-out", str(json_out)]
    result = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"export_selected_transform failed:\n{result.stderr}")
    return json.loads(json_out.read_text(encoding="utf-8"))


def merge_args(render_args: dict, adjust_data: dict) -> dict:
    merged = dict(render_args)
    mesh = adjust_data.get("mesh", {})
    if mesh:
        merged["location"] = mesh["location"]
        merged["rotation"] = mesh["rotation"]
        merged["scale"]    = mesh["scale"]
    camera = adjust_data.get("camera", {})
    if camera:
        merged["camera_location"]     = camera["location"]
        merged["camera_rotation"]     = [round(v, 4) for v in camera["rotation"]]
        merged["camera_focal_length"] = camera["focal_length"]
    return merged


def build_render_cmd(blender_exe: Path, render_script: Path,
                     model_dir: Path, output_dir: Path, render_args: dict) -> list[str]:
    cmd = [str(blender_exe), "-b", "-P", str(render_script),
           "--", "--model-dir", str(model_dir), "--output-dir", str(output_dir)]
    for key, value in render_args.items():
        append_flag(cmd, key, value)
    return cmd


def create_strip_for_model(output_dir: Path, dataset_map: dict | None, dataset: str):
    """Build a horizontal strip from available method PNGs, per dataset strip_order."""
    order = None
    labels = {}
    if dataset_map and dataset in dataset_map:
        ds = dataset_map[dataset]
        if isinstance(ds, dict):
            order = ds.get("strip_order")
            labels = ds.get("strip_labels", {})
    if not order:
        return

    # scan available PNGs
    available = []
    for method in order:
        png = output_dir / f"{method}.png"
        if png.exists():
            label = labels.get(method, method)
            available.append((png, label))

    if len(available) < 2:
        return

    # load and clean alpha
    images = []
    for path, _label in available:
        img = Image.open(path).convert("RGBA")
        a = np.array(img)
        a[a[:, :, 3] == 0] = [0, 0, 0, 0]
        images.append(Image.fromarray(a))

    margin = 24
    img_w, img_h = images[0].size
    canvas_w = len(images) * img_w + (len(images) - 1) * margin
    canvas = Image.new("RGBA", (canvas_w, img_h), (0, 0, 0, 0))

    for i, img in enumerate(images):
        x = i * (img_w + margin)
        canvas.alpha_composite(img, dest=(x, 0))

    out_path = output_dir / "strip_1x4.png"
    canvas.save(out_path)
    print(f"  [strip] {len(images)}-col -> {out_path}")


def render_model(row: dict, repo_root: Path, blender_exe: Path, render_script: Path,
                 export_script: Path, meshes_root: Path, adjust_root: Path,
                 output_base: Path, render_args: dict,
                 dataset_map: dict | None = None) -> str:
    model   = row["model"]
    dataset = row["dataset"]
    clean   = (row.get("clean") or "no").strip().lower() == "yes"

    model_dir  = resolve_model_dir(meshes_root, dataset, model, dataset_map)
    if model_dir is None or not model_dir.exists():
        return f"[WARN] {model}: model dir not found"

    subdir = get_dataset_output_subdir(dataset_map, dataset)
    output_dir = output_base / subdir / model
    output_dir.mkdir(parents=True, exist_ok=True)

    if clean:
        clean_ply = model_dir / "ours_mls_clean.ply"
        if not clean_ply.exists():
            return f"[WARN] {model}: clean=yes but ours_mls_clean.ply not found, skipping"
        staging = output_dir / "_staging"
        staging.mkdir(exist_ok=True)
        import shutil
        for ply in model_dir.glob("*.ply"):
            if ply.name == "ours_mls_clean.ply":
                continue
            dst = staging / ply.name
            if not dst.exists():
                shutil.copy2(ply, dst)
        shutil.copy2(clean_ply, staging / "ours_mls.ply")
        effective_model_dir = staging
    else:
        effective_model_dir = model_dir

    adjust_blend = find_adjust_blend(adjust_root, dataset, model)
    if adjust_blend is None:
        return f"[WARN] {model}: no adjust .blend found in {adjust_root / dataset / model}"

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        json_out = Path(tf.name)
    try:
        adjust_data = extract_adjust_data(repo_root, blender_exe, export_script, adjust_blend, json_out)
    except RuntimeError as e:
        return f"[ERROR] {model}: {e}"
    finally:
        json_out.unlink(missing_ok=True)

    merged = merge_args(render_args, adjust_data)
    (output_dir / "run_summary.json").write_text(
        json.dumps({"model": model, "dataset": dataset, "adjust_blend": str(adjust_blend),
                    "final_render_args": merged}, indent=2, ensure_ascii=False),
        encoding="utf-8")

    cmd = build_render_cmd(blender_exe, render_script, effective_model_dir, output_dir, merged)
    result = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    if result.returncode != 0:
        return f"[ERROR] {model}: blender exited {result.returncode}\n{result.stderr[-2000:]}"

    create_strip_for_model(output_dir, dataset_map, dataset)
    return f"[done]  {model}"


def make_blend(row: dict, repo_root: Path, blender_exe: Path, make_script: Path,
               meshes_root: Path, adjust_root: Path, render_args: dict,
               dataset_map: dict | None = None) -> str:
    model   = row["model"]
    dataset = row["dataset"]
    clean   = (row.get("clean") or "no").strip().lower() == "yes"

    model_dir = resolve_model_dir(meshes_root, dataset, model, dataset_map)
    if model_dir is None or not model_dir.exists():
        return f"[WARN] {model}: model dir not found ({dataset=})"
    ply = model_dir / ("ours_mls_clean.ply" if clean else "ours_mls.ply")
    if not ply.exists():
        return f"[WARN] {model}: mesh not found ({ply})"

    blend_out = adjust_root / dataset / model / f"{model}_ours_mls_{render_args.get('material','flat_ao')}.blend"
    blend_out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(blender_exe), "-b", "-P", str(make_script), "--",
        "--mesh-path",   str(ply),
        "--blend-out",   str(blend_out),
        "--resolution",  str(render_args.get("resolution", 1024)),
        "--samples",     str(render_args.get("samples", 128)),
        "--material",    render_args.get("material", "flat_ao"),
        "--mesh-rgb",    *[str(v) for v in render_args.get("mesh_rgb", [0.95, 0.95, 0.95])],
        "--location",    *[str(v) for v in render_args.get("location", [0.0, 0.0, -0.12])],
        "--rotation",    *[str(v) for v in render_args.get("rotation", [90.0, 0.0, 225.0])],
        "--scale",       *[str(v) for v in render_args.get("scale", [2.3, 2.3, 2.3])],
        "--recalc-normals",
    ]
    result = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    if result.returncode != 0:
        return f"[ERROR] {model}: make_adjust_scene failed\n{result.stderr[-1000:]}"
    return f"[blend] {model} -> {blend_out}"


def create_ranked_strip(all_rows: list[dict], output_base: Path, dataset_map: dict | None):
    """Stack individual strip images vertically in rank order, per dataset."""
    from collections import defaultdict
    groups = defaultdict(list)
    for r in all_rows:
        rank_str = (r.get("rank") or "").strip()
        if not rank_str or rank_str == "-1":
            continue
        try:
            rank = int(rank_str)
        except ValueError:
            continue
        dataset = r["dataset"]
        model   = r["model"]
        subdir  = get_dataset_output_subdir(dataset_map, dataset)
        strip_path = output_base / subdir / model / "strip_1x4.png"
        if strip_path.exists():
            groups[dataset].append((rank, strip_path))

    for dataset, items in groups.items():
        items.sort(key=lambda x: x[0])
        images = [Image.open(p).convert("RGBA") for _, p in items]
        w = max(img.width for img in images)
        total_h = sum(img.height for img in images)
        canvas = Image.new("RGBA", (w, total_h), (0, 0, 0, 0))
        y = 0
        for img in images:
            x = (w - img.width) // 2
            canvas.alpha_composite(img, dest=(x, y))
            y += img.height

        subdir = get_dataset_output_subdir(dataset_map, dataset)
        out_path = output_base / subdir / "ranked_strip.png"
        canvas.save(out_path)
        print(f"Ranked strip [{dataset}] ({len(images)} models) saved: {out_path}")


def main():
    args = parse_args()
    repo_root       = Path.cwd()
    blender_exe     = Path(args.blender_exe)
    render_script   = (repo_root / args.render_script).resolve()
    export_script   = (repo_root / args.export_script).resolve()
    make_script     = (repo_root / args.make_script).resolve()
    meshes_root     = (repo_root / args.meshes_root).resolve()
    adjust_root     = (repo_root / args.adjust_root).resolve()
    output_base     = (repo_root / args.output_root).resolve()
    preset_file     = (repo_root / args.preset_file).resolve()
    list_file       = (repo_root / args.list).resolve()
    dataset_map_path = (repo_root / args.dataset_map).resolve()

    dataset_map = None
    if dataset_map_path.exists():
        dataset_map = json.loads(dataset_map_path.read_text(encoding="utf-8"))
        print(f"Loaded dataset map: {list(dataset_map.keys())}")

    render_args, _ = load_preset(preset_file)
    output_base.mkdir(parents=True, exist_ok=True)

    with list_file.open(encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    # skip rendered=done
    todo_rows = [r for r in all_rows if (r.get("rendered") or "").strip().lower() != "done"]
    if not todo_rows:
        print("All models rendered — nothing to do.")
        create_ranked_strip(all_rows, output_base, dataset_map)
        return

    # Phase 1: generate .blend for blend=todo
    blend_todo = [r for r in todo_rows if (r.get("blend") or "").strip().lower() == "todo"]
    if blend_todo:
        print(f"Generating {len(blend_todo)} blend(s)...")
        for row in blend_todo:
            result = make_blend(row, repo_root, blender_exe, make_script,
                               meshes_root, adjust_root, render_args, dataset_map)
            print(result)

    # Phase 2: render blend=done (and not already rendered)
    render_rows = [r for r in todo_rows if (r.get("blend") or "").strip().lower() == "done"]
    if not render_rows:
        print("No models with blend=done to render.")
        create_ranked_strip(all_rows, output_base, dataset_map)
        return

    print(f"Rendering {len(render_rows)} model(s) with max_parallel={args.max_parallel}")
    for r in render_rows:
        print(f"  {r['dataset']}/{r['model']}  clean={r.get('clean','no')}")

    futures = {}
    with ThreadPoolExecutor(max_workers=args.max_parallel) as ex:
        for row in render_rows:
            f = ex.submit(render_model, row, repo_root, blender_exe, render_script,
                          export_script, meshes_root, adjust_root, output_base,
                          render_args, dataset_map)
            futures[f] = row["model"]

        for f in as_completed(futures):
            print(f.result())

    create_ranked_strip(all_rows, output_base, dataset_map)


if __name__ == "__main__":
    main()
