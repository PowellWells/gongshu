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
PyTorch 2.13.0+cpu
torchvision 0.28.0+cpu
Ultralytics 8.4.128
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
eef_displacement_m: 0.025514109915779952
gripper_displacement: 0.028582722964882325
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
- 原 `stage0_lift_smoke.py` 保持独立，回归结果继续为PASS；最近末端位移 `0.025514 m`，夹爪位移 `0.028583`，有效深度比例 `1.0`。

### 阶段2：YOLO11n-seg预训练感知适配器 — PASS

- `perception\ultralytics_adapter.py` 实现了 `InstanceSegmenter` 协议，只暴露 `model_name` 和 `predict()`，没有训练入口。
- 输入 `RGBDFrame.rgb` 会从RGB显式转换为Ultralytics NumPy接口所需的BGR。
- 推理固定使用CPU、640输入尺寸、`retina_masks=True`，输出原图尺度的 `Detection2D` 边界框和布尔Mask。
- 默认只保留 `bottle` 和 `cup`，置信度阈值和Mask阈值均为 `0.50`。
- 权重存在性和SHA-256会在首次推理前校验；缺失或被篡改时不会加载模型。
- Ultralytics配置隔离在 `artifacts\ultralytics`，同步遥测为关闭状态，没有使用Ultralytics云服务。
- 新增7项感知单元测试和1项官方权重真实冒烟测试；最近一次全量检查为22项测试全部通过。
- CC0 Fiji瓶子照片上检出1个 `bottle`，置信度 `0.853851`，原图Mask为 `319160` 像素。

感知资产保存在Git忽略目录：

```text
artifacts\models\yolo11n-seg.pt
来源：https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11n-seg.pt
SHA-256：55ed65c56c91713d23e8402371c6c49a6fd84f257f7dce452e8d70e41dcbe152

artifacts\perception\bottle_cc0.jpg
来源：https://commons.wikimedia.org/wiki/File:Fiji_water_bottle.jpg
许可：CC0 1.0
SHA-256：7e43c9fc4ac3b658bd7daf2e916d078ae6051bc21b472cd229184f48fe624585
```

许可证边界：Ultralytics代码和官方预训练权重默认采用AGPL-3.0。当前仅按本地个人/研究演示使用；若未来闭源、内部商业或产品化，必须满足AGPL开源义务或先取得Ultralytics商业许可。项目根目录当前没有LICENSE文件，不得擅自声称整个项目已经完成许可证选择。

### 阶段3：Mask + Depth三维定位 — PASS

- `geometry\mask_depth_localizer.py` 实现了 `TargetLocalizer` 协议，输出 `LocalizedTarget`。
- Mask必须与Depth原图尺寸一致；只使用Mask内有限且为正的米制深度。
- `depth_valid_ratio` 在离群点过滤前按Mask总像素计算，默认最低要求为 `0.50`。
- 使用中位数和MAD做确定性深度离群过滤，最小深度带宽为 `0.01 m`。
- 使用OpenCV相机坐标约定和 `CameraIntrinsics` 反投影，再通过经过刚体校验的 `world_from_camera` 转换到世界坐标。
- 点云最多输出4096个行优先确定性样本；质心使用全部过滤后的点计算，不受采样上限影响。
- 新增7项合成几何测试和1项真实robosuite RGB-D集成测试；最近一次全量检查为30项测试全部通过。
- 真实RGB-D中心区域测试的有效深度比例为 `1.0`，输出4096点，世界坐标质心约为 `[-0.04059, -0.00016, 0.81342] m`。
- `geometry` 源码和测试均未导入或读取仿真物体真值，也没有包含PCA抓取规划。

### 阶段4：PCA顶抓候选与几何评分 — PASS

- `grasp\pca_top_grasp.py` 实现了 `GraspPlanner` 协议，每个目标输出一个确定性 `GraspCandidate`。
- 抓取坐标约定：`+X`为夹爪闭合轴，`+Y`为目标长轴/手指方向，`+Z`为向下接近方向；输出旋转为右手正交矩阵。
- PCA仅使用世界坐标点云的XY平面；先做径向分位过滤，并包含完整浮点边界壳层以保持对称形状的主轴稳定。
- PCA轴符号按主分量确定；圆形或近圆形目标固定回退到世界 `+X` 长轴，重复运行结果一致。
- 宽度和长度使用2%至98%投影范围估计，夹爪宽度增加 `0.008 m` 余量，并限制在Panda的 `0.01–0.08 m` 范围。
- 本阶段 `reachable` 只表示夹爪宽度可行，不表示运动学或无碰撞可达；超宽目标仍返回诊断候选，但 `reachable=False` 且评分为0。
- 总评分由感知置信度、深度有效率、点数支撑、几何紧致度和宽度裕量组成，不使用仿真物体真值或机器人状态。
- 新增8项合成长方体/圆柱/离群点/超宽测试和1项真实RGB-D→几何→规划集成测试；最近一次全量检查为39项测试全部通过。
- 真实RGB-D区域生成候选 `top-pca-39-0`：开口 `0.029154 m`、评分 `0.836585`、宽度可行，位置约为 `[-0.01002, -0.00345, 0.84007] m`。

尚未实现Panda控制状态机、无真值端到端抓取闭环、统一首页或四视图工作台。

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

## 6. 下一任务（阶段5 Panda确定性控制）

下一步只实现 `control` 模块的Panda + OSC_POSE确定性抓取状态机：

1. 实现现有 `GraspExecutor` 协议，按 `HOME → PREGRASP → DESCEND → CLOSE → LIFT → RETURN_HOME` 执行，并返回完整 `ExecutionResult` 阶段记录。
2. 为控制层提供最小机器人动作与本体状态接口；允许读取Panda末端和夹爪本体状态，但不得读取目标物体位姿、接触真值或成功标签。
3. 明确把 `world_from_grasp` 的抓取坐标转换成robosuite Panda末端坐标，限制单步平移/旋转动作，并为每个阶段设置步数、误差和超时边界。
4. 在执行前拒绝 `reachable=False`、非刚体姿态、越界宽度或明显超出固定MVP工作区的候选；这仍不是MoveIt式运动规划。
5. 增加替身状态机单元测试和真实Lift环境动作集成测试；真实测试只验证末端/夹爪本体运动与阶段转换，抓取成功评价留到下一阶段。

本任务仍不读取物体真值、不实现成功率评价，也不开发前端。

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

> 请先阅读根目录 README.md、CODEX_HANDOFF.md 和当前Git状态。严格遵守交接文档边界，从“control模块Panda + OSC_POSE确定性抓取状态机”开始；开始修改前先核对现有接口、抓取坐标与robosuite末端坐标约定，不得读取目标物体真值，也不要提前实现成功率评价或前端。
