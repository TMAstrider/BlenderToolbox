$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$blenderExe = "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
$blendFile = Join-Path $repoRoot "test.blend"

if (-not (Test-Path -LiteralPath $blenderExe)) {
    Write-Error "Blender not found: $blenderExe"
}

if (-not (Test-Path -LiteralPath $blendFile)) {
    Write-Host "test.blend not found. Run the render script once first:" -ForegroundColor Yellow
    Write-Host "& '$blenderExe' -b -P default_mesh.py"
    exit 1
}

Write-Host "Opening Blender for view adjustment..."
Start-Process -FilePath $blenderExe -ArgumentList @($blendFile) -WorkingDirectory $repoRoot
