# 批量渲染流程

## 环境要求

- **Blender 4.5**：`C:\Program Files\Blender Foundation\Blender 4.5\blender.exe`
- **Python 依赖**：`numpy`, `scipy`, `Pillow`, `plyfile`
- 所有命令在仓库根目录 `BlenderToolbox` 下执行（PowerShell）

---

## 工具概览

| 文件 | 作用 | 运行方式 |
|------|------|----------|
| `make_adjust_scene.py` | 从单个 mesh 生成 .blend 调整场景 | `blender -b -P` |
| `open_view_adjust.ps1` | 用 Blender GUI 打开 test.blend 手动调整 | PowerShell 直接运行 |
| `export_selected_transform.py` | 从 .blend 中导出 mesh/camera 参数为 JSON | `blender -b -P`（被其他脚本调用） |
| `render_eval_set.py` | 核心渲染脚本：渲染一个目录下的所有 mesh | `blender -b -P`（被其他脚本调用） |
| `render_from_adjust_blend.py` | 单模型渲染：读取调整好的 .blend → 渲染所有方法 | `python` |
| `render_eval_batch.py` | 批量渲染：从模型列表批量渲染 | `python` |
| `render_from_list.py` | **推荐**：从 CSV 批量管理（含两阶段：生成 blend + 渲染） | `python` |
| `clean_nonmanifold.py` | 清理非流形面：沿非流形边分割并去除离群组件 | `python` |
| `export_components.py` | 调试用：将网格按非流形边拆分为独立组件导出 | `python` |

### 辅助文件

| 文件 | 作用 |
|------|------|
| `render_presets/*.json` | 渲染预设（材质、光照、分辨率、拼图配置） |
| `render_presets/*.txt` | 模型列表（供 `render_eval_batch.py` 使用） |
| `meshes/dataset_map.json` | 数据集映射配置（目录结构和 strip 排列顺序） |
| `meshes/render_list.csv` | 批量渲染任务表（供 `render_from_list.py` 使用） |

---

## 工作流一：单模型（手动调整）

适用于精细控制每个模型的姿态和构图。

### 第一步：生成调整用 blend 文件

```powershell
blender -b -P make_adjust_scene.py -- `
  --mesh-path "meshes\<数据集>\models\<model_name>\ours_mls.ply" `
  --blend-out "adjust_scenes\<类别>\<model_name>\<model_name>_ours_mls.blend" `
  --recalc-normals
```

参数说明：
- `--mesh-path`：输入 mesh 路径（.ply / .obj）
- `--blend-out`：输出 .blend 路径
- `--material`：材质类型，默认 `monotone`，可选 `flat` / `flat_ao` / `ao` / `ceramic` / `plastic` / `matte`
- `--recalc-normals`：重新计算法线
- `--resolution` / `--samples`：分辨率和采样数
- `--location` / `--rotation` / `--scale`：初始 mesh 变换

### 第二步：手动调整模型位置

1. 用 Blender 打开生成的 `.blend` 文件
2. 按 `Z` → **Rendered** 预览效果
3. 选中 mesh 对象，调整 **Location / Rotation / Scale**（不要动相机）
4. **Ctrl+S** 保存

### 第三步：渲染全部方法

```powershell
python render_from_adjust_blend.py `
  --adjust-blend "adjust_scenes\<类别>\<model_name>\<model_name>_ours_mls.blend" `
  --model-dir "meshes\<数据集>\models\<model_name>" `
  --output-dir "renders\<model_name>" `
  --preset-file "render_presets\cycles_default_strip.json"
```

输出结构：
```
renders\<model_name>\
  gt_pointcloud.png
  nsh.png
  multipull.png
  ours_mls.png
  strip_1x4.png          ← 多方法横向拼图
  run_summary.json       ← 渲染参数记录
```

---

## 工作流二：批量渲染（CSV 驱动）

适用于大规模评估，通过 CSV 管理所有模型的渲染状态。

### 1. 准备 CSV

`meshes/render_list.csv` 格式：

| 字段 | 说明 |
|------|------|
| `dataset` | 数据集名称，对应 `dataset_map.json` 中的 key |
| `model` | 模型目录名 |
| `blend` | `todo` = 需生成 blend，`done` = 已生成可渲染 |
| `clean` | `yes` = 使用 `ours_mls_clean.ply` 替代 `ours_mls.ply` |
| `rendered` | `done` = 跳过（已完成） |

### 2. 配置 dataset_map.json

```json
{
  "20260427_current3": {
    "dir": "20260427_current3_ours_nsh_multipull_casefix_multipull80k",
    "output_subdir": "current3",
    "strip_order": ["gt_pointcloud", "nsh", "multipull", "ours_mls"],
    "strip_labels": {
      "gt_pointcloud": "GT",
      "nsh": "NSH",
      "multipull": "MultiPull",
      "ours_mls": "Ours"
    }
  }
}
```

### 3. 运行

```powershell
python render_from_list.py `
  --list         meshes/render_list.csv `
  --meshes-root  meshes `
  --output-root  renders `
  --adjust-root  adjust_scenes `
  --preset-file  render_presets/cycles_flat_ao_strip.json `
  --max-parallel 3
```

工作流：
- **Phase 1**：`blend=todo` 的行 → 自动调用 `make_adjust_scene.py` 生成 .blend
- **手动步骤**：在 Blender 中打开生成的 .blend，调整模型位置后保存
- 将 CSV 中对应行的 `blend` 改为 `done`
- **Phase 2**：`blend=done` 的行 → 自动提取变换参数并渲染
- 渲染完成后自动生成每模型 strip 和每数据集 ranked_strip

---

## 工作流三：简单批量（模型列表）

适用于无需手动调整的快速批量渲染。

```powershell
python render_eval_batch.py `
  --models-root  "final_mesh\20260424_current3\models" `
  --model-list   "render_presets\sample_models_10.txt" `
  --preset-file  "render_presets\cycles_default_strip.json" `
  --output-root  "renders\sample10"
```

模型列表文件每行一个模型目录名。

---

## 渲染预设说明

预设 JSON 文件包含两部分：`render_args`（渲染参数）和 `strip_1x4`（拼图配置）。

### 常用 render_args

| 参数 | 说明 | 示例值 |
|------|------|--------|
| `resolution` | 输出分辨率 | 1024 |
| `samples` | Cycles 采样数 | 200 |
| `mesh_rgb` | 模型颜色 | `[0.4, 0.7, 0.85]` |
| `material` | 材质类型 | `monotone` / `flat_ao` / `flat` |
| `point_size` | 点云球大小 | 0.006 |
| `engine` | 渲染引擎 | `cycles` / `workbench` |
| `light_angle` | 日光角度 | `[6.0, -30.0, -155.0]` |
| `light_strength` | 日光强度 | 2.0 |
| `light_color` | 日光颜色 | `[1.0, 1.0, 1.0]` |

### 材质类型速查

| material | 效果 | 适用场景 |
|----------|------|----------|
| `monotone` | 三阶灰度 + 轮廓线 | 论文风格展示 |
| `flat_ao` | 环境光遮蔽 + 微高光 | 几何对比（推荐） |
| `flat` | 纯色 + 微高光 | 简洁展示 |
| `ao` | 纯环境光遮蔽 | 深度/几何预览 |
| `plastic` | 塑料质感 | 一般展示 |
| `ceramic` | 陶瓷质感 | 光滑表面 |
| `matte` | 哑光 | 无高光展示 |

### strip_1x4 拼图配置

```json
{
  "strip_1x4": {
    "margin": 0,
    "output_name": "strip_1x4.png",
    "items": [
      {"file": "gt_pointcloud.png"},
      {"file": "nsh.png"},
      {"file": "multipull.png"},
      {"file": "ours_mls.png"}
    ]
  }
}
```

---

## 清理非流形网格

渲染前清理网格上的漂浮碎片：

```powershell
python clean_nonmanifold.py `
  --mesh        "meshes\...\ours_mls.ply" `
  --pointcloud  "meshes\...\gt_pointcloud.ply" `
  --output      "meshes\...\ours_mls_clean.ply" `
  --threshold   0.004 `
  --filter-mode novel
```

参数说明：
- `--threshold`：GT 距离阈值，低于此距离的顶点被认为有效
- `--filter-mode novel`：贪婪保留能够覆盖新 GT 点的组件（推荐）
- `--filter-mode dist`：保留任何顶点在阈值内的组件
- `--min-novel-gt`：novel 模式下组件至少需要覆盖的新 GT 点数
- `--min-faces`：额外过滤掉面数少于此值的组件

### 调试组件

```powershell
python export_components.py `
  --mesh   "meshes\...\ours_mls.ply" `
  --outdir "debug_components\model_name"
```

将每个连通分量导出为独立 PLY 文件，方便在 MeshLab 中逐个检查。

---

## 渲染参数记录

每次渲染后会在输出目录生成 `run_summary.json`，记录完整的渲染参数，便于复现：

```json
{
  "adjust_blend": "...",
  "model_dir": "...",
  "final_render_args": { ... },
  "output_dir": "..."
}
```

## Armadillo 完整示例

```powershell
# 第一步：生成 blend
blender -b -P make_adjust_scene.py -- `
  --mesh-path "meshes\20260427_current3_ours_nsh_multipull_casefix_multipull80k\models\Armadillo__407456ef\ours_mls.ply" `
  --blend-out "adjust_scenes\manifold\Armadillo_407456ef\Armadillo__407456ef_ours_mls.blend" `
  --recalc-normals

# 第二步：用 Blender 打开 .blend，手动调整模型位置，Ctrl+S 保存

# 第三步：渲染
python render_from_adjust_blend.py `
  --adjust-blend "adjust_scenes\manifold\Armadillo_407456ef\Armadillo__407456ef_ours_mls.blend" `
  --model-dir "meshes\20260427_current3_ours_nsh_multipull_casefix_multipull80k\models\Armadillo__407456ef" `
  --output-dir "renders\Armadillo__407456ef" `
  --preset-file "render_presets\cycles_default_strip.json"
```
