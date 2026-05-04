$ErrorActionPreference = "Stop"

$Repo = "C:\Users\Nadine\Desktop\BlenderToolbox"
$Blender = "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
$OutDir = Join-Path $Repo "renders\portable_Armadillo__407456ef_noshadow_final"

$SourceBlend = Join-Path $OutDir "Armadillo__407456ef_plastic.blend"
$Targets = @(
  (Join-Path $OutDir "Armadillo__407456ef_contour.blend"),
  (Join-Path $OutDir "Armadillo__407456ef_nonmanifold_edges.blend"),
  (Join-Path $OutDir "Armadillo__407456ef_nonmanifold_regions.blend")
)

Set-Location $Repo

Write-Host "Syncing camera/model/light layout from plastic.blend..."
& $Blender -b `
  -P ".\sync_portable_blend_layout.py" -- `
  --source $SourceBlend `
  --targets $Targets

Remove-Item -LiteralPath `
  (Join-Path $OutDir "Armadillo__407456ef_contour.blend1"), `
  (Join-Path $OutDir "Armadillo__407456ef_plastic.blend1"), `
  (Join-Path $OutDir "Armadillo__407456ef_nonmanifold_edges.blend1"), `
  (Join-Path $OutDir "Armadillo__407456ef_nonmanifold_regions.blend1") `
  -ErrorAction SilentlyContinue

$Items = @("contour", "plastic", "nonmanifold_edges", "nonmanifold_regions")
foreach ($Item in $Items) {
  $Blend = Join-Path $OutDir "Armadillo__407456ef_$Item.blend"
  $Output = Join-Path $OutDir "Armadillo__407456ef_$Item.png"

  Write-Host "Rendering $Item..."
  & $Blender -b `
    -P ".\render_portable_blend_transparent.py" -- `
    --blend $Blend `
    --output $Output `
    --hide-ground `
    --resolution-x 1100 `
    --resolution-y 1100 `
    --save-blend $Blend
}

Remove-Item -LiteralPath `
  (Join-Path $OutDir "Armadillo__407456ef_contour.blend1"), `
  (Join-Path $OutDir "Armadillo__407456ef_plastic.blend1"), `
  (Join-Path $OutDir "Armadillo__407456ef_nonmanifold_edges.blend1"), `
  (Join-Path $OutDir "Armadillo__407456ef_nonmanifold_regions.blend1") `
  -ErrorAction SilentlyContinue

Write-Host "Done. Outputs:"
foreach ($Item in $Items) {
  Write-Host ("  " + (Join-Path $OutDir "Armadillo__407456ef_$Item.png"))
}
