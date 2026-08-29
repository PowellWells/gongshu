# XUANSHU LAB · Jingwei / Vision2Grasp

XUANSHU LAB（玄枢实验室）是一个 Windows AI / 机器人科研桌面平台。本仓库目前包含统一桌面壳、Jingwei Moment 图像理解工作台、Gongshu Vision2Grasp 抓取研究代码，以及 Hetu 预览入口。

当前版本的目标是提供可运行、可扩展的软件骨架和本地研究工具，不宣称已经完成真实机器人端到端抓取或世界模型能力。PySide6 负责桌面窗口和本地服务生命周期，用户界面由仓库内的 HTML / CSS / JavaScript 提供。

## 当前实现范围

- **Jingwei Moment**：本地图像导入、规则化分析与可视化工作台。
- **Gongshu Workspace v0.6**：在 v0.5 `SpatialObservation` 之后加入 CPU 几何抓取规划、标准 `GraspPlan`、规范化 MuJoCo 验证场景、Panda 连续物理动画与状态驱动 Cinematic Camera；布局继续由集中式 Pipeline State 驱动。
- **Jingwei Camera v1**：通过 Gongshu 的 Source / Camera Setup 提供手机 LAN 实时 RGB 输入、扫码配对与高清拍照上传。
- **XUANSHU LAB Desktop**：Windows 上的 PySide6 + Qt WebEngine 桌面容器、统一门户、本地服务和单实例启动。
- **Hetu Preview**：仅为预览入口，不运行尚未完成的世界模型。

真实 Camera 主链路目前严格限定为：

```text
Phone Camera → Frozen RGB Frame → Manual Target → Depth / Point Cloud → GraspPlan → Normalized MuJoCo Validation
```

Camera 实时画面通过私有局域网 WebRTC 传输，只在内存中保留最新 RGB 帧；高清拍照先进入 PC 内存预览，只有用户明确保存时才写入 `artifacts/camera/captures/`。

Target Perception 只输出与同一冻结帧绑定的实例掩膜、边界框、二维中心和可选语义信息。FastSAM-s 未提供可靠语义类别，因此默认显示 `未知目标 Unknown Object`，但仍允许用户选择。后续 Spatial / Grasp 只消费该冻结 Scene Snapshot 及其标准下游结果，不会重新抽取 Live RGB 帧；MuJoCo 只消费 `GraspPlan`，不读取 Phone Camera、Depth Backend 或前端状态。

## Camera 安全与网络边界

- WebRTC 不配置 STUN / TURN，不使用 Cloudflare；Cloud Relay、Cloud Storage、Internet Upload 和实时录像默认关闭。
- 配对使用五分钟有效的一次性 Token；成功配对后立即失效，刷新配对会使旧 Session 失效。
- 本地 CA 私钥和服务端私钥生成在 `artifacts/camera/secrets/`，该目录被 Git 忽略。不要复制、提交或公开这些文件。
- 手机和 PC 必须位于同一可信私有局域网。程序不会修改 Windows 防火墙规则。
- CameraProvider 的当前稳定输出边界是 `RGB Frame + Timestamp + Resolution + Camera Source + Camera Status`。
- 当前正式实现是 `PhoneLANProvider`；USB、Network Stream 和 RGB-D 仅保留接口或状态，不代表已经可用。

### 手机首次连接

1. 让手机与电脑连接同一个普通 Wi-Fi，避免开启客户端隔离的访客网络，并临时关闭手机 VPN。
2. 启动 XUANSHU LAB，从门户进入 Gongshu；页面默认直接显示四视图 Workspace。
3. Windows 首次询问防火墙权限时，只允许“专用网络”。
4. 用手机扫描 `LOCAL CA SETUP` 二维码，安装本地 CA，并核对手机页面与 PC 显示的 SHA-256 指纹。
5. 完全关闭并重新打开 Chrome，再扫描 `PAIRING` 二维码。
6. 手机允许后置摄像头，点击 `START CAMERA` 和 `START LIVE`；真实画面会进入 `01 实时视觉 Live RGB`。
7. 如需高清照片，切换到 `CAPTURE`；PC 端收到预览后，再由用户决定是否保存原图。

配对页默认使用 TCP `8766`（HTTPS）和 `8767`（首次证书设置）；WebRTC 会在同一私网内协商临时 UDP 端口。LAN IP 改变后，服务会在下次启动时为当前私网地址重新签发服务端证书。

## 环境要求

- Windows 11（当前已验证平台）
- Python 3.12.x（`pyproject.toml` 限定 `>=3.12,<3.13`）
- 支持 Qt WebEngine 的 Windows 桌面环境
- 同一私有局域网内的手机与 PC（仅 Camera v1 需要）
- MuJoCo / YOLO 模块需要额外的 CPU、内存和磁盘空间；它们不是 Camera RGB 接入的前置条件

当前验证环境包括 PySide6 6.8.3、OpenCV 4.11、MuJoCo 3.9.0、robosuite 1.5.2、PyTorch 2.13.0 CPU、Transformers 4.57.6、Ultralytics 8.4.128、aiohttp 3.14.3、aiortc 1.15.0 和 cryptography 50.0.1。

## 安装

项目使用 `pyproject.toml` 作为 Python 依赖的唯一来源，不需要额外维护重复的 `requirements.txt`。

在项目根目录运行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

模型权重不随 Git 仓库发布。Gongshu v0.4 的目标感知需要官方 `FastSAM-s.pt`，放到 `artifacts/models/FastSAM-s.pt`；程序会在首次分析前核对 SHA-256：`c9f78716a81c7aff0d608ccc73e1b82ab3aaad86005049f6a92106a0be6d0844`。v0.5 空间感知在第一次执行时延迟下载官方 Depth Anything V2 Metric Indoor Small 到 `artifacts/models/depth-anything-v2-metric-indoor-small-hf/`，固定官方 revision `8078d68a9c75a972131914f6afd0c1723be0da7f`，其中权重 SHA-256 为 `e990eb82fbf11b05b7813261196a2b841bdcf5a05f64396724a8987fa90504a3`；下载或校验失败只会返回 `DEPTH UNAVAILABLE`，不会阻止桌面启动。需要运行旧的离线 YOLO 模块时，另行从官方渠道获取 `yolo11n-seg.pt`。请在使用或分发前自行确认权重与运行时许可证。

## 启动

双击项目根目录的 `Start-XUANSHU-LAB.cmd` 启动完整桌面平台。

也可以在 PowerShell 中运行：

```powershell
.\.venv\Scripts\python.exe .\run_xuanshu_lab.py
```

只启动 Gongshu Web 工作台：

```powershell
.\Start-Vision2Grasp.cmd
```

启动器全部基于自身所在目录解析项目路径，不要求仓库位于特定盘符。

进入 Gongshu 后不再显示独立 Camera Input 页面。默认 Pipeline State 为 `LIVE`，Live RGB 是主视图；点击辅助视图可进入 Manual Pin，选择 Auto Follow 后恢复阶段跟随。Phone Live RGB 连接后先点击 `分析目标 Analyze Targets`：本地服务冻结一帧、生成实例候选并在原图上显示掩膜；点击候选后才进入 `TARGET_SELECTED` 并启用 `开始抓取 Start Grasp`。开始抓取严格复用同一个 Scene Snapshot，依次进入 `SCENE_CAPTURED → SPATIAL_ANALYSIS → SPATIAL_READY → GRASP_PLANNING`。普通 Phone RGB 使用可配置标称对角视场角构造 `NOMINAL_FOV / UNCALIBRATED` 投影参数；当前 metric-scaled 单目结果只标记 `Approx. Metric`。

v0.6 规划器在 OpenCV Camera Frame（`+X` 右、`+Y` 下、`+Z` 前）中对真实目标点云执行稳健范围估计与二维 PCA，生成中心及沿主轴偏移的 Top-down 候选，夹爪闭合方向取 PCA 短轴。所需宽度为目标短轴稳健范围加 8 mm clearance；Panda 有效范围固定为 `0.01–0.08 m`，超限直接 `FAILED`。`quality_score` 仅排序候选；`confidence` 为 `HEURISTIC_UNCALIBRATED`，由点支持、深度有效性、PCA 稳定性和宽度余量构成，不代表真实成功概率。

规划 READY 后必须由用户点击 `开始仿真验证 Start Validation`。由于没有 Camera→Robot/Table 外参，`ValidationSceneTransform / NORMALIZED_VALIDATION_SCENE` 只保留相对尺度、主轴、宽度与 Approach，并映射到 Panda 安全工作区；始终标记 `UNCALIBRATED / SIMULATION_ONLY`。MuJoCo 使用原生关节位置执行器、DLS IK 轨迹、动态目标接触、摩擦与重力，按 `HOME → PRE_GRASP → APPROACH → ALIGN → CLOSE → LIFT → VERIFY` 连续执行。`SUCCESS` 要求状态完整、无无效桌面碰撞、已执行 Close、达到 Lift Height 且通过稳定窗口。Cinematic / Auto Follow / Manual 只改变虚拟相机表现，不修改物理结果。扫码、证书、连接状态与高清 Capture 仍位于 `连接设置 Camera Setup`；原离线运行读取位于 `历史运行 History` 次级入口。

## 项目结构

```text
Vision2Grasp/
├─ configs/                 研究管线默认配置
├─ contracts/               公开运行结果数据契约
├─ frontend/                门户、Jingwei、Gongshu 与 Camera 前端
├─ scripts/                 Windows 启动脚本
├─ src/vision2grasp/        感知、几何、抓取、控制、仿真与 Camera 模块
├─ src/xuanshu_lab/         桌面 Shell、Workspace 注册与服务管理
├─ tests/                   单元测试与集成测试
├─ artifacts/               本地权重、密钥、抓拍和实验输出（Git 忽略）
├─ run_vision2grasp_app.py  本地 Web/API 服务入口
└─ run_xuanshu_lab.py       XUANSHU LAB 桌面入口
```

## 验证

在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m compileall -q .\src .\tests .\run_xuanshu_lab.py .\run_vision2grasp_app.py
.\.venv\Scripts\python.exe -m unittest discover -s .\tests -v
.\.venv\Scripts\python.exe -m pip check
```

## 当前限制

- 真实 Camera 主链路目前可生成 RGB Frame、手动目标、单目近似深度、目标点云、Camera Frame GraspPlan 与规范化 MuJoCo Validation；它不是标定后的 Camera→Robot / World 坐标闭环。
- Honor Magic4 的 v0.6 实体完整链路验收仍由用户完成；自动化、静态样本和 MuJoCo 结果不得描述为实体手机或实体机器人实测。
- USB Camera、Network Stream、RGB-D Camera 尚未作为正式输入实现。
- 尚未接入真实机械臂、外参标定、在线碰撞场景重建或物理执行闭环；当前 SUCCESS 仅表示 Simulation Validation。
- Hetu 只提供预览入口，没有世界模型算法。
- 尚未提供正式安装包、自动更新、账户、云同步或互联网中继。
- 运行产物、用户图片、证书私钥和模型权重均为本地数据，不随仓库发布。

## 许可证与第三方边界

本仓库目前**尚未选择项目级开源许可证**。公开源代码不等于自动授予复制、修改或分发权；正式发布前应由项目所有者选择并添加合适的 `LICENSE`。

- PySide6 / Qt 开源版本涉及 LGPLv3；Qt WebEngine 还包含 Chromium 第三方组件。未来分发 EXE 时需完成动态链接、许可证文本和第三方声明审计。
- v0.4 通过 Ultralytics 运行 FastSAM-s；当前 Ultralytics 软件采用 AGPL-3.0 系列许可。FastSAM 上游仓库声明 Apache-2.0，但闭源、内部商业或产品化使用前仍应分别确认运行时、权重及上游代码的适用许可。
- v0.5 使用 Apache-2.0 的 Depth Anything V2 Small 系列官方 indoor metric 权重，并通过 Apache-2.0 的 Hugging Face Transformers 运行；正式分发前仍需保留模型卡、许可证与依赖声明，并评估模型训练数据和用途边界。
- Camera v1 直接使用 aiortc、aiohttp、PyAV、cryptography 和 qrcode；发布二进制或安装包前应保留相应许可证和传递依赖声明。
- MuJoCo、robosuite、PyTorch、torchvision、OpenCV、NumPy 等算法依赖也需要在正式分发前形成完整的第三方清单。
- 仓库中的 UI 图片作为源代码资产被跟踪；公开发布前仍应由项目所有者确认这些图片的原创性、授权来源和可再分发范围。它们不应与 `artifacts/` 下的实验图片、用户抓拍或模型权重混淆。

以上仅说明当前已识别的许可证边界，不构成法律意见，也没有修改任何第三方许可证。
