from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
FAMILY_SOURCE_RELATIVE = {
    "GT_00000001": Path(r"renders\ablation\density_GT_00000001_400k\ours\density_GT_00000001_400k_plastic.blend"),
    "GT_00000003": Path(r"renders\ablation\density_GT_00000003_400k\ours\density_GT_00000003_400k_plastic.blend"),
    "GT_taxi": Path(r"renders\ablation\density_GT_taxi_400k\ours\density_GT_taxi_400k_plastic.blend"),
    "triperp_plane": Path(r"renders\ablation\density_triperp_plane_400k\ours\density_triperp_plane_400k_plastic.blend"),
}


def parse_args():
    parser = argparse.ArgumentParser(description="Sync ablation plastic blends to a shared view per base model.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--ablation-root", default=r"renders\ablation")
    parser.add_argument("--sync-script", default="sync_portable_blend_layout.py")
    parser.add_argument("--blender-exe", default=DEFAULT_BLENDER)
    parser.add_argument("--families", nargs="*", default=[])
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def command_text(cmd: list[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in cmd)


def family_for_model(model_name: str) -> str | None:
    for family in FAMILY_SOURCE_RELATIVE:
        if model_name.startswith(f"density_{family}") or model_name.startswith(f"noise_{family}"):
            return family
    return None


def run(cmd: list[str], cwd: Path):
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {command_text(cmd)}")


def main():
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    ablation_root = Path(args.ablation_root)
    if not ablation_root.is_absolute():
        ablation_root = (repo_root / ablation_root).resolve()
    blender_exe = Path(args.blender_exe)
    if not blender_exe.is_absolute():
        blender_exe = (repo_root / blender_exe).resolve()
    sync_script = Path(args.sync_script)
    if not sync_script.is_absolute():
        sync_script = (repo_root / sync_script).resolve()

    if not ablation_root.exists():
        raise FileNotFoundError(f"Ablation render root not found: {ablation_root}")
    if not blender_exe.exists():
        raise FileNotFoundError(f"Blender not found: {blender_exe}")
    if not sync_script.exists():
        raise FileNotFoundError(f"Sync script not found: {sync_script}")

    wanted = {name.strip() for name in args.families if name.strip()}
    grouped_targets: dict[str, list[Path]] = {}
    for blend in sorted(ablation_root.glob(r"*\ours\*_plastic.blend")):
        model_name = blend.parents[1].name
        family = family_for_model(model_name)
        if family is None:
            continue
        if wanted and family not in wanted:
            continue
        grouped_targets.setdefault(family, []).append(blend.resolve())

    if not grouped_targets:
        print("[skip] no matching ablation plastic blends found")
        return

    for family, targets in grouped_targets.items():
        source = (repo_root / FAMILY_SOURCE_RELATIVE[family]).resolve()
        if not source.exists():
            raise FileNotFoundError(f"Source blend missing for {family}: {source}")
        sync_targets = [target for target in targets if target != source]
        print(f"[family] {family}")
        print(f"  source: {source}")
        print(f"  targets: {len(sync_targets)}")
        if not sync_targets:
            continue
        cmd = [
            str(blender_exe),
            "-b",
            "-P",
            str(sync_script),
            "--",
            "--source",
            str(source),
            "--targets",
            *[str(target) for target in sync_targets],
        ]
        if args.dry_run:
            print(f"  dry-run: {command_text(cmd)}")
            continue
        run(cmd, repo_root)


if __name__ == "__main__":
    main()
