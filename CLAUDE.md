# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

BlenderToolbox renders 3D meshes/point clouds in Blender 4.5 headless. It wraps the `bpy` API into composable Python functions for scene setup, material assignment, lighting, and camera control. The main use case is batch-rendering evaluation results from multiple methods and generating comparison strip images.

## Commands

All commands run from repo root in PowerShell. Blender is installed at:
```
C:\Program Files\Blender Foundation\Blender 4.5\blender.exe
```

### Single mesh quick render
```powershell
python default_mesh.py
```
Adjust `mesh_path`, `mesh_position`, `mesh_rotation`, `mesh_scale` in the script first.

### Create an adjustment .blend from a mesh
```powershell
blender -b -P make_adjust_scene.py -- --mesh-path "<path>" --blend-out "<out.blend>" --recalc-normals
```

### Render from an adjusted .blend (single model)
```powershell
python render_from_adjust_blend.py --adjust-blend "<path.blend>" --model-dir "<meshes/dataset/models/modelname>" --output-dir "<renders/modelname>" --preset-file "render_presets/cycles_flat_ao_strip.json"
```

### Batch render from CSV (main pipeline)
```powershell
python render_from_list.py --list meshes/render_list.csv --meshes-root meshes --output-root renders --adjust-root adjust_scenes --preset-file render_presets/cycles_flat_ao_strip.json --max-parallel 3
```

### Clean non-manifold mesh
```powershell
python clean_nonmanifold.py --mesh "<input.ply>" --pointcloud "<gt_pointcloud.ply>" --output "<ours_mls_clean.ply>" --threshold 0.004 --filter-mode novel
```

### Export mesh components for debugging
```powershell
python export_components.py --mesh "<input.ply>" --outdir "debug_components/model"
```

## Architecture

### Core library: `blendertoolbox/`
The `__init__.py` exposes ~70 functions. Key ones:
- `blenderInit(res_x, res_y, samples, exposure, use_gpu)` — initialize Cycles scene
- `readMesh(path, location, rotation, scale)` — import a mesh file
- `renderImage(output_path, camera)` — render one frame
- `setCamera(location, lookat, focal_length)` — position camera via look-at
- `setCamera_from_UI(location, rotation, focal_length)` — position camera via rotation
- `setLight_sun(rotation, strength, shadow_soft_size)` / `setLight_ambient(color)`
- `setMat_*` — many material presets (monotone, plastic, ceramic, flat_ao, ao, etc.)
- `colorObj(RGBA, specular, roughness, ...)` — material color descriptor

### Scripts layer (run by Blender via `-b -P`)
- **`make_adjust_scene.py`** — Imports a single mesh, sets up scene + material, saves .blend. Used to create files that get manually adjusted in Blender GUI.
- **`render_eval_set.py`** — Imports ALL mesh files in `--model-dir`, renders each to `--output-dir`. Reads transforms from CLI args (typically extracted from an adjust .blend).
- **`export_selected_transform.py`** — Headless: opens a .blend, exports mesh/camera transforms as JSON.

### Orchestration layer (run by Python)
- **`render_from_list.py`** — **Main pipeline.** Reads `render_list.csv`. Phase 1: calls `make_adjust_scene.py` for `blend=todo` rows. Phase 2: for `blend=done` rows, extracts transforms via `export_selected_transform.py`, renders via `render_eval_set.py`, and generates comparison strips.
- **`render_from_adjust_blend.py`** — Single-model version: extract → render → strip.
- **`render_eval_batch.py`** — Simple batch: iterate a model list, call `render_eval_set.py` per model.

### Data flow
```
PLY/OBJ files  ──→  make_adjust_scene.py  ──→  .blend  ──→  (manual adjust in Blender GUI)
                                                                        │
                   export_selected_transform.py  ←──────────────────────┘
                          │
                          ▼  (JSON: mesh location/rotation/scale, camera params)
                          │
      render_eval_set.py  ←──  merged with preset render_args
                          │
                          ▼
                      PNG renders  ──→  strip images (Pillow)
```

### Mesh directory convention
```
meshes/<dataset_dir>/models/<model_name>/
                                  ├── ours_mls.ply          (main mesh)
                                  ├── ours_mls_clean.ply    (optional cleaned mesh)
                                  ├── gt_pointcloud.ply      (GT point cloud)
                                  ├── nsh.ply                (comparison method)
                                  ├── multipull.ply           (comparison method)
                                  └── ...
```
Dataset folders start with a dataset name prefix (e.g., `manifold_*`, `scene_*`).

### Key configuration files
- **`meshes/dataset_map.json`** — Maps dataset keys → actual directory names, output subdirectories, strip image column order, and column labels.
- **`meshes/render_list.csv`** — Batch job table: `dataset, model, clean, blend, rendered, preset, rank`.
- **`render_presets/*.json`** — Preset bundles containing `render_args` (resolution, samples, material, lighting, etc.) and optional `strip_1x4` config.

### Render presets format
```json
{
  "render_args": { "resolution": 1024, "samples": 200, "material": "flat_ao", ... },
  "strip_1x4": { "margin": 0, "output_name": "strip_1x4.png", "items": [...] }
}
```

Key materials: `monotone` (3-tone grayscale + outline), `flat_ao` (AO + slight specular), `flat` (solid color), `ao` (pure AO), `plastic`, `ceramic`, `matte`.

Both Cycles and Blender Workbench engines are supported.

## Important notes

- Blender scripts use `--` separator between Blender args and script args.
- `render_eval_set.py` picks up ALL `.ply`/`.obj`/`.stl` files in the model directory.
- The `.gitignore` excludes `renders/`, `render_presets/`, and `meshes/` — these are regenerated from external data.
- `clean_nonmanifold.py` needs `scipy` in addition to `numpy` and `plyfile`.
