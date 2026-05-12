from __future__ import annotations

from pathlib import Path
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
import os
import shutil
import subprocess
import sys


STANDARD_ITEMS = ("contour", "plastic", "nonmanifold_edges", "boundary_edges", "nonmanifold_regions")
CLOSEUP_ITEMS = ("closeup_plastic", "closeup_nonmanifold_edges", "closeup_boundary_edges")
ITEMS = STANDARD_ITEMS + CLOSEUP_ITEMS
ITEM_ALIASES = {
    "closeup_nonmanifold": "closeup_nonmanifold_edges",
    "closeup_boundary": "closeup_boundary_edges",
}
ITEM_TEMPLATE = {
    "closeup_plastic": "plastic",
    "closeup_nonmanifold_edges": "nonmanifold_edges",
    "closeup_boundary_edges": "boundary_edges",
}
DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"


def parse_args():
    p = argparse.ArgumentParser(description="Batch render portable no-shadow figures from a CSV list.")
    p.add_argument("--list", default=r"render_presets\portable_noshadow_render_list.csv")
    p.add_argument("--preset-file", default=r"render_presets\portable_noshadow_preset.json")
    p.add_argument("--dataset-map", default=r"meshes\dataset_map.json")
    p.add_argument("--meshes-root", default=r"meshes")
    p.add_argument("--output-root", default="")
    p.add_argument("--blender-exe", default=DEFAULT_BLENDER)
    p.add_argument("--sync-script", default="sync_portable_blend_layout.py")
    p.add_argument("--render-script", default="render_portable_blend_transparent.py")
    p.add_argument("--compute-script", default=r"portable_render\compute_heat_distances.py")
    p.add_argument("--portable-render-script", default=r"portable_render\render_surface_contours.py")
    p.add_argument("--resolution-x", type=int, default=0)
    p.add_argument("--resolution-y", type=int, default=0)
    p.add_argument("--ground-clearance", type=float, default=None)
    p.add_argument("--parallel-jobs", type=int, default=0)
    p.add_argument("--parallel-generate-blends", action="store_true")
    p.add_argument("--no-parallel-generate-blends", action="store_true")
    p.add_argument("--render-items", nargs="+", default=None)
    p.add_argument("--force-render-models", nargs="+", default=None)
    p.add_argument("--force-render-all", action="store_true")
    p.add_argument("--no-force-render-all", action="store_true")
    p.add_argument("--force-regenerate-blends", action="store_true")
    p.add_argument("--no-force-regenerate-blends", action="store_true")
    p.add_argument("--inherit-existing-layout-on-regenerate", action="store_true")
    p.add_argument("--no-inherit-existing-layout-on-regenerate", action="store_true")
    p.add_argument("--render-on-generate", action="store_true")
    p.add_argument("--no-render-on-generate", action="store_true")
    p.add_argument("--generate-only", action="store_true")
    p.add_argument("--skip-existing", action="store_true")
    return p.parse_args()


def load_csv(path: Path) -> list[dict]:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        lines.append(line)
    if not lines:
        return []
    return [
        {str(k).strip(): str(v).strip() for k, v in row.items() if k is not None}
        for row in csv.DictReader(lines)
    ]


def load_dataset_map(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_preset(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def norm_str(value):
    return (value or "").strip()


def preset_resolution(preset: dict, args) -> tuple[int, int]:
    resolution = preset.get("resolution", {})
    if isinstance(resolution, dict):
        preset_x = int(resolution.get("x", 1100))
        preset_y = int(resolution.get("y", 1100))
    elif isinstance(resolution, list) and len(resolution) >= 2:
        preset_x = int(resolution[0])
        preset_y = int(resolution[1])
    else:
        preset_x = 1100
        preset_y = 1100
    return args.resolution_x or preset_x, args.resolution_y or preset_y


def preset_parallel_jobs(preset: dict, args) -> int:
    if args.parallel_jobs > 0:
        return args.parallel_jobs
    value = int(preset.get("parallel_jobs", 1))
    return max(1, min(value, max(1, os.cpu_count() or 1)))


def preset_ground_clearance(preset: dict, args) -> float:
    if args.ground_clearance is not None:
        return float(args.ground_clearance)
    return float(preset.get("ground_clearance", 0.015))


def preset_force_render_all(preset: dict, args) -> bool:
    if args.force_render_all:
        return True
    if args.no_force_render_all or args.skip_existing:
        return False
    return bool(preset.get("force_render_all", True))


def split_names(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = value.replace(";", ",").split(",")
    names = []
    for item in value:
        text = str(item).strip()
        if text:
            names.append(text)
    return names


def preset_force_render_models(preset: dict, args) -> set[str]:
    values = args.force_render_models
    if values is None:
        values = preset.get("force_render_models", [])
    return {name.lower() for name in split_names(values)}


def preset_render_items(preset: dict, args) -> list[str]:
    value = args.render_items
    if value is None:
        value = preset.get("render_items", list(ITEMS))
    return normalize_render_items(value)


def canonical_item_name(item: str) -> str:
    return ITEM_ALIASES.get(item, item)


def normalize_render_items(value) -> list[str]:
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if value == ["all"] or value == ["*"]:
        return list(ITEMS)

    items = [canonical_item_name(str(item).strip()) for item in value if str(item).strip()]
    unknown = [item for item in items if item not in ITEMS]
    if unknown:
        raise ValueError(f"Unknown render item(s): {', '.join(unknown)}. Valid items: {', '.join(ITEMS)}")
    deduped = []
    seen = set()
    for item in items:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def dataset_render_items(preset: dict, dataset: str, default_items: list[str], args) -> list[str]:
    if args.render_items is not None:
        return default_items
    cfg = dataset_config(preset, dataset)
    if "render_items" not in cfg:
        return default_items
    return normalize_render_items(cfg.get("render_items"))


def preset_force_regenerate_blends(preset: dict, args) -> bool:
    if args.force_regenerate_blends:
        return True
    if args.no_force_regenerate_blends:
        return False
    return bool(preset.get("force_regenerate_blends", False))


def preset_parallel_generate_blends(preset: dict, args) -> bool:
    if args.parallel_generate_blends:
        return True
    if args.no_parallel_generate_blends:
        return False
    return bool(preset.get("parallel_generate_blends", False))


def preset_render_on_generate(preset: dict, args) -> bool:
    if args.render_on_generate:
        return True
    if args.no_render_on_generate:
        return False
    return bool(preset.get("render_on_generate", False))


def preset_inherit_existing_layout_on_regenerate(preset: dict, args) -> bool:
    if args.inherit_existing_layout_on_regenerate:
        return True
    if args.no_inherit_existing_layout_on_regenerate:
        return False
    return bool(preset.get("inherit_existing_layout_on_regenerate", True))


def enabled_dataset_methods(preset: dict) -> dict[str, list[str]]:
    datasets = preset.get("datasets", {})
    result = {}
    if not isinstance(datasets, dict):
        return result
    for dataset, cfg in datasets.items():
        if isinstance(cfg, dict):
            if not cfg.get("enabled", True):
                continue
            methods = cfg.get("methods", [])
        elif isinstance(cfg, list):
            methods = cfg
        else:
            continue
        result[str(dataset)] = [str(method) for method in methods]
    return result


def dataset_config(preset: dict, dataset: str) -> dict:
    datasets = preset.get("datasets", {})
    cfg = datasets.get(dataset, {}) if isinstance(datasets, dict) else {}
    return cfg if isinstance(cfg, dict) else {}


def default_method_mesh_file(method: str) -> str:
    if method == "ours":
        return "ours_mls.ply"
    return f"{method}.ply"


def method_mesh_file(preset: dict, dataset: str, method: str) -> str:
    cfg = dataset_config(preset, dataset)
    mapping = cfg.get("method_mesh_files", {})
    if isinstance(mapping, dict) and method in mapping:
        return str(mapping[method])
    return default_method_mesh_file(method)


def mesh_model_name(preset: dict, dataset: str, model: str) -> str:
    cfg = dataset_config(preset, dataset)
    mapping = cfg.get("model_name_map", {})
    if isinstance(mapping, dict) and model in mapping:
        return str(mapping[model])
    return model


def dataset_mesh_dir(meshes_root: Path, dataset: str, model: str, dataset_map: dict) -> Path:
    ds = dataset_map.get(dataset, {})
    if isinstance(ds, dict) and ds.get("dir"):
        return meshes_root / str(ds["dir"]) / "models" / model
    if isinstance(ds, str):
        return meshes_root / ds / "models" / model
    return meshes_root / dataset / "models" / model


def resolve_model_roots(row: dict, repo_root: Path, output_root: Path, dataset_methods: dict[str, list[str]]) -> list[tuple[str, Path, list[str]]]:
    explicit = norm_str(row.get("output_dir"))
    if explicit:
        p = Path(explicit)
        return [("explicit", p if p.is_absolute() else (repo_root / p).resolve(), [])]

    dataset = norm_str(row.get("dataset"))
    model = norm_str(row.get("model"))
    if not model:
        raise ValueError("Each row needs a model.")
    if dataset:
        if dataset not in dataset_methods:
            return []
        methods = dataset_methods.get(dataset, [])
        return [(dataset, (output_root / dataset / model).resolve(), methods)]
    if dataset_methods:
        return [
            (dataset_name, (output_root / dataset_name / model).resolve(), methods)
            for dataset_name, methods in dataset_methods.items()
        ]
    return sorted(
        (p.parent.name, p.resolve(), [])
        for p in output_root.glob(f"*/{model}")
        if p.is_dir()
    )


def resolve_render_dirs(model_root: Path, prefix: str, methods: list[str]) -> list[Path]:
    if methods:
        return [(model_root / method).resolve() for method in methods]
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


def resolve_mesh_path(row: dict, repo_root: Path) -> Path | None:
    explicit = norm_str(row.get("mesh_path"))
    if not explicit:
        return None
    p = Path(explicit)
    return p if p.is_absolute() else (repo_root / p).resolve()


def model_matches(name: str, patterns: set[str]) -> bool:
    if not patterns:
        return False
    return name.lower() in patterns


def resolve_source_blend(output_dir: Path, prefix: str, row: dict) -> Path:
    explicit = norm_str(row.get("source_blend"))
    if explicit:
        p = Path(explicit)
        return p if p.is_absolute() else (output_dir / p).resolve()
    return (output_dir / f"{prefix}_plastic.blend").resolve()


def command_text(cmd: list[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in cmd)


def run(cmd: list[str], cwd: Path):
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {command_text(cmd)}")


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
        raise RuntimeError(f"{label} failed ({result.returncode}): {command_text(cmd)}\n{tail}")
    print(f"[done] {label}")


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
               resolution_x: int, resolution_y: int, quiet: bool = False):
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
    if quiet:
        run_quiet(cmd, repo_root, f"render {output}")
    else:
        run(cmd, repo_root)


def cleanup_blend_backups(output_dir: Path, prefix: str):
    for item in ITEMS:
        backup = output_dir / f"{prefix}_{item}.blend1"
        if backup.exists():
            backup.unlink()


def blend_path(output_dir: Path, prefix: str, item: str) -> Path:
    return output_dir / f"{prefix}_{item}.blend"


def png_path(output_dir: Path, prefix: str, item: str) -> Path:
    return output_dir / f"{prefix}_{item}.png"


def item_layout_group(item: str) -> str:
    return "closeup" if item in CLOSEUP_ITEMS else "default"


def layout_group_source_item(group: str) -> str:
    if group == "closeup":
        return "closeup_plastic"
    return "plastic"


def item_sync_source_item(preset: dict, dataset: str, item: str) -> str:
    cfg = dataset_config(preset, dataset)
    mapping = cfg.get("item_sync_sources", {})
    canonical_item = canonical_item_name(item)
    if isinstance(mapping, dict):
        configured = mapping.get(canonical_item, mapping.get(item))
        if configured:
            configured_name = canonical_item_name(str(configured).strip())
            if configured_name in ITEMS:
                return configured_name
    return layout_group_source_item(item_layout_group(canonical_item))


def dedupe_keep_order(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def requested_generate_items(output_dir: Path, prefix: str, render_items: list[str], force_standard: bool = False) -> list[str]:
    render_items = [canonical_item_name(item) for item in render_items]
    standard_needed: list[str] = []
    closeup_needed: list[str] = []

    for item in render_items:
        if item in STANDARD_ITEMS:
            if force_standard or not blend_path(output_dir, prefix, item).exists():
                standard_needed.append(item)
            continue

        if item in CLOSEUP_ITEMS:
            if not blend_path(output_dir, prefix, item).exists():
                closeup_needed.append(item)

            if item != "closeup_plastic" and not blend_path(output_dir, prefix, "closeup_plastic").exists():
                closeup_needed.append("closeup_plastic")

            template_item = ITEM_TEMPLATE[item]
            if not blend_path(output_dir, prefix, template_item).exists():
                standard_needed.append(template_item)

    if standard_needed and (force_standard or not blend_path(output_dir, prefix, "plastic").exists()):
        standard_needed = ["plastic", *standard_needed]

    return dedupe_keep_order(standard_needed + closeup_needed)


def initial_blends_exist(output_dir: Path, prefix: str, items: list[str]) -> bool:
    return all(blend_path(output_dir, prefix, item).exists() for item in items)


def layout_source_blend(
    preset: dict,
    dataset: str,
    model_root: Path,
    output_dir: Path,
    prefix: str,
    source_item: str = "plastic",
) -> Path:
    cfg = dataset_config(preset, dataset)
    source_method = norm_str(cfg.get("layout_source_method"))
    if source_method:
        candidate = model_root / source_method / f"{prefix}_{source_item}.blend"
        if candidate.exists():
            return candidate.resolve()
    return blend_path(output_dir, prefix, source_item).resolve()


def generate_initial_blends(
    repo_root: Path,
    blender_exe: Path,
    compute_script: Path,
    portable_render_script: Path,
    mesh_path: Path,
    output_dir: Path,
    prefix: str,
    resolution_x: int,
    resolution_y: int,
    ground_clearance: float,
    samples: int,
    distance_percentile: float,
    items: list[str] | None = None,
    save_only: bool = True,
    force_distances: bool = False,
    quiet: bool = False,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    requested_items = list(items or STANDARD_ITEMS)
    distance_file = output_dir / f"{prefix}_heat_distances.npz"

    needs_distances = "contour" in requested_items

    if needs_distances and (force_distances or not distance_file.exists()):
        print(f"[compute] {mesh_path} -> {distance_file}")
        cmd = [
            sys.executable,
            str(compute_script),
            "--mesh",
            str(mesh_path),
            "--output",
            str(distance_file),
        ]
        if quiet:
            run_quiet(cmd, repo_root, f"compute {distance_file}")
        else:
            run(cmd, repo_root)

    print(f"[generate] {output_dir}")
    cmd = [
        str(blender_exe),
        "-b",
        "-P",
        str(portable_render_script),
        "--",
        "--mesh",
        str(mesh_path),
        "--output",
        str(output_dir / f"{prefix}_contour.png"),
        "--plain-output",
        str(output_dir / f"{prefix}_plastic.png"),
        "--nonmanifold-output",
        str(output_dir / f"{prefix}_nonmanifold_edges.png"),
        "--boundary-output",
        str(output_dir / f"{prefix}_boundary_edges.png"),
        "--regions-output",
        str(output_dir / f"{prefix}_nonmanifold_regions.png"),
        "--blend",
        str(output_dir / f"{prefix}_contour.blend"),
        "--plain-blend",
        str(output_dir / f"{prefix}_plastic.blend"),
        "--nonmanifold-blend",
        str(output_dir / f"{prefix}_nonmanifold_edges.blend"),
        "--boundary-blend",
        str(output_dir / f"{prefix}_boundary_edges.blend"),
        "--regions-blend",
        str(output_dir / f"{prefix}_nonmanifold_regions.blend"),
        "--distance-percentile",
        str(distance_percentile),
        "--samples",
        str(samples),
        "--ground-clearance",
        str(ground_clearance),
        "--resolution-x",
        str(resolution_x),
        "--resolution-y",
        str(resolution_y),
        "--items",
        *requested_items,
    ]
    if needs_distances:
        cmd.extend([
            "--distance-file",
            str(distance_file),
        ])
    if save_only:
        cmd.append("--save-only")
    if quiet:
        run_quiet(cmd, repo_root, f"generate {output_dir}")
    else:
        run(cmd, repo_root)
    cleanup_blend_backups(output_dir, prefix)


def generate_closeup_blends(output_dir: Path, prefix: str, items: list[str]):
    output_dir.mkdir(parents=True, exist_ok=True)
    for item in items:
        if item not in CLOSEUP_ITEMS:
            continue
        target = blend_path(output_dir, prefix, item)
        if target.exists():
            continue
        template_item = ITEM_TEMPLATE[item]
        template = blend_path(output_dir, prefix, template_item)
        if not template.exists():
            raise FileNotFoundError(f"Missing template blend for {item}: {template}")
        shutil.copy2(template, target)
        print(f"[generate-closeup] {template} -> {target}")


def generate_requested_blends(
    repo_root: Path,
    blender_exe: Path,
    compute_script: Path,
    portable_render_script: Path,
    mesh_path: Path,
    output_dir: Path,
    prefix: str,
    resolution_x: int,
    resolution_y: int,
    ground_clearance: float,
    samples: int,
    distance_percentile: float,
    items: list[str] | None = None,
    save_only: bool = True,
    force_distances: bool = False,
    quiet: bool = False,
):
    requested_items = list(items or ITEMS)
    standard_items = [item for item in requested_items if item in STANDARD_ITEMS]
    closeup_items = [item for item in requested_items if item in CLOSEUP_ITEMS]

    if standard_items:
        generate_initial_blends(
            repo_root,
            blender_exe,
            compute_script,
            portable_render_script,
            mesh_path,
            output_dir,
            prefix,
            resolution_x,
            resolution_y,
            ground_clearance,
            samples,
            distance_percentile,
            standard_items,
            save_only,
            force_distances,
            quiet,
        )
    if closeup_items:
        generate_closeup_blends(output_dir, prefix, closeup_items)


def run_parallel(jobs: list[tuple[str, object, tuple]], max_workers: int):
    if not jobs:
        return []

    if max_workers <= 1 or len(jobs) == 1:
        results = []
        for _label, fn, args in jobs:
            results.append(fn(*args))
        return results

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(fn, *args): label
            for label, fn, args in jobs
        }
        for future in as_completed(futures):
            label = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                raise RuntimeError(f"Parallel job failed: {label}") from exc
    return results


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    blender_exe = Path(args.blender_exe)
    if not blender_exe.is_absolute():
        blender_exe = (repo_root / blender_exe).resolve()
    list_path = (repo_root / args.list).resolve()
    preset_path = (repo_root / args.preset_file).resolve()
    dataset_map_path = (repo_root / args.dataset_map).resolve()
    meshes_root = (repo_root / args.meshes_root).resolve()
    sync_script = (repo_root / args.sync_script).resolve()
    render_script = (repo_root / args.render_script).resolve()
    compute_script = (repo_root / args.compute_script).resolve()
    portable_render_script = (repo_root / args.portable_render_script).resolve()

    if not blender_exe.exists():
        raise FileNotFoundError(f"Blender not found: {blender_exe}")
    if not list_path.exists():
        raise FileNotFoundError(f"List not found: {list_path}")
    if not sync_script.exists():
        raise FileNotFoundError(f"Sync script not found: {sync_script}")
    if not render_script.exists():
        raise FileNotFoundError(f"Render script not found: {render_script}")
    if not compute_script.exists():
        raise FileNotFoundError(f"Compute script not found: {compute_script}")
    if not portable_render_script.exists():
        raise FileNotFoundError(f"Portable render script not found: {portable_render_script}")

    preset = load_preset(preset_path)
    output_root_arg = args.output_root or preset.get("output_root", "renders")
    output_root = (repo_root / output_root_arg).resolve()
    resolution_x, resolution_y = preset_resolution(preset, args)
    ground_clearance = preset_ground_clearance(preset, args)
    parallel_jobs = preset_parallel_jobs(preset, args)
    samples = int(preset.get("samples", 96))
    distance_percentile = float(preset.get("distance_percentile", 100))
    auto_generate = bool(preset.get("auto_generate_blends", True))
    parallel_generate = preset_parallel_generate_blends(preset, args)
    force_regenerate_blends = preset_force_regenerate_blends(preset, args)
    inherit_existing_layout_on_regenerate = preset_inherit_existing_layout_on_regenerate(preset, args)
    force_render_all = preset_force_render_all(preset, args)
    force_render_models = preset_force_render_models(preset, args)
    restrict_to_force_render_models = args.force_render_models is not None and bool(force_render_models)
    render_on_generate = preset_render_on_generate(preset, args)
    render_items = preset_render_items(preset, args)
    dataset_methods = enabled_dataset_methods(preset)
    dataset_map = load_dataset_map(dataset_map_path)
    rows = load_csv(list_path)
    output_root.mkdir(parents=True, exist_ok=True)

    print(
        f"[config] jobs={parallel_jobs}, force_render_all={force_render_all}, "
        f"force_regenerate_blends={force_regenerate_blends}, "
        f"parallel_generate_blends={parallel_generate}, "
        f"ground_clearance={ground_clearance}, "
        f"inherit_existing_layout_on_regenerate={inherit_existing_layout_on_regenerate}, "
        f"render_on_generate={render_on_generate}, "
        f"generate_only={args.generate_only}, "
        f"render_items={','.join(render_items)}, "
        f"force_render_models={','.join(sorted(force_render_models)) or '-'}"
    )

    units = []
    for row in rows:
        dataset = norm_str(row.get("dataset"))
        model = norm_str(row.get("model"))
        prefix = resolve_prefix(row)
        forced_model = model_matches(model, force_render_models) or model_matches(prefix, force_render_models)
        if restrict_to_force_render_models and not forced_model:
            continue

        model_roots = resolve_model_roots(row, repo_root, output_root, dataset_methods)
        if not model_roots:
            print(f"[skip] no render model root found for: {model}")
            continue

        for dataset_name, model_root, methods in model_roots:
            render_dirs = resolve_render_dirs(model_root, prefix, methods)
            if not render_dirs:
                print(f"[skip] no method folders with {prefix}_plastic.blend under: {model_root}")
                continue

            for output_dir in render_dirs:
                units.append(
                    {
                        "row_dataset": dataset,
                        "dataset_name": dataset_name,
                        "model": model,
                        "model_root": model_root,
                        "output_dir": output_dir,
                        "method": output_dir.name,
                        "prefix": prefix,
                        "mesh_path_override": resolve_mesh_path(row, repo_root),
                        "force_render": forced_model,
                        "render_items": dataset_render_items(preset, dataset_name, render_items, args),
                        "layout_source_overrides": {},
                        "regenerated_from_existing_layout": False,
                        "skip": "",
                    }
                )

    if not units:
        print("[skip] no render units found")
        return

    generated_dirs = set()
    generate_jobs = []
    temporary_layout_backups = []
    for unit in units:
        output_dir = unit["output_dir"]
        prefix = unit["prefix"]
        if not (auto_generate or force_regenerate_blends):
            continue
        generate_items = requested_generate_items(output_dir, prefix, unit["render_items"], force_regenerate_blends)
        needs_generation = bool(generate_items) and (
            force_regenerate_blends or not initial_blends_exist(output_dir, prefix, generate_items)
        )
        if not needs_generation:
            continue

        if force_regenerate_blends and inherit_existing_layout_on_regenerate:
            source_items = dedupe_keep_order(
                [item_sync_source_item(preset, unit["dataset_name"], item) for item in unit["render_items"]]
            )
            for source_item in source_items:
                old_source_blend = layout_source_blend(
                    preset,
                    unit["dataset_name"],
                    unit["model_root"],
                    output_dir,
                    prefix,
                    source_item=source_item,
                )
                if not old_source_blend.exists():
                    continue
                backup = output_dir / f".{prefix}_{unit['method']}_{source_item}_layout_before_regen.blend"
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old_source_blend, backup)
                unit["layout_source_overrides"][source_item] = backup.resolve()
                unit["regenerated_from_existing_layout"] = True
                temporary_layout_backups.append(backup.resolve())
                print(f"[layout-backup] {old_source_blend} -> {backup}")

        mesh_path = unit.get("mesh_path_override")
        if mesh_path is None:
            mesh_model = mesh_model_name(preset, unit["dataset_name"], unit["model"])
            mesh_dir = dataset_mesh_dir(meshes_root, unit["dataset_name"], mesh_model, dataset_map)
            mesh_path = mesh_dir / method_mesh_file(preset, unit["dataset_name"], unit["method"])
        if not mesh_path.exists():
            unit["skip"] = f"missing mesh: {mesh_path}"
            print(f"[skip] missing mesh for {unit['dataset_name']}/{unit['model']}/{unit['method']}: {mesh_path}")
            continue

        generate_jobs.append(
            (
                f"generate {unit['dataset_name']}/{unit['model']}/{unit['method']}",
                generate_requested_blends,
                (
                    repo_root,
                    blender_exe,
                    compute_script,
                    portable_render_script,
                    mesh_path,
                    output_dir,
                    prefix,
                    resolution_x,
                    resolution_y,
                    ground_clearance,
                    samples,
                    distance_percentile,
                    generate_items,
                    True,
                    force_regenerate_blends,
                    parallel_generate and parallel_jobs > 1,
                ),
            )
        )

    if generate_jobs:
        generate_workers = parallel_jobs if parallel_generate else 1
        print(f"[generate-phase] jobs={len(generate_jobs)}, workers={generate_workers}")
        run_parallel(generate_jobs, generate_workers)
        for _label, _fn, args_tuple in generate_jobs:
            generated_dirs.add(str(args_tuple[5]))

    render_jobs = []
    for unit in units:
        if unit["skip"]:
            continue

        output_dir = unit["output_dir"]
        prefix = unit["prefix"]
        sync_sources: dict[str, list[Path]] = {}
        for item in ITEMS:
            target = blend_path(output_dir, prefix, item)
            if not target.exists():
                continue
            source_item = item_sync_source_item(preset, unit["dataset_name"], item)
            sync_sources.setdefault(source_item, []).append(target)

        if not sync_sources:
            print(f"[skip] no blend targets under: {output_dir}")
            continue

        for source_item, sync_targets in sync_sources.items():
            override = unit["layout_source_overrides"].get(source_item)
            if override is not None:
                source_blend = override
            else:
                source_blend = layout_source_blend(
                    preset,
                    unit["dataset_name"],
                    unit["model_root"],
                    output_dir,
                    prefix,
                    source_item=source_item,
                )
            if not source_blend.exists():
                print(f"[skip] missing source blend: {source_blend}")
                continue
            sync_targets = [target for target in sync_targets if target.resolve() != source_blend.resolve()]
            if sync_targets:
                sync_layout(repo_root, blender_exe, sync_script, source_blend, sync_targets)
        cleanup_blend_backups(output_dir, prefix)

        generated_this_run = str(output_dir) in generated_dirs
        if args.generate_only:
            print(f"[generate-only] skip render phase: {output_dir}")
            continue
        if generated_this_run and not render_on_generate and not unit["regenerated_from_existing_layout"]:
            print(f"[hold] generated this run, waiting for manual edit: {output_dir}")
            continue

        queued = 0
        for item in unit["render_items"]:
            blend = blend_path(output_dir, prefix, item)
            png = png_path(output_dir, prefix, item)
            if not blend.exists():
                print(f"[skip] missing blend: {blend}")
                continue
            if not force_render_all and not unit["force_render"] and png.exists() and not generated_this_run:
                print(f"[skip-existing] {png}")
                continue
            render_jobs.append(
                (
                    f"render {unit['dataset_name']}/{unit['model']}/{unit['method']}/{item}",
                    render_one,
                    (
                        repo_root,
                        blender_exe,
                        render_script,
                        blend,
                        png,
                        resolution_x,
                        resolution_y,
                        parallel_jobs > 1,
                    ),
                )
            )
            queued += 1

        print(
            f"[queued] {unit['row_dataset'] or unit['dataset_name'] or '*'} / "
            f"{unit['model']} / {unit['method']} -> {queued} render(s)"
        )

    if render_jobs:
        print(f"[render-phase] jobs={len(render_jobs)}, workers={parallel_jobs}")
        run_parallel(render_jobs, parallel_jobs)
        for unit in units:
            if not unit["skip"]:
                cleanup_blend_backups(unit["output_dir"], unit["prefix"])
    else:
        print("[skip] no render jobs queued")

    for backup in temporary_layout_backups:
        if backup.exists():
            backup.unlink()


if __name__ == "__main__":
    main()
