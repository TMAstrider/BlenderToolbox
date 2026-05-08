from __future__ import annotations

from pathlib import Path
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
import os
import subprocess


DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"


def parse_args():
    p = argparse.ArgumentParser(description="Render GT point clouds using existing portable plastic blend layouts.")
    p.add_argument("--list", default=r"render_presets\portable_noshadow_render_list.csv")
    p.add_argument("--preset-file", default=r"render_presets\portable_noshadow_preset.json")
    p.add_argument("--dataset-map", default=r"meshes\dataset_map.json")
    p.add_argument("--meshes-root", default="meshes")
    p.add_argument("--output-root", default="")
    p.add_argument("--blender-exe", default=DEFAULT_BLENDER)
    p.add_argument("--render-script", default="render_pointcloud_from_layout.py")
    p.add_argument("--item", default="")
    p.add_argument("--parallel-jobs", type=int, default=0)
    p.add_argument("--force", action="store_true")
    p.add_argument("--point-size", type=float, default=None)
    p.add_argument("--point-color", nargs=3, type=float, default=None)
    return p.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_rows(path: Path) -> list[dict]:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        lines.append(line)
    rows = []
    for row in csv.DictReader(lines):
        rows.append({str(k).strip(): str(v).strip() for k, v in row.items() if k is not None})
    return rows


def norm(value) -> str:
    return (value or "").strip()


def item_from_render_items(items, fallback: str = "plastic") -> str:
    if isinstance(items, list) and items:
        return str(items[0])
    if isinstance(items, str) and items.strip():
        return items.strip()
    return fallback


def default_item(preset: dict, args) -> str:
    if args.item:
        return args.item
    return item_from_render_items(preset.get("render_items", ["plastic"]))


def dataset_item(preset: dict, dataset_cfg: dict, args) -> str:
    if args.item:
        return args.item
    if "render_items" in dataset_cfg:
        return item_from_render_items(dataset_cfg.get("render_items"))
    return default_item(preset, args)


def enabled_datasets(preset: dict) -> dict:
    datasets = preset.get("datasets", {})
    if not isinstance(datasets, dict):
        return {}
    return {
        str(name): cfg
        for name, cfg in datasets.items()
        if isinstance(cfg, dict) and cfg.get("enabled", True)
    }


def wants_gt_pointcloud(cfg: dict, item: str) -> bool:
    ranking_by_item = cfg.get("mesh_ranking_by_item")
    if isinstance(ranking_by_item, dict):
        values = ranking_by_item.get(item)
        if isinstance(values, list) and "gt_pointcloud" in [str(v) for v in values]:
            return True
    ranking = cfg.get("mesh_ranking")
    if isinstance(ranking, list) and "gt_pointcloud" in [str(v) for v in ranking]:
        return True
    methods = cfg.get("methods", [])
    return "gt_pointcloud" in [str(v) for v in methods]


def dataset_mesh_dir(meshes_root: Path, dataset: str, model: str, dataset_map: dict) -> Path:
    ds = dataset_map.get(dataset, {})
    if isinstance(ds, dict) and ds.get("dir"):
        return meshes_root / str(ds["dir"]) / "models" / model
    if isinstance(ds, str):
        return meshes_root / ds / "models" / model
    return meshes_root / dataset / "models" / model


def mesh_model_name(dataset_cfg: dict, model: str) -> str:
    mapping = dataset_cfg.get("model_name_map", {})
    if isinstance(mapping, dict) and model in mapping:
        return str(mapping[model])
    return model


def layout_source_method(cfg: dict) -> str:
    return str(cfg.get("layout_source_method") or "ours")


def pointcloud_cfg(preset: dict, dataset_cfg: dict) -> dict:
    merged = {}
    global_cfg = preset.get("pointcloud", {})
    if isinstance(global_cfg, dict):
        merged.update(global_cfg)
    dataset_pc_cfg = dataset_cfg.get("pointcloud", {})
    if isinstance(dataset_pc_cfg, dict):
        merged.update(dataset_pc_cfg)
    return merged


def point_size(preset: dict, dataset_cfg: dict, args) -> float:
    if args.point_size is not None:
        return float(args.point_size)
    cfg = pointcloud_cfg(preset, dataset_cfg)
    return float(cfg.get("point_size", 0.003))


def point_color(preset: dict, dataset_cfg: dict, args) -> tuple[float, float, float]:
    if args.point_color is not None:
        return tuple(float(v) for v in args.point_color)
    cfg = pointcloud_cfg(preset, dataset_cfg)
    color = cfg.get("color", [0.72, 0.76, 0.82])
    if not isinstance(color, list) or len(color) != 3:
        raise ValueError("pointcloud.color must be a list of three RGB values in 0..1")
    return tuple(float(v) for v in color)


def run_quiet(cmd: list[str], cwd: Path, label: str):
    result = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    if result.returncode != 0:
        tail = (result.stdout or "")[-6000:]
        raise RuntimeError(f"{label} failed ({result.returncode})\n{tail}")
    print(f"[done] {label}")


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    preset = load_json((repo_root / args.preset_file).resolve())
    dataset_map = load_json((repo_root / args.dataset_map).resolve())
    rows = load_rows((repo_root / args.list).resolve())
    output_root = (repo_root / (args.output_root or preset.get("output_root", "renders"))).resolve()
    meshes_root = (repo_root / args.meshes_root).resolve()
    blender_exe = Path(args.blender_exe)
    render_script = (repo_root / args.render_script).resolve()
    resolution = preset.get("resolution", {})
    resolution_x = int(resolution.get("x", 1100)) if isinstance(resolution, dict) else 1100
    resolution_y = int(resolution.get("y", 1100)) if isinstance(resolution, dict) else 1100
    samples = int(preset.get("samples", 96))
    parallel_jobs = args.parallel_jobs or int(preset.get("parallel_jobs", 1))
    parallel_jobs = max(1, min(parallel_jobs, os.cpu_count() or 1))

    jobs = []
    for row in rows:
        model = norm(row.get("model"))
        explicit_dataset = norm(row.get("dataset"))
        if not model:
            continue
        datasets = enabled_datasets(preset)
        dataset_items = [(explicit_dataset, datasets[explicit_dataset])] if explicit_dataset in datasets else datasets.items()
        for dataset, cfg in dataset_items:
            item = dataset_item(preset, cfg, args)
            if not wants_gt_pointcloud(cfg, item):
                continue
            pointcloud = dataset_mesh_dir(meshes_root, dataset, mesh_model_name(cfg, model), dataset_map) / "gt_pointcloud.ply"
            if not pointcloud.exists():
                continue
            source_method = layout_source_method(cfg)
            source_blend = output_root / dataset / model / source_method / f"{model}_{item}.blend"
            if not source_blend.exists():
                print(f"[skip] missing layout source: {source_blend}")
                continue
            out_dir = output_root / dataset / model / "gt_pointcloud"
            output = out_dir / f"{model}_{item}.png"
            if output.exists() and not args.force:
                print(f"[skip-existing] {output}")
                continue
            blend = out_dir / f"{model}_{item}.blend"
            pc_size = point_size(preset, cfg, args)
            pc_color = point_color(preset, cfg, args)
            cmd = [
                str(blender_exe),
                "-b",
                "-P",
                str(render_script),
                "--",
                "--source-blend",
                str(source_blend),
                "--pointcloud",
                str(pointcloud),
                "--output",
                str(output),
                "--save-blend",
                str(blend),
                "--resolution-x",
                str(resolution_x),
                "--resolution-y",
                str(resolution_y),
                "--samples",
                str(samples),
                "--point-size",
                str(pc_size),
                "--color",
                str(pc_color[0]),
                str(pc_color[1]),
                str(pc_color[2]),
            ]
            jobs.append((f"{dataset}/{model}/gt_pointcloud", cmd))

    if not jobs:
        print("[skip] no pointcloud render jobs queued")
        return

    print(f"[pointcloud-render] jobs={len(jobs)}, workers={parallel_jobs}")
    with ThreadPoolExecutor(max_workers=parallel_jobs) as executor:
        futures = {executor.submit(run_quiet, cmd, repo_root, label): label for label, cmd in jobs}
        for future in as_completed(futures):
            label = futures[future]
            try:
                future.result()
            except Exception as exc:
                raise RuntimeError(f"Pointcloud render failed: {label}") from exc


if __name__ == "__main__":
    main()
