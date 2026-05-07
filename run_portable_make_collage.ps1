$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Nadine\Desktop\BlenderToolbox"
python .\portable_render_make_collage.py `
  --list ".\render_presets\portable_noshadow_render_list.csv" `
  --preset-file ".\render_presets\portable_noshadow_preset.json"
