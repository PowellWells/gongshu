# 公输 Gongshu Robotics · Vision2Grasp

Vision2Grasp 是公输 Gongshu Robotics 的机器人视觉项目，目标是在 MuJoCo 中演示从 RGB-D 感知到 Franka Panda 抓取执行的完整闭环。

当前状态：MuJoCo / robosuite 生命线、模块化工程骨架、正式 RGB-D 仿真适配器、YOLO11n-seg 预训练感知、Mask + Depth 三维定位、PCA / 圆拟合顶抓规划、Panda 确定性执行和单瓶端到端闭环均已通过。项目不训练模型，YOLO 权重保存在 Git 忽略的 `artifacts` 目录；后端核心闭环已达到前端接入条件。

继续开发前请先阅读 [CODEX_HANDOFF.md](CODEX_HANDOFF.md)。

## 模块边界

- `simulation`：仿真环境、相机、机器人动作和机器人本体状态；当前提供 `RobosuiteRGBDSimulator`。
- `perception`：实例分割推理，只输出检测结果；当前提供 CPU 版 `UltralyticsYOLOSegmenter`。
- `geometry`：深度反投影、坐标变换和局部点云；当前提供 `MaskDepthTargetLocalizer`。
- `grasp`：几何抓取候选与评分；当前提供 `PCATopGraspPlanner`。
- `control`：Panda 确定性抓取状态机；当前提供 `PandaOSCGraspExecutor`。
- `pipeline`：无真值反馈的单目标编排；当前提供 `Vision2GraspPipeline`。
- `visualization`：RGB、Depth、Grasp、Simulation 四视图。
- `evaluation`：执行后误差和成功率；仿真真值仅允许通过这里的隔离评价器读取。

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

固定种子单瓶闭环：

```powershell
G:\Vision2Grasp\.venv\Scripts\python.exe G:\Vision2Grasp\run_bottle_pipeline.py
```

该命令会在 `artifacts/runs/<run-id>/` 写入前端可直接消费的 `run.json`，以及 RGB 检测、深度、抓取叠加和 MuJoCo 结果四张 PNG。标准输出也是同一份 `vision2grasp.run/v1` JSON；其中只包含公开模块输出，不含隔离评价真值。退出码 `0` 仍表示瓶子垂直抬升达到 `0.03 m` 的后端验收阈值。

冻结的前端契约位于 [contracts/run-v1.schema.json](contracts/run-v1.schema.json)。媒体路径均相对于 `run.json`，统一使用 `/` 分隔符。

## 启动统一门户

先从项目根目录启动本地静态服务：

```powershell
G:\Vision2Grasp\.venv\Scripts\python.exe -m http.server 8765 --bind 127.0.0.1 --directory G:\Vision2Grasp\frontend
```

然后打开 `http://127.0.0.1:8765/`，进入“公输 Gongshu”工作台，点击“导入运行目录”，选择完整的 `artifacts\runs\<run-id>` 文件夹。页面会校验 `vision2grasp.run/v1`，并读取其中的 `run.json` 和四个相对媒体文件；无需上传到云端。
