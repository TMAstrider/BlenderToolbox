from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from PIL import Image


def parse_args():
    parser = argparse.ArgumentParser(
        description="Export all PNGs from one rendered model folder into an images-only folder."
    )
    parser.add_argument(
        "--source-model-dir",
        required=True,
        help="Rendered model directory, for example renders/gt/GT_00003987_red_nonmanifold_mark.",
    )
    parser.add_argument(
        "--source-root",
        default="renders",
        help="Root used to preserve relative output layout. Defaults to renders.",
    )
    parser.add_argument(
        "--output-root",
        default="",
        help="Output root. Defaults to renders_images_only/single_model_<timestamp>.",
    )
    parser.add_argument(
        "--crop-padding",
        type=int,
        default=0,
        help="Padding kept around the non-transparent alpha bounding box.",
    )
    parser.add_argument(
        "--no-crop",
        action="store_true",
        help="Copy images without alpha cropping.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output PNGs.",
    )
    return parser.parse_args()


def crop_alpha(image: Image.Image, padding: int) -> Image.Image:
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        return image

    left, top, right, bottom = bbox
    pad = max(0, int(padding))
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(image.width, right + pad)
    bottom = min(image.height, bottom + pad)
    return image.crop((left, top, right, bottom))


def default_output_root(repo_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return repo_root / "renders_images_only" / f"single_model_{timestamp}"


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    source_model_dir = Path(args.source_model_dir)
    if not source_model_dir.is_absolute():
        source_model_dir = repo_root / source_model_dir
    source_model_dir = source_model_dir.resolve()

    source_root = Path(args.source_root)
    if not source_root.is_absolute():
        source_root = repo_root / source_root
    source_root = source_root.resolve()

    if args.output_root:
        output_root = Path(args.output_root)
        if not output_root.is_absolute():
            output_root = repo_root / output_root
        output_root = output_root.resolve()
    else:
        output_root = default_output_root(repo_root)

    if not source_model_dir.is_dir():
        raise FileNotFoundError(f"Source model dir not found: {source_model_dir}")

    copied = 0
    skipped = 0
    for png in sorted(source_model_dir.rglob("*.png")):
        try:
            relative = png.resolve().relative_to(source_root)
        except ValueError:
            relative = Path(source_model_dir.name) / png.relative_to(source_model_dir)
        target = output_root / relative
        if target.exists() and not args.overwrite:
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)

        image = Image.open(png)
        if not args.no_crop:
            image = crop_alpha(image, args.crop_padding)
        image.save(target)
        copied += 1

    print(f"[export-single] source={source_model_dir}")
    print(f"[export-single] output={output_root}")
    print(f"[export-single] copied={copied}, skipped={skipped}")


if __name__ == "__main__":
    main()
