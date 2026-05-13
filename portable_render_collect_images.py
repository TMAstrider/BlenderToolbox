from __future__ import annotations

from pathlib import Path
import argparse
import csv
from datetime import datetime
import json
import shutil

from PIL import Image


ITEM_ALIASES = {
    "closeup_nonmanifold": "closeup_nonmanifold_edges",
    "closeup_boundary": "closeup_boundary_edges",
}

METHOD_ALIASES = {
    "ours_mls": "ours",
}


def parse_args():
    p = argparse.ArgumentParser(
        description="Collect configured portable render PNGs into a mirrored images-only directory."
    )
    p.add_argument("--list", default=r"render_presets\portable_noshadow_render_list.csv")
    p.add_argument("--preset-file", default=r"render_presets\portable_noshadow_preset.json")
    p.add_argument("--source-root", default="")
    p.add_argument("--output-root", default="")
    p.add_argument("--render-items", nargs="+", default=None)
    p.add_argument("--models", nargs="+", default=None)
    p.add_argument("--include-model-strips", action="store_true")
    p.add_argument("--no-ranked-strips", action="store_true")
    p.add_argument("--crop-padding", type=int, default=0)
    return p.parse_args()


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_rows(path: Path) -> list[dict]:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        lines.append(line)
    if not lines:
        return []
    return [
        {str(k).strip(): ("" if v is None else str(v).strip()) for k, v in row.items() if k is not None}
        for row in csv.DictReader(lines)
    ]


def norm(value) -> str:
    return (value or "").strip()


def resolve_prefix(row: dict) -> str:
    prefix = norm(row.get("prefix"))
    if prefix:
        return prefix
    model = norm(row.get("model"))
    if model:
        return model
    raise ValueError("Each row needs prefix or model.")


def split_names(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = value.replace(";", ",").split(",")
    return [str(item).strip() for item in value if str(item).strip()]


def canonical_item_name(item: str) -> str:
    return ITEM_ALIASES.get(item, item)


def normalize_render_items(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    items = [canonical_item_name(str(item).strip()) for item in value if str(item).strip()]
    deduped = []
    seen = set()
    for item in items:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def configured_datasets(preset: dict) -> dict[str, dict]:
    datasets = preset.get("datasets", {})
    if not isinstance(datasets, dict):
        return {}
    return {
        str(name): cfg
        for name, cfg in datasets.items()
        if isinstance(cfg, dict)
    }


def default_item_list(preset: dict) -> list[str]:
    return normalize_render_items(preset.get("render_items", ["plastic"]))


def dataset_render_items(preset: dict, dataset_cfg: dict, args) -> list[str]:
    if args.render_items is not None:
        return normalize_render_items(args.render_items)
    if "render_items" in dataset_cfg:
        return normalize_render_items(dataset_cfg.get("render_items"))
    return default_item_list(preset)


def ranking_by_item(dataset_cfg: dict, item: str) -> list[str] | None:
    mapping = dataset_cfg.get("mesh_ranking_by_item")
    if not isinstance(mapping, dict):
        return None
    values = mapping.get(item)
    if not isinstance(values, list) or not values:
        return None
    return [str(v) for v in values]


def method_order(dataset_cfg: dict, item: str) -> list[str]:
    per_item = ranking_by_item(dataset_cfg, item)
    if per_item:
        return per_item
    ranking = dataset_cfg.get("mesh_ranking")
    if isinstance(ranking, list) and ranking:
        values = [str(v) for v in ranking]
        if values[0] == item:
            return values[1:]
        return values
    methods = dataset_cfg.get("methods", [])
    return [str(v) for v in methods]


def methods_to_collect(dataset_cfg: dict, item: str) -> list[str]:
    ordered = method_order(dataset_cfg, item)
    dataset_methods = [str(v) for v in dataset_cfg.get("methods", [])]
    result = []
    seen = set()
    for method in ordered + dataset_methods:
        if method not in seen:
            result.append(method)
            seen.add(method)
    return result


def methods_to_collect_all(dataset_cfg: dict) -> list[str]:
    result = []
    seen = set()

    def add(method: str):
        if method not in seen:
            result.append(method)
            seen.add(method)

    for method in [str(v) for v in dataset_cfg.get("methods", [])]:
        add(method)

    ranking = dataset_cfg.get("mesh_ranking")
    if isinstance(ranking, list):
        for method in ranking:
            text = str(method)
            if text:
                add(text)

    ranking_by_item_map = dataset_cfg.get("mesh_ranking_by_item")
    if isinstance(ranking_by_item_map, dict):
        for values in ranking_by_item_map.values():
            if not isinstance(values, list):
                continue
            for method in values:
                text = str(method)
                if text:
                    add(text)

    return result


def method_dir_name(method: str) -> str:
    return METHOD_ALIASES.get(method, method)


def resolve_method_png(model_root: Path, prefix: str, method: str, item: str) -> Path | None:
    method_dir = method_dir_name(method)
    base_dir = model_root / method_dir
    candidates = [base_dir / f"{prefix}_{item}.png"]
    if method_dir == "gt_pointcloud" and item != "plastic":
        candidates.append(base_dir / f"{prefix}_plastic.png")
    for path in candidates:
        if path.exists():
            return path
    return None


def discover_method_pngs(model_root: Path, prefix: str, method: str, allowed_items: set[str] | None = None) -> list[Path]:
    method_dir = model_root / method_dir_name(method)
    if not method_dir.exists():
        return []

    found = []
    for path in sorted(method_dir.glob(f"{prefix}_*.png")):
        suffix = path.stem[len(prefix) + 1 :]
        item_name = canonical_item_name(suffix)
        if allowed_items is not None and item_name not in allowed_items:
            continue
        found.append(path)
    return found


def copy_png(path: Path, source_root: Path, output_root: Path, crop_padding: int) -> Path | None:
    try:
        relative = path.resolve().relative_to(source_root.resolve())
    except ValueError:
        return None
    target = output_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(path)
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is not None:
        left, top, right, bottom = bbox
        pad = max(0, int(crop_padding))
        left = max(0, left - pad)
        top = max(0, top - pad)
        right = min(image.width, right + pad)
        bottom = min(image.height, bottom + pad)
        image = image.crop((left, top, right, bottom))
    image.save(target)
    return target


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    preset = load_json((repo_root / args.preset_file).resolve())
    rows = load_rows((repo_root / args.list).resolve())
    source_root = (repo_root / (args.source_root or preset.get("output_root", "renders"))).resolve()
    if args.output_root:
        output_root = (repo_root / args.output_root).resolve()
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_root = source_root.with_name(source_root.name + "_images_only") / timestamp

    datasets = configured_datasets(preset)
    model_filters = {name.lower() for name in split_names(args.models)}
    copied = 0
    missing = 0
    copied_targets: set[Path] = set()
    datasets_to_export: set[str] = set()

    for row in rows:
        model = norm(row.get("model"))
        if not model:
            continue
        prefix = resolve_prefix(row)
        if model_filters and model.lower() not in model_filters:
            continue

        explicit_dataset = norm(row.get("dataset"))
        if explicit_dataset in datasets:
            dataset_items = [(explicit_dataset, datasets[explicit_dataset])]
        else:
            dataset_items = list(datasets.items())

        for dataset, cfg in dataset_items:
            model_root = source_root / dataset / model
            if not model_root.exists():
                continue
            datasets_to_export.add(dataset)

            if args.render_items is None:
                for method in methods_to_collect_all(cfg):
                    for png in discover_method_pngs(model_root, prefix, method):
                        copied_path = copy_png(png, source_root, output_root, args.crop_padding)
                        if copied_path is not None and copied_path not in copied_targets:
                            copied_targets.add(copied_path)
                            copied += 1
            else:
                items = dataset_render_items(preset, cfg, args)
                allowed_items = set(items)
                for item in items:
                    for method in methods_to_collect(cfg, item):
                        png = resolve_method_png(model_root, prefix, method, item)
                        if png is None:
                            missing += 1
                            continue
                        copied_path = copy_png(png, source_root, output_root, args.crop_padding)
                        if copied_path is not None and copied_path not in copied_targets:
                            copied_targets.add(copied_path)
                            copied += 1

                    if args.include_model_strips:
                        strip = model_root / f"strip_{item}.png"
                        copied_path = None
                        if strip.exists():
                            copied_path = copy_png(strip, source_root, output_root, args.crop_padding)
                        if copied_path is not None and copied_path not in copied_targets:
                            copied_targets.add(copied_path)
                            copied += 1

    if not args.no_ranked_strips:
        for dataset in sorted(datasets_to_export):
            dataset_root = source_root / dataset
            if not dataset_root.exists():
                continue
            for ranked in sorted(dataset_root.glob("ranked_strip_*.png")):
                copied_path = copy_png(ranked, source_root, output_root, args.crop_padding)
                if copied_path is not None and copied_path not in copied_targets:
                    copied_targets.add(copied_path)
                    copied += 1

    print(f"[collect] source={source_root}")
    print(f"[collect] output={output_root}")
    print(f"[collect] copied={copied}, missing={missing}")


if __name__ == "__main__":
    main()
