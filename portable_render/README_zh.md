# Non-Manifold Mesh 测地线渲染工作流

这个目录当前只保留一套已经验证可用的方案：

1. 在 `conda` Python 里先计算测地距离
2. 在 Blender 里只负责读取距离并渲染

这就是后续 DCX / QMDF 非流形结果统一使用的方案。

## 当前方法

### 距离计算

使用：

- `potpourri3d`
- `MeshHeatMethodDistanceSolver`
- `use_robust=True`

也就是：

- **heat method**
- **robust / non-manifold Laplacian**
- 直接作用在原始 `final_non_manifold_mesh_restored_to_input_scale.ply` 上

### 渲染

Blender 不再自己计算测地距离。  
Blender 只读取外部保存好的每顶点距离，然后生成：

- contour 图
- plain plastic 图
- `.blend`

## 为什么改成两步

之前尝试过把 `potpourri3d` 直接放进 Blender 进程里调用，但在当前机器上会触发底层崩溃。  
因此当前稳定方案是：

- 外部 Python 求距离
- Blender 只渲染

这样已经在 `0001` 上测试通过。

## 当前保留的脚本

- [compute_heat_distances.py](F:\Code\allresult\portable_geodesic_surface_contours\compute_heat_distances.py)
- [render_surface_contours.py](F:\Code\allresult\portable_geodesic_surface_contours\render_surface_contours.py)

## 环境

- Blender:
  `C:\Program Files\Blender Foundation\Blender 4.1\blender.exe`
- Conda Python:
  `C:\ProgramData\anaconda3\envs\blender\python.exe`

当前需要的 Python 包：

- `numpy`
- `scipy`
- `potpourri3d`

## 第一步：计算 heat geodesic distance

输入必须和后续 Blender 渲染使用的是**同一个 mesh 文件**。

当前脚本针对我们现在的结果文件，主要使用：

- `final_non_manifold_mesh_restored_to_input_scale.ply`

示例：

```powershell
C:\ProgramData\anaconda3\envs\blender\python.exe `
  F:\Code\allresult\portable_geodesic_surface_contours\compute_heat_distances.py `
  --mesh "F:\Code\allresult\NonDetect\DCX\result_gt_poisson100k_final\0001\final_non_manifold_mesh_restored_to_input_scale.ply" `
  --output "F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_heat_distances.npz"
```

输出：

- 一个 `.npz`
- 里面包含：
  - `distances`
  - `source_idx`
  - `vertex_count`
  - `face_count`
  - `mesh_path`
  - `fit_size`
  - `source_xyz`
  - `t_coef`

## 第二步：Blender 渲染

Blender 读取上一步的 `.npz`，再把距离映射到材质里。

示例：

```powershell
& "C:\Program Files\Blender Foundation\Blender 4.1\blender.exe" -b `
  -P "F:\Code\allresult\portable_geodesic_surface_contours\render_surface_contours.py" -- `
  --mesh "F:\Code\allresult\NonDetect\DCX\result_gt_poisson100k_final\0001\final_non_manifold_mesh_restored_to_input_scale.ply" `
  --distance-file "F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_heat_distances.npz" `
  --output "F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_final_contours_heat_true_range.png" `
  --plain-output "F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_final_plastic_heat_true_range.png" `
  --blend "F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_final_heat_true_range.blend"
```

## 当前渲染逻辑

### 1. 颜色按真实全范围距离上色

当前默认：

- `--distance-percentile 100`

也就是：

- 不再像之前那样截到 `94% percentile`
- 直接按真实最大距离归一化

这样最远区域会正常变蓝，不会再因为截断看起来发灰。

### 2. 颜色和等值线分开

当前材质内部使用两个顶点属性：

- `geo_dist_color`
- `geo_dist_line`

含义：

- `geo_dist_color`：用于颜色映射，范围截到 `[0, 1]`
- `geo_dist_line`：用于生成等值线，相位不再和颜色截断绑死

这样可以避免“最远区域整片正好落在线上，所以看起来像灰色”的问题。

### 3. plain 图使用浅蓝塑料材质

当前 plain 材质是论文友好的浅蓝塑料风格，并且已经避免了法线方向不一致导致的大块发黑问题。

## 当前推荐工作流

后续如果你要处理一个新模型，步骤固定为：

1. 对该模型的 `final_non_manifold_mesh_restored_to_input_scale.ply` 运行 `compute_heat_distances.py`
2. 得到对应的 `.npz`
3. 用同一个 mesh + 这个 `.npz` 运行 `render_surface_contours.py`
4. 得到：
   - contour 图
   - plain plastic 图
   - `.blend`

## 当前保留的 0001 结果

- [dcx_0001_heat_distances.npz](F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_heat_distances.npz)
- [dcx_0001_final_contours_heat_true_range.png](F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_final_contours_heat_true_range.png)
- [dcx_0001_final_plastic_heat_true_range.png](F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_final_plastic_heat_true_range.png)
- [dcx_0001_final_heat_true_range.blend](F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_final_heat_true_range.blend)

## 注意事项

1. `compute_heat_distances.py` 和 Blender 渲染时使用的 mesh 必须是同一个文件。
2. 当前距离文件默认是按归一化后的 mesh 坐标选源点，但距离最终是一一对应回这个 mesh 的顶点顺序。
3. 如果以后换别的 mesh 格式或改顶点顺序，必须重新计算对应的 `.npz`。
4. 当前方案是我们之后的默认方案，不再使用之前那些失败的 `proxy_exact` / `graph` / Blender 内部直接 heat 求解路线。
