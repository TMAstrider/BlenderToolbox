import argparse
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def load_models(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_flag(args: list[str], key: str, value):
    flag = f"--{key.replace('_', '-')}"
    if isinstance(value, bool):
        if value:
            args.append(flag)
        return
    if isinstance(value, (list, tuple)):
        args.append(flag)
        args.extend(str(item) for item in value)
        return
    args.extend([flag, str(value)])


def build_blender_command(blender_exe: Path, render_script: Path, model_dir: Path, output_dir: Path, preset: dict) -> list[str]:
    cmd = [str(blender_exe), "-b", "-P", str(render_script), "--", "--model-dir", str(model_dir), "--output-dir", str(output_dir)]
    for key, value in preset.items():
        append_flag(cmd, key, value)
    return cmd


def load_preset(path: Path) -> tuple[dict, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "render_args" in data:
        render_args = data["render_args"]
        strip = data.get("strip_1x4", {})
        return render_args, strip
    return data, {}


def create_strip_image(model_output: Path, strip_cfg: dict):
    if not strip_cfg:
        return

    items = strip_cfg.get("items", [])
    if not items:
        return

    margin = int(strip_cfg.get("margin", 0))
    out_name = strip_cfg.get("output_name", "strip_1x4.png")

    opened = []
    for item in items:
        image_path = model_output / item["file"]
        if not image_path.exists():
            print(f"  [strip] skip missing: {image_path}")
            continue
        img = Image.open(image_path).convert("RGBA")
        # zero out RGB where alpha==0 (fix Blender premultiplied-alpha black background)
        import numpy as np
        a = np.array(img)
        a[a[:, :, 3] == 0] = [0, 0, 0, 0]
        opened.append(Image.fromarray(a))

    if not opened:
        print(f"  [strip] no inputs found, skipping strip for {model_output}")
        return
    img_w, img_h = opened[0].size
    cols = len(opened)
    canvas_w = cols * img_w + (cols - 1) * margin
    canvas_h = img_h
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    for idx, image in enumerate(opened):
        x = idx * (img_w + margin)
        canvas.alpha_composite(image, dest=(x, 0))

    canvas.save(model_output / out_name)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender-exe", default=r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe")
    parser.add_argument("--render-script", default="render_eval_set.py")
    parser.add_argument("--models-root", default=r"final_mesh\20260424_current3_ours_nsh_multipull_casefix\models")
    parser.add_argument("--preset-file", default=r"render_presets\meshlab_blue_workbench.json")
    parser.add_argument("--model-list", default=r"render_presets\sample_models_10.txt")
    parser.add_argument("--output-root", default=r"renders\sample10_meshlab_blue")
    return parser.parse_args()


def main():
    args = parse_args()
    repo_root = Path.cwd()
    blender_exe = (repo_root / args.blender_exe).resolve() if not Path(args.blender_exe).is_absolute() else Path(args.blender_exe)
    render_script = (repo_root / args.render_script).resolve()
    models_root = (repo_root / args.models_root).resolve()
    preset_file = (repo_root / args.preset_file).resolve()
    model_list = (repo_root / args.model_list).resolve()
    output_root = (repo_root / args.output_root).resolve()

    if not blender_exe.exists():
        raise FileNotFoundError(f"Blender not found: {blender_exe}")
    if not render_script.exists():
        raise FileNotFoundError(f"Render script not found: {render_script}")
    if not models_root.exists():
        raise FileNotFoundError(f"Models root not found: {models_root}")

    preset, strip_cfg = load_preset(preset_file)
    models = load_models(model_list)
    output_root.mkdir(parents=True, exist_ok=True)

    summary = {
        "blender_exe": str(blender_exe),
        "render_script": str(render_script),
        "models_root": str(models_root),
        "preset_file": str(preset_file),
        "render_args": preset,
        "strip_1x4": strip_cfg,
        "models": models,
        "output_root": str(output_root),
    }
    (output_root / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    for model_name in models:
        model_dir = models_root / model_name
        if not model_dir.exists():
            print(f"[skip] missing model: {model_name}")
            continue
        model_output = output_root / model_name
        model_output.mkdir(parents=True, exist_ok=True)
        cmd = build_blender_command(blender_exe, render_script, model_dir, model_output, preset)
        print(f"[render] {model_name}")
        result = subprocess.run(cmd, cwd=repo_root)
        if result.returncode != 0:
            raise SystemExit(result.returncode)
        create_strip_image(model_output, strip_cfg)


if __name__ == "__main__":
    main()
