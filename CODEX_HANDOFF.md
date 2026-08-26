# Vision2Grasp Codex 交接文档

最后更新：2026-08-26

## 1. 项目定位与硬边界

- 正式项目：**公输 Gongshu Robotics · Vision2Grasp**，工作目录为 `G:\Vision2Grasp`。
- 统一门户最终展示 `Jingwei Moment`（UI 视觉识别）与 `公输 Gongshu Robotics`（RGB-D 机器人抓取）两个入口；`Grasp` 只作为技术能力名称。
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
eef_displacement_m: 0.025678614688203403
gripper_displacement: 0.028582724466231085
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
- 原 `stage0_lift_smoke.py` 保持独立，回归结果继续为PASS；最近末端位移 `0.025679 m`，夹爪位移 `0.028583`，有效深度比例 `1.0`。

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
- 抓取坐标约定：`+X`为夹爪闭合轴，`+Y`为目标长轴/夹爪平面正交轴，`+Z`沿手指向下接近；输出旋转为右手正交矩阵。
- PCA仅使用世界坐标点云的XY平面；先做径向分位过滤，并包含完整浮点边界壳层以保持对称形状的主轴稳定。
- PCA轴符号按主分量确定；圆形或近圆形目标固定回退到世界 `+X` 长轴，重复运行结果一致。
- 宽度和长度使用2%至98%投影范围估计，夹爪宽度增加 `0.008 m` 余量，并限制在Panda的 `0.01–0.08 m` 范围。
- 本阶段 `reachable` 只表示夹爪宽度可行，不表示运动学或无碰撞可达；超宽目标仍返回诊断候选，但 `reachable=False` 且评分为0。
- 总评分由感知置信度、深度有效率、点数支撑、几何紧致度和宽度裕量组成，不使用仿真物体真值或机器人状态。
- 新增8项合成长方体/圆柱/离群点/超宽测试和1项真实RGB-D→几何→规划集成测试；最近一次全量检查为39项测试全部通过。
- 真实RGB-D区域生成候选 `top-pca-39-0`：开口 `0.029154 m`、评分 `0.836585`、宽度可行，位置约为 `[-0.01002, -0.00345, 0.84007] m`。

### 阶段5：Panda + OSC_POSE确定性控制 — PASS

- `control\panda_osc_executor.py` 实现了 `GraspExecutor` 协议，固定执行 `HOME → PREGRASP → DESCEND → CLOSE → LIFT → RETURN_HOME`，并记录完整终态。
- 新增 `PandaProprioception` 和最小 `PandaControlBackend` 边界，只包含末端site姿态、夹爪关节位置、时间戳和7维动作，不提供目标物体位姿、接触或成功真值。
- `RobosuiteRGBDSimulator.robot_state()` 明确使用 `robot0_eef_quat_site` 的xyzw四元数；没有使用robosuite 1.5中与末端位置site不一致的旧body四元数。
- PCA抓取坐标与Panda `grip_site` 坐标显式对齐：`+X`为闭合轴、`+Y`为平面正交/目标长轴、`+Z`沿手指向下接近；默认固定坐标变换为单位变换。
- 默认OSC_POSE归一化输入按robosuite配置换算：平移 `±1 → ±0.05 m`、旋转 `±1 → ±0.5 rad`；执行器进一步将单步范数限制为 `0.02 m` 和 `0.15 rad`。
- 候选执行前会拒绝 `reachable=False`、非刚体姿态、Panda宽度范围外、非向下抓取以及固定MVP工作区外的抓取/预抓取/抬升目标。
- 每个阶段有独立步数上限与位置/姿态收敛阈值；失败返回当前阶段和 `FAILED`，不会无限动作。
- `ExecutionResult.success=True` 只表示动作序列完成，消息明确说明尚未评价物体抓取结果。
- 新增5项执行器/配置替身测试、1项控制契约测试、1项仿真本体状态测试和1项真实Lift控制集成测试；最近一次全量检查为47项测试全部通过。
- 真实Lift控制测试只依据机器人本体状态验证完整阶段、末端位移、夹爪位移和返回HOME，不读取物体真值。

### 阶段6：无真值端到端闭环与隔离评价 — PASS

- `simulation\bottle_lift.py` 基于当前冻结的MIT许可robosuite 1.5.2 `Lift` 模型加载模式，使用其自带 `BottleObject` 建立单瓶场景，没有引入新依赖或外部3D资产。
- 瓶身保持robosuite原生网格和碰撞模型；蓝色瓶身、白色标签和红色瓶盖只作用于可视几何，用于让官方COCO预训练YOLO稳定识别，不提供真值Mask。
- 正式场景使用固定 `frontview`、640×480 RGB-D和种子7，并关闭robosuite对象观测；主闭环只能取得RGB-D、机器人本体状态和动作接口。
- 官方 `yolo11n-seg.pt` 在默认 `0.50` 阈值下检出 `bottle`，固定种子置信度 `0.560525`、Mask `1022` 像素。
- `pipeline.py` 实现 `CAPTURE → DETECT → LOCALIZE → PLAN → EXECUTE` 薄编排，只调用现有公共协议，并返回包含各阶段公开输出的 `PipelineRunResult`。
- 检测和候选选择具有确定性排序；无检测、深度定位失败、无可达候选和控制失败均在对应阶段终止并保留诊断。
- 为解决侧视可见曲面质心偏离瓶子轴心的问题，`PCATopGraspPlanner` 仅对“高度明显大于平面宽度”的 `bottle/cup` 点云启用二维圆拟合，以感知点云恢复中心和直径，并在点云75%高度处夹持；非轴对称目标仍走原PCA路线。
- `evaluation\lift.py` 在主闭环前后通过私有窄接口各读取一次瓶子位姿；评价结果不反馈给检测、定位、规划或控制。源码测试确认 `pipeline.py` 不依赖evaluation、真值类型或私有真值方法。
- `run_bottle_pipeline.py` 提供可复现命令行入口并输出JSON，便于下一阶段前端直接消费阶段数据结构。
- 最近一次固定种子闭环结果：深度有效率 `1.0`、定位点数 `923`、候选开口 `0.048243 m`、候选评分 `0.788457`、动作序列完成、瓶子垂直抬升 `0.055189 m`，超过 `0.03 m` 阈值，最终评价 `success=True`。
- 新增圆拟合、编排、失败路径、评价隔离和真实单瓶抓取测试；最近一次全量检查为59项测试全部通过，`compileall`和`pip check`通过。

后端核心闭环和公开前端数据契约已经达到接入条件；前端任务正在 `frontend\` 独立目录迁移统一门户与四视图工作台。

### 阶段7后端桥接：公开 run.json v1 与四视图产物 — PASS

- `visualization\run_artifacts.py` 从 `PipelineRunResult` 和公开 RGB-D 帧导出稳定的 `vision2grasp.run/v1` 文档。
- 冻结 JSON Schema 位于 `contracts\run-v1.schema.json`；字段统一使用 snake_case，媒体路径相对 `run.json` 且统一使用 `/`。
- 默认输出目录为 `artifacts\runs\<run-id>\`，其中包含 `run.json`、RGB 检测图、Depth 热图、Grasp Overlay 和 MuJoCo 最终帧。
- 导出内容只包含公开管线输出，不包含 `evaluation.success`、物体真值位姿或仿真器内部对象。
- 运行目录不可覆盖，run id 会做路径安全校验；失败运行也保持相同顶层字段和明确的 null/空数组。
- CLI `run_bottle_pipeline.py` 仍以隔离评价决定进程退出码，但标准输出和文件中的 JSON 不泄露评价真值。
- 新增4项导出、失败路径、路径安全和契约冻结测试；最近一次全量检查为63项测试全部通过，`compileall`和`pip check`通过。
- 最新真实固定种子导出成功，四张 PNG 均已读取并人工检查。

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

## 6. 下一任务（阶段7 前端消费契约）

下一步正式开始前端接入，不再扩展后端算法范围：

1. 先检查现有未跟踪 `assets\` 的实际用途并保持来源边界；`F:\hotarea-cv` 仍只能作为只读视觉参考。
2. 在 `frontend\` 建立统一入口骨架，同时呈现 `Jingwei Moment` 与 `公输 Gongshu Robotics` 两个入口。
3. 为公输工作台建立最小运行桥接，只消费 `artifacts\runs\<run-id>\run.json` 的v1标准字段，不让页面直接读取仿真内部状态或evaluation私有真值接口。
4. 首批界面至少展示运行状态、阶段时间线、检测类别/置信度、候选位置/开口/评分和最终动作执行状态；RGB、Depth、Grasp、Simulation四视图直接使用v1媒体字段。
5. 保留本地离线/静态使用路径，明确启动命令和失败提示；不得为了界面引入ROS2、云服务或训练流程。

现有后端算法和验收阈值视为前端接入基线，除非前端联调暴露明确缺陷，否则不再修改。

## 7. 后续顺序

```text
simulation正式适配器
→ YOLO11n-seg预训练推理
→ RGB-D三维定位
→ PCA几何抓取规划
→ Panda确定性执行
→ 无真值端到端闭环
→ 统一门户index
→ 四视图、视频、报告和PPT
→ 可选弱光扰动
```

前端只在核心闭环稳定后进入主开发。可借鉴 `F:\hotarea-cv` 的蓝白科研风格、Logo、卡片、SVG叠加、状态时间线和本地静态服务模式，但不得直接修改参考工程，也不要复制其大型标注工作台或任务特定识别逻辑。

## 8. 新聊天启动指令

在新聊天中指定工作目录 `G:\Vision2Grasp`，并先发送：

> 请先阅读根目录 README.md、CODEX_HANDOFF.md 和当前Git状态。后端单瓶闭环已经通过，从“阶段7前端接入起步”开始；先核对未跟踪assets用途和现有入口约束，保持F:\hotarea-cv只读。前端只消费公开PipelineRunResult/JSON，不得读取仿真内部状态或evaluation私有真值接口，也不要扩展后端算法范围。
