$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Nadine\Desktop\BlenderToolbox"
python .\portable_render_batch_from_list.py `
  --list ".\render_presets\portable_noshadow_render_list.csv" `
  --output-root ".\renders" `
  --resolution-x 1100 `
  --resolution-y 1100
