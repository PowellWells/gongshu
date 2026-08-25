# Jingwei Grasp · Vision2Grasp

Vision2Grasp 是 Jingwei Vision 的机器人视觉分支，目标是在 MuJoCo 中演示从 RGB-D 感知到 Franka Panda 抓取执行的完整闭环。

当前状态：阶段 0（MuJoCo / robosuite 生命线）与阶段 1 最小模块化工程骨架已通过，正式 robosuite RGB-D 仿真适配器也已完成。项目暂不包含 YOLO 权重、训练数据或统一前端。

继续开发前请先阅读 [CODEX_HANDOFF.md](CODEX_HANDOFF.md)。

## 模块边界

- `simulation`：仿真环境、相机和机器人动作；当前提供 `RobosuiteRGBDSimulator`。
- `perception`：实例分割推理，只输出检测结果。
- `geometry`：深度反投影、坐标变换和局部点云。
- `grasp`：几何抓取候选与评分。
- `control`：Panda 确定性抓取状态机。
- `visualization`：RGB、Depth、Grasp、Simulation 四视图。
- `evaluation`：误差和成功率；仿真真值仅允许出现在这里。

模块通过 `vision2grasp.contracts` 中的数据对象交换信息，不直接读取其他模块的内部状态。

## 已验证环境

```text
Python 3.12.5
MuJoCo 3.9.0
robosuite 1.5.2
```

## 本地检查

```powershell
$env:PYTHONPATH = "G:\Vision2Grasp\src"
G:\Vision2Grasp\.venv\Scripts\python.exe -m unittest discover -s G:\Vision2Grasp\tests -v
```

阶段 0 复测仍可直接运行：

```powershell
G:\Vision2Grasp\.venv\Scripts\python.exe G:\Vision2Grasp\stage0_lift_smoke.py
```
