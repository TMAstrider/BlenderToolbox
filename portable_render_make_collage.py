from __future__ import annotations

from pathlib import Path
import argparse
import csv
import json

from PIL import Image, ImageDraw, ImageFont


METHOD_ALIASES = {
    "ours_mls": "ours",
}


def parse_args():
    p = argparse.ArgumentParser(description="Create portable render strips and ranked collage images.")
    p.add_argument("--list", default=r"render_presets\portable_noshadow_render_list.csv")
    p.add_argument("--preset-file", default=r"render_presets\portable_noshadow_preset.json")
    p.add_argument("--output-root", default="")
    p.add_argument("--item", default="")
    p.add_argument("--margin", type=int, default=24)
    p.add_argument("--background", default="transparent", choices=["transparent", "white"])
    p.add_argument("--labels", action="store_true")
    p.add_argument("--strip-name", default="")
    p.add_argument("--ranked-name", default="")
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
    if not lines:
        return []
    rows = []
    for row in csv.DictReader(lines):
        rows.append({str(k).strip(): str(v).strip() for k, v in row.items() if k is not None})
    return rows


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


def enabled_datasets(preset: dict) -> dict:
    datasets = preset.get("datasets", {})
    if not isinstance(datasets, dict):
        return {}
    return {
        str(name): cfg
        for name, cfg in datasets.items()
        if isinstance(cfg, dict) and cfg.get("enabled", True)
    }


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


def method_dir_name(method: str) -> str:
    return METHOD_ALIASES.get(method, method)


def label_for(dataset_cfg: dict, method: str) -> str:
    labels = dataset_cfg.get("strip_labels", {})
    if isinstance(labels, dict):
        return str(labels.get(method, labels.get(method_dir_name(method), method)))
    pretty = {
        "ours": "Ours",
        "ours_mls": "Ours",
        "nsh": "NSH",
        "multipull": "MultiPull",
        "capudf": "CAP-UDF",
        "deudf_dcudf": "DCUDF",
        "gt_mesh": "GT",
        "gt_pointcloud": "GT PC",
    }
    return pretty.get(method, method)


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


def read_rank(row: dict) -> int | None:
    text = norm(row.get("rank"))
    if not text or text == "-1":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def clean_alpha(img: Image.Image) -> Image.Image:
    return img.convert("RGBA")


def canvas_color(background: str):
    return (255, 255, 255, 255) if background == "white" else (0, 0, 0, 0)


def draw_label(canvas: Image.Image, text: str, x: int, y: int):
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    pad_x, pad_y = 8, 5
    w = bbox[2] - bbox[0] + pad_x * 2
    h = bbox[3] - bbox[1] + pad_y * 2
    draw.rectangle((x, y, x + w, y + h), fill=(255, 255, 255, 220))
    draw.text((x + pad_x, y + pad_y), text, fill=(20, 20, 20, 255), font=font)


def create_strip(images: list[tuple[Path, str]], output_path: Path, margin: int, background: str, labels: bool):
    loaded = [(clean_alpha(Image.open(path)), label) for path, label in images]
    if not loaded:
        return False
    max_h = max(img.height for img, _label in loaded)
    total_w = sum(img.width for img, _label in loaded) + margin * (len(loaded) - 1)
    canvas = Image.new("RGBA", (total_w, max_h), canvas_color(background))
    x = 0
    for img, label in loaded:
        y = (max_h - img.height) // 2
        canvas.alpha_composite(img, dest=(x, y))
        if labels:
            draw_label(canvas, label, x + 12, y + 12)
        x += img.width + margin
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return True


def create_ranked(strips: list[tuple[int, Path]], output_path: Path, margin: int, background: str):
    if not strips:
        return False
    strips = sorted(strips, key=lambda item: item[0])
    images = [Image.open(path).convert("RGBA") for _rank, path in strips]
    width = max(img.width for img in images)
    height = sum(img.height for img in images) + margin * (len(images) - 1)
    canvas = Image.new("RGBA", (width, height), canvas_color(background))
    y = 0
    for img in images:
        x = (width - img.width) // 2
        canvas.alpha_composite(img, dest=(x, y))
        y += img.height + margin
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return True


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    preset_path = (repo_root / args.preset_file).resolve()
    list_path = (repo_root / args.list).resolve()
    preset = load_json(preset_path)
    rows = load_rows(list_path)
    output_root = (repo_root / (args.output_root or preset.get("output_root", "renders"))).resolve()

    datasets = enabled_datasets(preset)
    ranked_by_dataset: dict[str, list[tuple[int, Path]]] = {}

    for row in rows:
        model = norm(row.get("model"))
        if not model:
            continue
        prefix = resolve_prefix(row)
        rank = read_rank(row)
        explicit_dataset = norm(row.get("dataset"))
        dataset_items = [(explicit_dataset, datasets[explicit_dataset])] if explicit_dataset in datasets else datasets.items()

        for dataset, cfg in dataset_items:
            item = dataset_item(preset, cfg, args)
            strip_name = args.strip_name or f"strip_{item}.png"
            model_root = output_root / dataset / model
            if not model_root.exists():
                continue
            paths: list[tuple[Path, str]] = []
            missing: list[str] = []
            for method in method_order(cfg, item):
                png = resolve_method_png(model_root, prefix, method, item)
                if png is not None:
                    paths.append((png, label_for(cfg, method)))
                else:
                    missing.append(method)
            if len(paths) < 1:
                continue
            strip_path = model_root / strip_name
            create_strip(paths, strip_path, args.margin, args.background, args.labels)
            print(f"[strip] {dataset}/{model}: {len(paths)} image(s) -> {strip_path}")
            if missing:
                print(f"[strip] {dataset}/{model}: missing {', '.join(missing)}")
            if rank is not None:
                ranked_by_dataset.setdefault(dataset, []).append((rank, strip_path))

    for dataset, strips in ranked_by_dataset.items():
        cfg = datasets.get(dataset, {})
        item = dataset_item(preset, cfg, args)
        ranked_name = args.ranked_name or f"ranked_strip_{item}.png"
        out_path = output_root / dataset / ranked_name
        if create_ranked(strips, out_path, args.margin, args.background):
            print(f"[ranked] {dataset}: {len(strips)} strip(s) -> {out_path}")


if __name__ == "__main__":
    main()
