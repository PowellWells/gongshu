# Vision2Grasp Codex 交接文档

最后更新：2026-08-25

## 1. 项目定位与硬边界

- 正式项目：**Jingwei Grasp · Vision2Grasp**，工作目录为 `G:\Vision2Grasp`。
- 展示品牌：**Jingwei Vision**。最终由一个 `index.html` 同时展示 `Jingwei Moment`（UI 视觉识别）与 `Jingwei Grasp`（RGB-D 机器人抓取）两个入口。
- `F:\hotarea-cv` 仅作为只读参考工程，任何任务都不得修改它。
- 用户只有电脑和手机，无真实相机、机械臂或 RGB-D 设备；第一阶段全部使用 MuJoCo 仿真。
- 预算上限 200 元，当前目标实际支出 0 元。
- 禁止范围膨胀：不使用 ROS2、MoveIt、真实机器人、强化学习、GraspNet、Contact-GraspNet、6D Pose/VLA、大模型、自训练检测模型、复杂 Web 前端或付费云服务。
- 主定位和抓取路径不得读取仿真物体真值；真值仅可用于 `evaluation` 下的调试、误差和验收。

## 2. 冻结技术路线

```text
MuJoCo RGB
→ YOLO11n-seg 预训练实例分割（不训练）
→ Mask + MuJoCo Depth
→ 像素反投影与相机/世界坐标变换
→ 局部点云与 PCA
→ 顶抓候选及几何评分
→ Panda + OSC_POSE 确定性状态机
→ 成功/失败评价
```

MVP固定为一个相机、一台 Panda、一个桌面目标、一个顶抓方向和一个动作流程。正式YOLO目标应使用COCO可识别物体（优先瓶子或杯子），不要把普通彩色方块当作YOLO正式目标。

## 3. 当前环境

```text
Windows 11
Python 3.12.5
MuJoCo 3.9.0
robosuite 1.5.2
NumPy 1.26.4
OpenCV 4.11.0
h5py 3.16.0
```

虚拟环境：`G:\Vision2Grasp\.venv`

兼容性结论：MuJoCo 3.10.0 更改了 `mj_fullM` Python接口，会使robosuite 1.5.2控制器初始化失败；本项目必须保持 `mujoco==3.9.0`，除非后续明确升级robosuite并重新完成生命线验收。

robosuite启动时会提示缺少 private macros、`robosuite_models`、mink和Gym。这些是当前Panda + OSC_POSE + RGB-D路径不需要的可选组件，不要为消除警告擅自安装。

## 4. 已完成状态

### 阶段0：生命线测试 — PASS

入口：`stage0_lift_smoke.py`

最近一次结果：

```text
environment: Lift
robot: Panda
controller: OSC_POSE
RGB: 480 x 640 x 3
Depth: 480 x 640
depth_valid_ratio: 1.0
eef_displacement_m: 0.02576095635002532
gripper_displacement: 0.02858272079987
status: PASS
```

生成产物保存在 `artifacts\stage0`，该目录已被Git忽略。阶段0脚本为使位移超过验收阈值，将Z动作设置为 `0.10` 并执行20步；验收标准仍为末端位移大于 `0.01 m`、夹爪位移大于 `0.005`。

### 阶段1：最小工程骨架 — PASS

- `src\vision2grasp` 已包含 `simulation`、`perception`、`geometry`、`grasp`、`control`、`visualization`、`evaluation` 七个解耦模块。
- `contracts.py` 定义跨模块数据契约。
- 每个模块目前只定义协议边界，没有伪造功能实现。
- 仿真真值类型只位于 `evaluation\ground_truth.py`，未从根包导出。
- `configs\default.toml` 冻结当前仿真版本与MVP默认值。
- 模块导入和既有7项契约测试继续通过。

### 阶段2前置：正式simulation适配器 — PASS

- `simulation\robosuite_adapter.py` 实现了 `RGBDSimulator` 协议。
- `reset()`、`capture()` 和 `apply_action()` 均返回合法 `RGBDFrame`。
- RGB来自同步robosuite观测，Depth通过 `get_real_depth_map()` 转换为米制 `float32`。
- 相机内参来自 `get_camera_intrinsic_matrix()`，`world_from_camera` 来自 `get_camera_extrinsic_matrix()`，没有手填标定矩阵。
- 显式传入 `reset(seed=...)` 时会重建环境，确保robosuite 1.5.2确实应用该种子。
- 动作形状和有限数值会被校验；`close()`可重复调用。
- 适配器公共接口不提供原始仿真器或物体真值。
- 新增6项替身单元测试和1项真实Lift集成测试；最近一次完整检查为14项测试全部通过，`compileall`和`pip check`通过。
- 原 `stage0_lift_smoke.py` 保持独立，回归结果继续为PASS；最近末端位移 `0.025690 m`，夹爪位移 `0.028583`，有效深度比例 `1.0`。

尚未安装PyTorch或Ultralytics，尚未下载 `yolo11n-seg.pt`，尚未创建统一首页或四视图工作台。

## 5. 当前验证命令

```powershell
$env:PYTHONPATH = "G:\Vision2Grasp\src"
& "G:\Vision2Grasp\.venv\Scripts\python.exe" -m compileall -q "G:\Vision2Grasp\src" "G:\Vision2Grasp\tests"
& "G:\Vision2Grasp\.venv\Scripts\python.exe" -m unittest discover -s "G:\Vision2Grasp\tests" -v
& "G:\Vision2Grasp\.venv\Scripts\python.exe" -m pip check
```

阶段0回归：

```powershell
& "G:\Vision2Grasp\.venv\Scripts\python.exe" "G:\Vision2Grasp\stage0_lift_smoke.py"
```

## 6. 下一任务（阶段2感知）

下一步实现 `perception` 模块的最小预训练实例分割适配器：

1. 安装并冻结与Python 3.12兼容的CPU版PyTorch和Ultralytics；安装前核对官方兼容性与许可证，不引入训练依赖或GPU要求。
2. 下载并校验官方 `yolo11n-seg.pt`，不训练或微调模型。
3. 实现现有 `InstanceSegmenter` 协议，将原图尺度上的类别、置信度、边界框和布尔Mask转换为 `Detection2D`。
4. 只保留目标类别选择和最低置信度等必要配置，不将几何定位或仿真真值混入感知模块。
5. 增加替身单元测试和一次真实预训练权重冒烟测试；正式目标应使用COCO可识别的瓶子或杯子图像。

本任务仍不开发前端，不进行RGB-D三维定位或抓取规划。

## 7. 后续顺序

```text
simulation正式适配器
→ YOLO11n-seg预训练推理
→ RGB-D三维定位
→ PCA几何抓取规划
→ Panda确定性执行
→ 无真值端到端闭环
→ Jingwei Vision统一index
→ 四视图、视频、报告和PPT
→ 可选弱光扰动
```

前端只在核心闭环稳定后进入主开发。可借鉴 `F:\hotarea-cv` 的蓝白科研风格、Logo、卡片、SVG叠加、状态时间线和本地静态服务模式，但不得直接修改参考工程，也不要复制其大型标注工作台或任务特定识别逻辑。

## 8. 新聊天启动指令

在新聊天中指定工作目录 `G:\Vision2Grasp`，并先发送：

> 请先阅读根目录 README.md、CODEX_HANDOFF.md 和当前Git状态。严格遵守交接文档边界，从“perception模块最小预训练实例分割适配器”开始；开始修改前先核对现有接口、测试、依赖兼容性和许可证，不要训练模型或开发前端。
