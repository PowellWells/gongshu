# Jingwei Grasp · Vision2Grasp

Vision2Grasp 是 Jingwei Vision 的机器人视觉分支，目标是在 MuJoCo 中演示从 RGB-D 感知到 Franka Panda 抓取执行的完整闭环。

当前状态：MuJoCo / robosuite 生命线、模块化工程骨架、正式 RGB-D 仿真适配器、YOLO11n-seg 预训练感知、Mask + Depth 三维定位和 PCA 顶抓规划均已通过。项目不训练模型，YOLO 权重保存在 Git 忽略的 `artifacts` 目录，尚未开发统一前端。

继续开发前请先阅读 [CODEX_HANDOFF.md](CODEX_HANDOFF.md)。

## 模块边界

- `simulation`：仿真环境、相机和机器人动作；当前提供 `RobosuiteRGBDSimulator`。
- `perception`：实例分割推理，只输出检测结果；当前提供 CPU 版 `UltralyticsYOLOSegmenter`。
- `geometry`：深度反投影、坐标变换和局部点云；当前提供 `MaskDepthTargetLocalizer`。
- `grasp`：几何抓取候选与评分；当前提供 `PCATopGraspPlanner`。
- `control`：Panda 确定性抓取状态机。
- `visualization`：RGB、Depth、Grasp、Simulation 四视图。
- `evaluation`：误差和成功率；仿真真值仅允许出现在这里。

模块通过 `vision2grasp.contracts` 中的数据对象交换信息，不直接读取其他模块的内部状态。

## 已验证环境

```text
Python 3.12.5
MuJoCo 3.9.0
robosuite 1.5.2
PyTorch 2.13.0+cpu
torchvision 0.28.0+cpu
Ultralytics 8.4.128
```

## 第三方许可证边界

Ultralytics 软件和官方 YOLO11 预训练权重默认采用 AGPL-3.0。当前只按本地个人 / 研究演示用途使用；如果未来需要闭源、内部商业或产品化部署，必须先确认能够履行 AGPL-3.0 的开源义务，或取得 Ultralytics 商业许可。本仓库目前没有擅自替整个项目选择许可证。

## 本地检查

```powershell
$env:PYTHONPATH = "G:\Vision2Grasp\src"
G:\Vision2Grasp\.venv\Scripts\python.exe -m unittest discover -s G:\Vision2Grasp\tests -v
```

阶段 0 复测仍可直接运行：

```powershell
G:\Vision2Grasp\.venv\Scripts\python.exe G:\Vision2Grasp\stage0_lift_smoke.py
```
