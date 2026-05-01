from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


DEFAULT_OUTPUT_ROOT = Path(r"F:\Code\allresult\portable_geodesic_surface_contours\outputs\DCX")
DEFAULT_BLENDER_EXE = Path(r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract reusable camera overrides from per-model plastic blend files."
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--blender-exe", type=Path, default=DEFAULT_BLENDER_EXE)
    parser.add_argument(
        "--export-script",
        type=Path,
        default=Path(__file__).resolve().parent / "export_camera_override.py",
    )
    parser.add_argument(
        "--manifest-md",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "CAMERA_OVERRIDES.md",
    )
    parser.add_argument(
        "--manifest-json",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "camera_overrides_manifest.json",
    )
    parser.add_argument("--mode", type=str, default="directional_fit", choices=["directional_fit", "exact"])
    return parser.parse_args()


def run_command(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def fmt_vec(values: list[float] | None) -> str:
    if not values:
        return "-"
    return "[" + ", ".join(f"{float(v):.3f}" for v in values) + "]"


def main() -> int:
    args = parse_args()
    if not args.output_root.exists():
        raise FileNotFoundError(f"Output root not found: {args.output_root}")
    if not args.blender_exe.exists():
        raise FileNotFoundError(f"Blender executable not found: {args.blender_exe}")
    if not args.export_script.exists():
        raise FileNotFoundError(f"Export script not found: {args.export_script}")

    model_dirs = sorted(p for p in args.output_root.iterdir() if p.is_dir())
    manifest_rows: list[dict] = []

    for model_dir in model_dirs:
        model_id = model_dir.name
        blend_path = model_dir / f"{model_id}_plastic.blend"
        camera_json = model_dir / f"{model_id}_camera.json"
        if not blend_path.exists():
            continue

        cmd = [
            str(args.blender_exe),
            "-b",
            str(blend_path),
            "-P",
            str(args.export_script),
            "--",
            "--output",
            str(camera_json),
            "--mode",
            args.mode,
        ]
        print(f"[extract] {model_id}")
        run_command(cmd)

        with camera_json.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        data["model_id"] = model_id
        data["blend_path"] = str(blend_path)
        data["camera_json"] = str(camera_json)
        manifest_rows.append(data)

    args.manifest_json.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest_json.open("w", encoding="utf-8") as handle:
        json.dump(manifest_rows, handle, indent=2)
        handle.write("\n")

    lines = [
        "# Camera Overrides",
        "",
        f"Total models: {len(manifest_rows)}",
        f"Export mode: `{args.mode}`",
        "",
        "| Model | Default? | Lens | Position Hint | Look Target | Exact Location | Exact Rotation | JSON |",
        "| --- | --- | ---: | --- | --- | --- | --- | --- |",
    ]
    for row in manifest_rows:
        model_id = row["model_id"]
        default_flag = "yes" if row.get("matches_default_camera") else "no"
        lens = float(row.get("exact_lens", row.get("lens", 58.0)))
        position_hint = fmt_vec(row.get("position_hint"))
        look_target = fmt_vec(row.get("look_target"))
        exact_location = fmt_vec(row.get("exact_location"))
        exact_rotation = fmt_vec(row.get("exact_rotation_euler"))
        json_rel = Path(row["camera_json"]).name
        lines.append(
            f"| {model_id} | {default_flag} | {lens:.2f} | {position_hint} | {look_target} | {exact_location} | {exact_rotation} | {json_rel} |"
        )

    args.manifest_md.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Saved manifest markdown: {args.manifest_md}")
    print(f"Saved manifest json: {args.manifest_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
