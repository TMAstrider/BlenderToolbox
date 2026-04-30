import argparse
import json
import subprocess
import sys
from pathlib import Path

from render_eval_batch import append_flag, create_strip_image, load_preset


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender-exe", default=r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe")
    parser.add_argument("--render-script", default="render_eval_set.py")
    parser.add_argument("--export-script", default="export_selected_transform.py")
    parser.add_argument("--preset-file", default=r"render_presets\meshlab_blue_strip_gt_method1_method2_ours.json")
    parser.add_argument("--adjust-blend", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def normalize_paths(args):
    repo_root = Path.cwd()
    blender_exe = (repo_root / args.blender_exe).resolve() if not Path(args.blender_exe).is_absolute() else Path(args.blender_exe)
    render_script = (repo_root / args.render_script).resolve()
    export_script = (repo_root / args.export_script).resolve()
    preset_file = (repo_root / args.preset_file).resolve()
    adjust_blend = (repo_root / args.adjust_blend).resolve() if not Path(args.adjust_blend).is_absolute() else Path(args.adjust_blend)
    model_dir = (repo_root / args.model_dir).resolve() if not Path(args.model_dir).is_absolute() else Path(args.model_dir)
    output_dir = (repo_root / args.output_dir).resolve() if not Path(args.output_dir).is_absolute() else Path(args.output_dir)
    return repo_root, blender_exe, render_script, export_script, preset_file, adjust_blend, model_dir, output_dir


def build_render_command(blender_exe: Path, render_script: Path, model_dir: Path, output_dir: Path, render_args: dict) -> list[str]:
    cmd = [str(blender_exe), "-b", "-P", str(render_script), "--", "--model-dir", str(model_dir), "--output-dir", str(output_dir)]
    for key, value in render_args.items():
        append_flag(cmd, key, value)
    return cmd


def extract_adjust_data(repo_root: Path, blender_exe: Path, export_script: Path, adjust_blend: Path, json_out: Path) -> dict:
    cmd = [
        str(blender_exe),
        str(adjust_blend),
        "-b",
        "-P",
        str(export_script),
        "--",
        "--json-out",
        str(json_out),
    ]
    result = subprocess.run(cmd, cwd=repo_root)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    return json.loads(json_out.read_text(encoding="utf-8"))


def merge_adjust_into_render_args(render_args: dict, adjust_data: dict) -> dict:
    merged = dict(render_args)

    mesh = adjust_data.get("mesh", {})
    if mesh:
        merged["location"] = mesh["location"]
        merged["rotation"] = mesh["rotation"]
        merged["scale"] = mesh["scale"]

    camera = adjust_data.get("camera", {})
    if camera:
        merged["camera_location"] = camera["location"]
        # round tiny values to 0 to avoid -1.7e-05 style args that confuse argparse
        merged["camera_rotation"] = [round(v, 4) for v in camera["rotation"]]
        merged["camera_focal_length"] = camera["focal_length"]

    return merged


def main():
    args = parse_args()
    repo_root, blender_exe, render_script, export_script, preset_file, adjust_blend, model_dir, output_dir = normalize_paths(args)

    if not blender_exe.exists():
        raise FileNotFoundError(f"Blender not found: {blender_exe}")
    if not render_script.exists():
        raise FileNotFoundError(f"Render script not found: {render_script}")
    if not export_script.exists():
        raise FileNotFoundError(f"Export script not found: {export_script}")
    if not preset_file.exists():
        raise FileNotFoundError(f"Preset file not found: {preset_file}")
    if not adjust_blend.exists():
        raise FileNotFoundError(f"Adjust blend not found: {adjust_blend}")
    if not model_dir.exists():
        raise FileNotFoundError(f"Model dir not found: {model_dir}")

    render_args, strip_cfg = load_preset(preset_file)
    output_dir.mkdir(parents=True, exist_ok=True)

    adjust_json = output_dir / "_adjust_params.json"
    adjust_data = extract_adjust_data(repo_root, blender_exe, export_script, adjust_blend, adjust_json)
    merged_args = merge_adjust_into_render_args(render_args, adjust_data)

    summary = {
        "adjust_blend": str(adjust_blend),
        "model_dir": str(model_dir),
        "preset_file": str(preset_file),
        "adjust_data": adjust_data,
        "final_render_args": merged_args,
        "output_dir": str(output_dir),
    }
    (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    cmd = build_render_command(blender_exe, render_script, model_dir, output_dir, merged_args)
    result = subprocess.run(cmd, cwd=repo_root)
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    create_strip_image(output_dir, strip_cfg)


if __name__ == "__main__":
    main()
