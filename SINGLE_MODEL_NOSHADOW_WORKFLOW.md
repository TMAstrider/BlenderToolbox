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
- Sync that layout to `contour`, `nonmanifold_edges`, and
  `nonmanifold_regions` before rendering the final four images.

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
  --output-root ".\renders" `
  --resolution-x 1100 `
  --resolution-y 1100
```

Or run the wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_portable_render_batch.ps1
```

CSV format:

```csv
model,rendered
Armadillo__407456ef,done
```

Columns:

- `model`: model folder/name
- `rendered`: optional bookkeeping column

Output directories are inferred by scanning:

```text
renders/*/<model>/*
```

Every method folder containing `{model}_plastic.blend` is rendered. For example,
this row:

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
