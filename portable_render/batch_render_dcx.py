from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_INPUT_ROOT = Path(r"F:\Code\allresult\NonDetect\DCX\result_gt_poisson100k_final")
DEFAULT_OUTPUT_ROOT = Path(r"F:\Code\allresult\portable_geodesic_surface_contours\outputs\DCX")
DEFAULT_DISTANCE_PYTHON = Path(r"C:\ProgramData\anaconda3\envs\blender\python.exe")
DEFAULT_BLENDER_EXE = Path(r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch render DCX models with simplified per-model output names."
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--distance-python", type=Path, default=DEFAULT_DISTANCE_PYTHON)
    parser.add_argument("--blender-exe", type=Path, default=DEFAULT_BLENDER_EXE)
    parser.add_argument("--start", type=str, default="", help="Optional start model id, inclusive.")
    parser.add_argument("--end", type=str, default="", help="Optional end model id, inclusive.")
    parser.add_argument("--samples", type=int, default=96)
    parser.add_argument("--resolution-x", type=int, default=1600)
    parser.add_argument("--resolution-y", type=int, default=1100)
    parser.add_argument("--fit-size", type=float, default=2.4)
    parser.add_argument("--line-density", type=float, default=8.5)
    parser.add_argument("--line-width", type=float, default=0.028)
    parser.add_argument("--distance-percentile", type=float, default=100.0)
    parser.add_argument(
        "--camera-overrides-root",
        type=Path,
        default=None,
        help="Optional directory containing per-model camera JSON files named <model_id>.json.",
    )
    parser.add_argument("--force", action="store_true", help="Recompute and rerender even if outputs already exist.")
    return parser.parse_args()


def list_model_ids(input_root: Path, start: str, end: str) -> list[str]:
    ids = sorted(p.name for p in input_root.iterdir() if p.is_dir())
    if start:
        ids = [x for x in ids if x >= start]
    if end:
        ids = [x for x in ids if x <= end]
    return ids


def expected_outputs(model_output_dir: Path, model_id: str) -> list[Path]:
    return [
        model_output_dir / f"{model_id}_heat_distances.npz",
        model_output_dir / f"{model_id}_contour.png",
        model_output_dir / f"{model_id}_contour.blend",
        model_output_dir / f"{model_id}_plastic.png",
        model_output_dir / f"{model_id}_plastic.blend",
        model_output_dir / f"{model_id}_nonmanifold_edges.png",
        model_output_dir / f"{model_id}_nonmanifold_edges.blend",
        model_output_dir / f"{model_id}_nonmanifold_regions.png",
        model_output_dir / f"{model_id}_nonmanifold_regions.blend",
    ]


def cleanup_blender_backups(model_output_dir: Path) -> None:
    for backup in model_output_dir.glob("*.blend1"):
        backup.unlink(missing_ok=True)


def find_camera_override(model_id: str, model_output_dir: Path, overrides_root: Path | None) -> Path | None:
    if overrides_root is not None:
        candidate = overrides_root / f"{model_id}.json"
        if candidate.exists():
            return candidate
    local_candidate = model_output_dir / f"{model_id}_camera.json"
    if local_candidate.exists():
        return local_candidate
    return None


def run_command(cmd: list[str], label: str) -> None:
    print(f"[run] {label}")
    print("       " + " ".join(f'"{x}"' if " " in x else x for x in cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    args = parse_args()
    project_dir = Path(__file__).resolve().parent
    compute_script = project_dir / "compute_heat_distances.py"
    render_script = project_dir / "render_surface_contours.py"

    if not args.input_root.exists():
        raise FileNotFoundError(f"Input root not found: {args.input_root}")
    if not args.distance_python.exists():
        raise FileNotFoundError(f"Distance python not found: {args.distance_python}")
    if not args.blender_exe.exists():
        raise FileNotFoundError(f"Blender executable not found: {args.blender_exe}")

    model_ids = list_model_ids(args.input_root, args.start, args.end)
    if not model_ids:
        print("No model folders found in the requested range.")
        return 0

    args.output_root.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    completed = 0
    skipped = 0

    for index, model_id in enumerate(model_ids, start=1):
        model_dir = args.input_root / model_id
        mesh_path = model_dir / "final_non_manifold_mesh_restored_to_input_scale.ply"
        if not mesh_path.exists():
            print(f"[skip] {model_id}: mesh not found -> {mesh_path}")
            skipped += 1
            continue

        model_output_dir = args.output_root / model_id
        model_output_dir.mkdir(parents=True, exist_ok=True)

        outputs = expected_outputs(model_output_dir, model_id)
        if (not args.force) and all(path.exists() for path in outputs):
            print(f"[skip] {model_id}: outputs already exist")
            skipped += 1
            continue

        print(f"[{index}/{len(model_ids)}] processing {model_id}")

        distance_output = model_output_dir / f"{model_id}_heat_distances.npz"
        contour_png = model_output_dir / f"{model_id}_contour.png"
        contour_blend = model_output_dir / f"{model_id}_contour.blend"
        plastic_png = model_output_dir / f"{model_id}_plastic.png"
        plastic_blend = model_output_dir / f"{model_id}_plastic.blend"
        edges_png = model_output_dir / f"{model_id}_nonmanifold_edges.png"
        edges_blend = model_output_dir / f"{model_id}_nonmanifold_edges.blend"
        regions_png = model_output_dir / f"{model_id}_nonmanifold_regions.png"
        regions_blend = model_output_dir / f"{model_id}_nonmanifold_regions.blend"
        camera_override = find_camera_override(model_id, model_output_dir, args.camera_overrides_root)

        run_command(
            [
                str(args.distance_python),
                str(compute_script),
                "--mesh",
                str(mesh_path),
                "--output",
                str(distance_output),
            ]
            + (["--camera-override", str(camera_override)] if camera_override is not None else []),
            f"{model_id} heat distances",
        )

        render_cmd = [
                str(args.blender_exe),
                "-b",
                "-P",
                str(render_script),
                "--",
                "--mesh",
                str(mesh_path),
                "--distance-file",
                str(distance_output),
                "--output",
                str(contour_png),
                "--plain-output",
                str(plastic_png),
                "--nonmanifold-output",
                str(edges_png),
                "--regions-output",
                str(regions_png),
                "--blend",
                str(contour_blend),
                "--plain-blend",
                str(plastic_blend),
                "--nonmanifold-blend",
                str(edges_blend),
                "--regions-blend",
                str(regions_blend),
                "--samples",
                str(args.samples),
                "--resolution-x",
                str(args.resolution_x),
                "--resolution-y",
                str(args.resolution_y),
                "--fit-size",
                str(args.fit_size),
                "--line-density",
                str(args.line_density),
                "--line-width",
                str(args.line_width),
                "--distance-percentile",
                str(args.distance_percentile),
            ]
        if camera_override is not None:
            render_cmd.extend(["--camera-override", str(camera_override)])

        run_command(render_cmd, f"{model_id} render four outputs")

        cleanup_blender_backups(model_output_dir)
        completed += 1

    elapsed = time.perf_counter() - started
    print("")
    print(f"Completed models: {completed}")
    print(f"Skipped models: {skipped}")
    print(f"Output root: {args.output_root}")
    print(f"Elapsed time: {elapsed:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
