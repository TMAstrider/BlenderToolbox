# 当前最终渲染方案

这份文档记录目前确认保留、后续继续沿用的非流形网格渲染流程。

## 1. 输入模型

每个模型统一使用这个文件作为渲染输入：

- `final_non_manifold_mesh_restored_to_input_scale.ply`

例如 `DCX 0001`：

- `F:\Code\allresult\NonDetect\DCX\result_gt_poisson100k_final\0001\final_non_manifold_mesh_restored_to_input_scale.ply`

## 2. 每个模型的最终输出

每个模型固定生成四张图：

1. 测地线等值线图
2. 纯色塑料图
3. 非流形边高亮图
4. 非流形阻断后的区域分块图

同时保留对应的 `.blend` 文件，方便后续手动微调。

批处理时的目录结构统一为：

- `outputs\DCX\<模型id>\heat_distances.npz`
- `outputs\DCX\<模型id>\contour.png`
- `outputs\DCX\<模型id>\contour.blend`
- `outputs\DCX\<模型id>\plastic.png`
- `outputs\DCX\<模型id>\plastic.blend`
- `outputs\DCX\<模型id>\nonmanifold_edges.png`
- `outputs\DCX\<模型id>\nonmanifold_edges.blend`
- `outputs\DCX\<模型id>\nonmanifold_regions.png`
- `outputs\DCX\<模型id>\nonmanifold_regions.blend`

以 `dcx_0001` 为例，当前保留的正式结果是：

- `dcx_0001_final_contours_heat_true_range.png`
- `dcx_0001_final_contours_heat_true_range.blend`
- `dcx_0001_final_plastic_heat_true_range.png`
- `dcx_0001_final_plastic_heat_true_range.blend`
- `dcx_0001_final_nonmanifold_edges.png`
- `dcx_0001_final_nonmanifold_edges.blend`
- `dcx_0001_final_nonmanifold_regions.png`
- `dcx_0001_final_nonmanifold_regions.blend`
- `dcx_0001_heat_distances.npz`

## 3. 当前保留的脚本

现在正式流程只保留两个脚本：

- `compute_heat_distances.py`
- `render_surface_contours.py`

其余旧测试脚本、测试结果和备份结果都已经清理。

## 4. 测地距离计算

测地距离在 Blender 外部先计算好，Blender 只负责读取结果并渲染。

当前方法：

- 使用 `potpourri3d.MeshHeatMethodDistanceSolver`
- `use_robust=True`
- 直接对最终非流形 mesh 计算 heat geodesic distance

输出是一个 `.npz` 文件，里面保存每个顶点的距离和相关元数据。

示例命令：

```powershell
C:\ProgramData\anaconda3\envs\blender\python.exe `
  F:\Code\allresult\portable_geodesic_surface_contours\compute_heat_distances.py `
  --mesh "F:\Code\allresult\NonDetect\DCX\result_gt_poisson100k_final\0001\final_non_manifold_mesh_restored_to_input_scale.ply" `
  --output "F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_heat_distances.npz"
```

## 5. Blender 渲染

Blender 读取：

- 同一个 mesh
- 对应的 `.npz` 距离文件

然后一次性生成四张正式结果图和四个 `.blend` 文件。

示例命令：

```powershell
& "C:\Program Files\Blender Foundation\Blender 4.1\blender.exe" -b `
  -P "F:\Code\allresult\portable_geodesic_surface_contours\render_surface_contours.py" -- `
  --mesh "F:\Code\allresult\NonDetect\DCX\result_gt_poisson100k_final\0001\final_non_manifold_mesh_restored_to_input_scale.ply" `
  --distance-file "F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_heat_distances.npz" `
  --output "F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_final_contours_heat_true_range.png" `
  --plain-output "F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_final_plastic_heat_true_range.png" `
  --nonmanifold-output "F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_final_nonmanifold_edges.png" `
  --regions-output "F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_final_nonmanifold_regions.png" `
  --blend "F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_final_contours_heat_true_range.blend" `
  --plain-blend "F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_final_plastic_heat_true_range.blend" `
  --nonmanifold-blend "F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_final_nonmanifold_edges.blend" `
  --regions-blend "F:\Code\allresult\portable_geodesic_surface_contours\outputs\dcx_0001_final_nonmanifold_regions.blend" `
  --distance-percentile 100 `
  --samples 96
```

## 6. 当前固定的视觉方案

当前确认保留的视觉标准如下：

- 最终背景是纯白
- 使用很大的水平地面
- 地面只保留阴影，不保留倒影
- 底部有轻微但可见的接触阴影，用来增强立体感
- 没有竖直背景板
- 不加 bevel
- 不加 subdivision
- 不加 remesh
- 不改已有的归一化逻辑
- 不改已有的相机 `look_at` 逻辑
- 继续使用当前稳定的 flat shading / stable normals 流程

灯光方向：

- 主光从前方偏左上打下来
- 补光很弱
- 顶部/后方辅助光也很弱

目标是：

- 颜色协调
- 论文友好
- 底部有一点阴影增加体积感
- 但不要出现很重的内部黑块

## 7. 三张图的含义

### 7.1 测地线等值线图

- 底色由 heat geodesic distance 决定
- 等值线也由同一个距离场生成
- 当前使用 `distance-percentile = 100`
- 也就是按真实全范围上色，不再截断

### 7.2 纯色塑料图

- 使用统一的浅蓝色塑料风格材质
- 不叠加测地线
- 用于清楚展示模型外形

### 7.3 非流形边高亮图

- 主体材质与纯色图保持一致
- 只额外高亮非流形边
- 边界边不高亮

非流形边定义：

- 一条边若被至少 `3` 个三角面共用，则判定为非流形边

### 7.4 非流形阻断后的区域分块图

- 先在 Python 中按三角面建立面邻接关系
- 如果两面共享的是普通二面边，则允许洪泛跨越
- 如果两面之间是非流形边，则禁止洪泛跨越
- 最终每个面连通块作为一个区域
- 每个区域赋一个固定离散颜色
- 该图不改 mesh 几何，只是基于拓扑关系做区域染色

## 8. 使用注意事项

- 计算 heat distance 时使用的 mesh，必须和 Blender 渲染时使用的 mesh 完全一致。
- 如果顶点顺序发生变化，必须重新计算 `.npz`。
- 当前这套流程就是后续默认保留方案，不再沿用之前的测试脚本和测试结果。
