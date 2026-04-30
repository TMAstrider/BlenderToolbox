# BlenderToolbox 本地使用说明

这个仓库是一个给 Blender 用的 Python 渲染脚本库，不是直接双击使用的 `.blend` 工程。

当前这台机器已经配置完成，可以直接运行。

## 当前环境

- Blender 路径：`C:\Program Files\Blender Foundation\Blender 4.5\blender.exe`
- 已将 `blendertoolbox` 安装到 Blender 的模块目录
- 已验证默认示例可以正常渲染

## 最简单的运行方法

在仓库根目录打开 PowerShell，执行：

```powershell
& 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' -b -P default_mesh.py
```

如果要运行可自定义材质和灯光的模板脚本：

```powershell
& 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' -b -P template.py
```

## 当前渲染结果位置

- 渲染图片：`C:\Users\Nadine\Desktop\BlenderToolbox\default_mesh.png`
- Blender 场景：`C:\Users\Nadine\Desktop\BlenderToolbox\test.blend`

## 如何换成你自己的模型

编辑 [default_mesh.py](C:/Users/Nadine/Desktop/BlenderToolbox/default_mesh.py:13) 里的这些参数：

- `mesh_path`
- `mesh_position`
- `mesh_rotation`
- `mesh_scale`

例如：

```python
"mesh_path": "C:/path/to/your/model.obj"
```

支持的常见输入格式以仓库现有脚本为主，默认流程最稳的是 `.obj` 和 `.ply`。

## 推荐工作流

1. 先运行一次：

```powershell
& 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' -b -P default_mesh.py
```

2. 打开生成的 `test.blend`
3. 在 Blender 里调整模型的位置、旋转、缩放
4. 把 Blender 里调好的参数抄回 `default_mesh.py`
5. 再运行一次脚本，输出最终图片

## 打开 Blender 场景

可以直接双击：

- [test.blend](C:/Users/Nadine/Desktop/BlenderToolbox/test.blend)

或者在 PowerShell 里执行：

```powershell
& 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' 'C:\Users\Nadine\Desktop\BlenderToolbox\test.blend'
```

## 注意事项

- 请在仓库根目录运行脚本，因为很多路径写的是相对路径
- 当前稳定用法是 `blender.exe -b -P xxx.py`
- 系统自带的 `python 3.12/3.15` 不能直接运行这些脚本，因为它们没有可用的 `bpy`
- 这个仓库原本主要针对 Blender 4.3，当前已经做了一个 Blender 4.5 的兼容修复，默认流程可以正常用

## 常用命令

渲染默认网格：

```powershell
& 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' -b -P default_mesh.py
```

渲染模板：

```powershell
& 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' -b -P template.py
```

运行点云示例：

```powershell
& 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' -b -P default_point_cloud.py
```



```
python render_from_list.py \
    --list meshes/render_list.csv \
    --meshes-root "meshes/20260427_current3_ours_nsh_multipull_casefix_multipull80k/models" \
    --adjust-root adjust_scenes \
    --output-root renders/manifold_flat_ao \
    --preset-file render_presets/cycles_flat_ao_strip.json \
    --max-parallel 2
```


```
 python render_from_list.py --list meshes\render_list.csv --meshes-root "meshes\20260427_current3_ours_nsh_multipull_casefix_multipull80k\models" --adjust-root adjust_scenes --output-root renders\manifold_flat_ao --preset-file render_presets\cycles_flat_ao_strip.json --max-parallel 2
```