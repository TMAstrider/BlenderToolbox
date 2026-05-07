# Single Model No-Shadow Rendering Workflow

This is the current workflow for one-off single mesh renders after manual tuning.

## Baseline

Use the portable renderer as the base pipeline:

- `portable_render/compute_heat_distances.py`
- `portable_render/render_surface_contours.py`

The portable scripts still own the core data and material logic:

- heat geodesic distance computation
- contour coloring
- plain plastic material generation
- non-manifold edge detection
- non-manifold region partition coloring

This workflow only adds final presentation control around the generated `.blend`
files.

## Current Presentation Rules

For final single-model figures:

- Use transparent PNG output.
- Hide the ground plane.
- Remove contact shadows.
- Keep the manually tuned camera/model/light layout from the current
  `plastic.blend`.
- Sync that layout to all four generated `.blend` files before rendering the
  final four images.

The current Armadillo working folder is:

```text
renders/portable_Armadillo__407456ef_noshadow_final
```

## Helper Scripts

### `render_portable_blend_transparent.py`

Renders an existing `.blend` with final output settings.

Typical final mode:

```powershell
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b `
  -P ".\render_portable_blend_transparent.py" -- `
  --blend ".\renders\portable_Armadillo__407456ef_noshadow_final\Armadillo__407456ef_plastic.blend" `
  --output ".\renders\portable_Armadillo__407456ef_noshadow_final\Armadillo__407456ef_plastic.png" `
  --hide-ground
```

Square 1100 px output:

```powershell
--resolution-x 1100 --resolution-y 1100
```

Optional material test color:

```powershell
--plain-color 0.32 0.60 0.90
```

### `sync_portable_blend_layout.py`

Copies layout from the tuned `plastic.blend` to the other generated `.blend`
files while preserving each target's own material.

It syncs:

- active camera transform and camera data
- subject mesh transform
- non-manifold curve overlay transform
- light transforms and light power/size
- render resolution
- transparent output
- hidden ground plane / no shadow catcher

Example:

```powershell
$dir = ".\renders\portable_Armadillo__407456ef_noshadow_final"
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b `
  -P ".\sync_portable_blend_layout.py" -- `
  --source "$dir\Armadillo__407456ef_plastic.blend" `
  --targets `
    "$dir\Armadillo__407456ef_contour.blend" `
    "$dir\Armadillo__407456ef_nonmanifold_edges.blend" `
    "$dir\Armadillo__407456ef_nonmanifold_regions.blend"
```

## Final Four-Image Render

After syncing, render all four final PNGs:

```powershell
$dir = ".\renders\portable_Armadillo__407456ef_noshadow_final"
$items = @("contour", "plastic", "nonmanifold_edges", "nonmanifold_regions")
foreach ($item in $items) {
  & "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b `
    -P ".\render_portable_blend_transparent.py" -- `
    --blend "$dir\Armadillo__407456ef_$item.blend" `
    --output "$dir\Armadillo__407456ef_$item.png" `
    --hide-ground `
    --resolution-x 1100 `
    --resolution-y 1100
}
```

## Batch Launcher

For multiple tuned model folders, use:

```powershell
python .\portable_render_batch_from_list.py `
  --list ".\render_presets\portable_noshadow_render_list.csv" `
  --preset-file ".\render_presets\portable_noshadow_preset.json"
```

Or run the wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_portable_render_batch.ps1
```

CSV format:

```csv
model
Armadillo__407456ef
```

Columns:

- `model`: model folder/name

The preset controls datasets, methods, output root, and resolution:

```json
{
  "output_root": "renders",
  "auto_generate_blends": true,
  "force_regenerate_blends": false,
  "inherit_existing_layout_on_regenerate": true,
  "render_on_generate": false,
  "parallel_jobs": 3,
  "parallel_generate_blends": false,
  "force_render_all": true,
  "force_render_models": [],
  "render_items": ["contour", "plastic", "nonmanifold_edges", "nonmanifold_regions"],
  "resolution": { "x": 1100, "y": 1100 },
  "datasets": {
    "manifold": {
      "enabled": true,
      "methods": ["ours"]
    },
    "scene": {
      "enabled": false,
      "methods": ["ours"]
    }
  }
}
```

Useful preset switches:

- `parallel_jobs`: number of concurrent Blender render processes.
- `parallel_generate_blends`: also parallelize first-time `.blend` generation.
- `force_render_all`: rerender selected PNGs even if they already exist.
- `force_render_models`: rerender selected models even if their PNGs already
  exist, for example `["Armadillo__407456ef"]`.
- `render_items`: render only selected outputs, for example `["plastic"]`.
- `auto_generate_blends`: create missing `.blend` files from the dataset mesh.
- `render_on_generate`: render immediately after creating missing `.blend`
  files. Keep this `false` when you want to manually tune the generated
  `plastic.blend` first.
- `force_regenerate_blends`: rebuild `.blend` files from the source mesh even
  when they already exist.
- `inherit_existing_layout_on_regenerate`: before force-regenerating, copy the
  current layout source `plastic.blend`; after regeneration, sync that old
  camera/model transform/light setup onto the new `.blend` files. This is the
  normal mode when the source `.ply` changed but the view should stay the same.

The source mesh is read only when generating or force-regenerating `.blend`
files. Final PNG rendering opens the existing `.blend` and uses the mesh stored
inside that scene; it does not re-read the original `.ply`.

For an existing tuned model whose source `.ply` changed, set:

```json
"force_regenerate_blends": true,
"inherit_existing_layout_on_regenerate": true
```

Run the batch once, then set `force_regenerate_blends` back to `false`. The new
mesh and heat-distance data are rebuilt from the source path, while the old
layout is reused.

To force PNG rendering for only a few models without touching the rest, set:

```json
"force_render_all": false,
"force_render_models": ["Armadillo__407456ef", "dragon_vrip"]
```

The same can be passed on the command line:

```powershell
python .\portable_render_batch_from_list.py --force-render-models Armadillo__407456ef dragon_vrip
```

For each model in the CSV, output directories are inferred from the enabled
dataset/method pairs:

```text
renders/<dataset>/<model>/<method>
```

Every method folder containing `{model}_plastic.blend` is rendered. With the
default preset, this row:

```text
Armadillo__407456ef
```

will render folders such as:

```text
renders/manifold/Armadillo__407456ef/ours
```

## What Changed Compared With The Portable Base

The base portable algorithm was not changed.

The final single-model workflow changes presentation only:

- ground plane is hidden
- shadow catcher/contact shadow is disabled
- PNG uses RGBA transparent background
- manually tuned camera/model/light transforms are reused consistently across
  the four `.blend` files
- optional one-off plastic color override is available for tests
- output resolution can be overridden at render time
