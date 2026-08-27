# Vision2Grasp Codex 交接文档

最后更新：2026-08-27

## 1. 项目定位与硬边界

- 正式平台：**XUANSHU LAB · 玄枢实验室**，工作目录仍为 `G:\Vision2Grasp`；`Vision2Grasp` 现在是公输 Workspace 的领域项目名，不再代表整个桌面平台。
- v0.1 固定三个 Workspace：`Jingwei Moment`、`Gongshu Vision2Grasp` 和 `Hetu Preview`。
- `F:\hotarea-cv` 仅作为只读参考工程，任何任务都不得修改它。
- 用户有 Android 手机和电脑自带摄像头，但没有机械臂或 RGB-D 设备；当前真实场景只使用普通 RGB，并以固定相机、尺子和人工四点标定恢复桌面平面尺度。
- 预算上限 200 元，当前目标实际支出 0 元。
- 禁止范围膨胀：不使用 ROS2、MoveIt、真实机器人、强化学习、GraspNet、Contact-GraspNet、6D Pose/VLA、大模型、自训练检测模型、复杂 Web 前端或付费云服务。
- 主定位和抓取路径不得读取仿真物体真值；真值仅可用于 `evaluation` 下的调试、误差和验收。

## 2. 冻结技术路线

```text
Real Scene（默认）：PC / Android RGB / 单张照片
→ YOLO11n-seg bottle 实例分割（不训练）
→ 尺子 + 人工四点桌面标定
→ 平面 X/Y、方向、尺寸和三个顶抓候选
→ 真实画面叠加与来源标注

Simulation（保留）：MuJoCo RGB-D
→ Mask + Depth 三维定位
→ PCA / 圆拟合顶抓规划
→ Panda + OSC_POSE 确定性状态机
→ 隔离成功/失败评价
```

当前真实 MVP 固定只支持 `bottle`。稳定后才能依次增加 `cup`、`banana`。普通 RGB 输入不得伪装成 RGB-D：当前只输出标定平面上的米制 X/Y；方向、目标宽度和夹爪开口必须标为估计值，不输出虚假 Z。

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

后端核心闭环、公开前端数据契约和 `frontend\` 统一门户均已完成联合接入。

### 阶段7后端桥接：公开 run.json v1 与四视图产物 — PASS

- `visualization\run_artifacts.py` 从 `PipelineRunResult` 和公开 RGB-D 帧导出稳定的 `vision2grasp.run/v1` 文档。
- 冻结 JSON Schema 位于 `contracts\run-v1.schema.json`；字段统一使用 snake_case，媒体路径相对 `run.json` 且统一使用 `/`。
- 默认输出目录为 `artifacts\runs\<run-id>\`，其中包含 `run.json`、RGB 检测图、Depth 热图、Grasp Overlay 和 MuJoCo 最终帧。
- 导出内容只包含公开管线输出，不包含 `evaluation.success`、物体真值位姿或仿真器内部对象。
- 运行目录不可覆盖，run id 会做路径安全校验；失败运行也保持相同顶层字段和明确的 null/空数组。
- CLI `run_bottle_pipeline.py` 仍以隔离评价决定进程退出码，但标准输出和文件中的 JSON 不泄露评价真值。
- 新增4项导出、失败路径、路径安全和契约冻结测试；最近一次全量检查为63项测试全部通过，`compileall`和`pip check`通过。
- 最新真实固定种子导出成功，四张 PNG 均已读取并人工检查。

### 阶段7前端：统一门户与公输工作台 — PASS

- 前端全部位于 `frontend\`，包含玄枢统一门户、Jingwei Moment 与公输 Gongshu Robotics 工作台；`F:\hotarea-cv` 不再是交付源。
- 公输工作台只接受 `schema_version == "vision2grasp.run/v1"`，不长期兼容旧字段别名。
- 根目录 `Start-Vision2Grasp.cmd` 已升级为统一应用启动器：启动或复用本地服务并直接打开公输工作台，默认进入 Real Scene Mode；仿真改为用户在 Simulation Mode 中按需运行。
- 自动发布区为 Git 忽略的 `frontend\runtime\`；`vision2grasp.launcher/v1` 的 `latest.json` 只指向公开 `run.json v1`，不包含评价真值。
- 通过目录选择器读取完整 run 文件夹，依据 `webkitRelativePath` 安全解析 `run.json` 的相对媒体路径，并用 Blob URL 展示四视图；清空或离开页面时释放 URL。
- 真实固定种子目录联合测试已通过：四张 640×480 图片全部加载，目标类别/置信度、世界坐标、RPY、夹爪开口、候选评分、可达性、执行状态和13个事件均正确。
- 浏览器控制台无 warning/error；修复了真实媒体显示后空态文案仍覆盖图片的问题。
- 门户到公输工作台导航通过，全部前端 JavaScript 语法检查、Moment Node 测试和本地HTML资源路径检查通过；旧品牌 `百臂巨人` / `Jingwei Grasp` 无残留。
- 前端里程碑提交：`aafc8c3 feat(frontend): add Gongshu integrated workbench`。

### 阶段8：REAL SCENE GRASP PERCEPTION — PASS（软件与集成）

- 新增独立 `RGBFrame` 契约和 `sources` 模块，支持电脑摄像头索引、Android HTTP/HTTPS/RTSP 地址和单张图片；没有给普通 RGB 帧伪造 depth 或相机内参。
- `UltralyticsYOLOSegmenter` 同时接受 RGB 与 RGB-D 输入；Real Scene Mode 固定只保留 `bottle`，原 Simulation Mode 的感知路径保持兼容。
- 新增人工四点桌面标定：用户输入尺量的长宽，并按 `原点 → +X → +X+Y → +Y` 顺序点选四角；标定按图像分辨率校验并持久化。
- 新增平面目标定位与确定性三候选规划，输出标定平面 X/Y、平面 yaw、估计目标宽度、估计夹爪开口、宽度可行性和可解释评分。
- 新增真实画面叠加：Live Vision、Spatial Perception、Grasp Planner 三视图分别显示检测、标定坐标和抓取候选；字段明确区分 `MEASURED / ESTIMATED / NOT_AVAILABLE`。
- 新增本地统一应用服务 `run_vision2grasp_app.py`，后台以目标 2 FPS 读取真实输入，提供状态、三张 JPEG、来源切换、标定和按需仿真 API。
- 一键启动器会识别并安全替换本项目旧版静态服务；遇到未知端口占用者会拒绝终止。重复双击会复用健康服务。
- 浏览器联合测试已覆盖：PC 摄像头连续取流、CC0 瓶子照片检测（置信度约 0.854）、四点标定后三候选显示、Real/Simulation 模式切换，以及原固定种子单瓶仿真成功。
- 自动化测试覆盖输入源、标定、平面定位、规划、真实管线和后台服务；本轮最终全量检查为 76 项 Python 测试全部通过，`compileall`、`pip check`、全部前端 JavaScript 语法检查和 Moment Node 测试通过。
- 尚未完成的现场验收：用户 Android 实际视频地址连接；固定真实相机下 5–10 个尺量检查点的定位误差统计。这两项需要用户实体设备参与。
- Real→MuJoCo 候选验证尚未实现，真实模式第四视图明确显示 `NOT_RUN / VALIDATOR PENDING`，不得宣称已经完成该闭环。

### 阶段9：XUANSHU LAB Windows 桌面平台 v0.1 — PASS

- 新增 PySide6 6.8.3 / Qt 6.8.3 桌面层，主入口为 `run_xuanshu_lab.py`，一键入口为根目录 `Start-XUANSHU-LAB.cmd`。
- 桌面采用 HTML-first 混合架构：PySide6 只管理 Windows 窗口、本地服务、日志、窗口偏好和单实例；单个 `QWebEngineView` 铺满窗口，原样载入既有 HTML 开机动画、玄枢门户、Moment 与 Gongshu，不重复实现或替换领域 UI。
- `xuanshu_lab.contracts.WorkspaceSpec` 和 `WorkspaceRegistry` 冻结可扩展注册边界。默认按顺序注册 `moment`、`gongshu`、`hetu`，重复 ID、非法本地资源路径和缺失 Web route 会被拒绝。
- 原版玄枢门户是唯一桌面主页；此前新增的 PySide 研究总览、左侧导航、顶部状态条和原生 Hetu 页面均不再参与运行界面。
- Jingwei Moment 与 Gongshu Vision2Grasp 均已在真实 Windows PySide6 窗口内成功加载；Gongshu 真实场景持续取得本地摄像头状态。
- Hetu 沿用原门户的规划中预告入口，不跳转到不存在的系统，也不展示虚假模型结果。
- `LocalServiceController` 只复用符合 `vision2grasp.app-health/v1` 的服务；未知程序占用端口时拒绝覆盖。桌面自行启动的服务会在窗口关闭时回收，复用的外部服务不会被终止。
- 平台包含快捷键控制的运行日志、持久化窗口尺寸和单实例唤醒；`Alt+Home` 返回原门户，`F5` / `Ctrl+R` 刷新，`Ctrl+Shift+L` 显示日志。原版 HTML 动画取代 PySide Splash，启动与返回视觉均由前端负责。
- 后台服务对 health、真实状态和 JPEG 帧轮询日志做降噪，避免桌面长期运行时日志文件因正常轮询持续膨胀。
- HTML-first 修正版已在真实 Windows PySide6 窗口中确认：普通系统标题栏下只有原版玄枢门户，没有原生侧栏、顶部栏或状态栏。更细的视觉验收由用户自行完成。
- 最终全量检查为 82 项 Python 测试全部通过，`compileall`、`pip check`、全部前端 JavaScript 语法检查和 Moment Node 测试通过。
- PySide6 / Qt 开源分发涉及 LGPLv3，WebEngine 同时涉及 Chromium 第三方许可证；未来打包 EXE 前必须完成分发合规审计。当前 v0.1 交付为项目虚拟环境加双击启动器，不冒充已完成安装包。

## 5. 当前验证命令

```powershell
$env:PYTHONPATH = "G:\Vision2Grasp\src"
& "G:\Vision2Grasp\.venv\Scripts\python.exe" -m compileall -q "G:\Vision2Grasp\src" "G:\Vision2Grasp\tests" "G:\Vision2Grasp\run_xuanshu_lab.py" "G:\Vision2Grasp\run_vision2grasp_app.py"
& "G:\Vision2Grasp\.venv\Scripts\python.exe" -m unittest discover -s "G:\Vision2Grasp\tests" -v
& "G:\Vision2Grasp\.venv\Scripts\python.exe" -m pip check
```

阶段0回归：

```powershell
& "G:\Vision2Grasp\.venv\Scripts\python.exe" "G:\Vision2Grasp\stage0_lift_smoke.py"
```

## 6. 当前使用方法

Windows 一键启动 XUANSHU LAB 桌面平台：

```text
双击 G:\Vision2Grasp\Start-XUANSHU-LAB.cmd
```

启动器使用项目虚拟环境打开 PySide6 桌面窗口，启动或复用端口 `8765` 上的统一本地服务。再次双击会唤醒已有窗口。窗口会播放原版 HTML 开机动画并进入原版玄枢门户；经纬、公输通过前端入口进入并可返回主页，Hetu 保持门户预告状态。

只需打开旧版公输 Web 工作台时，仍可双击 `Start-Vision2Grasp.cmd`。

真实场景首次使用：固定摄像头，输入尺量桌面区域长宽，点击“四点标定”，再依次点击 `原点、+X、+X+Y、+Y`。只放置 `bottle`。Android 与电脑连接同一 Wi-Fi 后，把手机摄像头应用给出的 HTTP/HTTPS/RTSP 地址粘贴到页面；也可直接选择单张照片。

手动启动统一应用：

```powershell
& "G:\Vision2Grasp\.venv\Scripts\python.exe" "G:\Vision2Grasp\run_vision2grasp_app.py" --host 127.0.0.1 --port 8765
```

原有仿真可在页面切换到 Simulation Mode 后按需运行，也可直接执行：

```powershell
& "G:\Vision2Grasp\.venv\Scripts\python.exe" "G:\Vision2Grasp\run_bottle_pipeline.py"
```

真实模式依赖本地 API，不得退回普通 `python -m http.server`。

## 7. 后续顺序

```text
XUANSHU LAB v0.1 桌面骨架（已完成）
→ 打包前许可证与第三方声明审计
→ Windows 安装包 / EXE 与卸载流程
→ Workspace 事件总线和可追踪任务模型
→ Hetu 数据契约与回放骨架

Gongshu 领域路线：
REAL SCENE GRASP PERCEPTION（软件与集成已完成）
→ 用户现场 Android 串流验证
→ 真实固定相机 5–10 点尺量误差验收
→ Real 候选坐标映射到 MuJoCo
→ 仿真验证结果回写 Real Scene Mode
→ 稳定后增加 cup
→ 再稳定后增加 banana
```

在上述现场验收前，不得调整标定阈值来迎合结果；在 Real→MuJoCo 完成前，第四视图必须保持明确的未运行状态。

## 8. 新聊天启动指令

在新聊天中指定工作目录 `G:\Vision2Grasp`，并先发送：

> 请先阅读根目录 README.md、CODEX_HANDOFF.md 和当前 Git 状态。XUANSHU LAB v0.1 PySide6 桌面平台已完成，固定三个 Workspace：Jingwei Moment、Gongshu Vision2Grasp、Hetu Preview。保持桌面 Shell 与领域算法解耦，Hetu 不得伪造模型结果。Gongshu 下一步仍是 Android 串流、尺量误差和 Real→MuJoCo 验证；保持 F:\hotarea-cv 只读。
