#!/usr/bin/env bash
set -euo pipefail

REPO="/c/Users/Nadine/Desktop/BlenderToolbox"
BLENDER="/c/Program Files/Blender Foundation/Blender 4.5/blender.exe"
OUT_DIR="$REPO/renders/portable_Armadillo__407456ef_noshadow_final"

cd "$REPO"

echo "Syncing camera/model/light layout from plastic.blend..."
"$BLENDER" -b \
  -P "./sync_portable_blend_layout.py" -- \
  --source "$OUT_DIR/Armadillo__407456ef_plastic.blend" \
  --targets \
    "$OUT_DIR/Armadillo__407456ef_contour.blend" \
    "$OUT_DIR/Armadillo__407456ef_nonmanifold_edges.blend" \
    "$OUT_DIR/Armadillo__407456ef_nonmanifold_regions.blend"

rm -f \
  "$OUT_DIR/Armadillo__407456ef_contour.blend1" \
  "$OUT_DIR/Armadillo__407456ef_plastic.blend1" \
  "$OUT_DIR/Armadillo__407456ef_nonmanifold_edges.blend1" \
  "$OUT_DIR/Armadillo__407456ef_nonmanifold_regions.blend1"

for item in contour plastic nonmanifold_edges nonmanifold_regions; do
  echo "Rendering $item..."
  "$BLENDER" -b \
    -P "./render_portable_blend_transparent.py" -- \
    --blend "$OUT_DIR/Armadillo__407456ef_${item}.blend" \
    --output "$OUT_DIR/Armadillo__407456ef_${item}.png" \
    --hide-ground \
    --resolution-x 1100 \
    --resolution-y 1100 \
    --save-blend "$OUT_DIR/Armadillo__407456ef_${item}.blend"
done

rm -f \
  "$OUT_DIR/Armadillo__407456ef_contour.blend1" \
  "$OUT_DIR/Armadillo__407456ef_plastic.blend1" \
  "$OUT_DIR/Armadillo__407456ef_nonmanifold_edges.blend1" \
  "$OUT_DIR/Armadillo__407456ef_nonmanifold_regions.blend1"

echo "Done. Outputs:"
for item in contour plastic nonmanifold_edges nonmanifold_regions; do
  echo "  $OUT_DIR/Armadillo__407456ef_${item}.png"
done
