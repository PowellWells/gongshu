# XUANSHU LAB · Jingwei / Vision2Grasp

XUANSHU LAB（玄枢实验室）是一个 Windows AI / 机器人科研桌面平台。本仓库目前包含统一桌面壳、Jingwei Moment 图像理解工作台、Gongshu Vision2Grasp 抓取研究代码，以及 Hetu 预览入口。

当前版本的目标是提供可运行、可扩展的软件骨架和本地研究工具，不宣称已经完成真实机器人端到端抓取或世界模型能力。PySide6 负责桌面窗口和本地服务生命周期，用户界面由仓库内的 HTML / CSS / JavaScript 提供。

## 当前实现范围

- **Jingwei Moment**：本地图像导入、规则化分析与可视化工作台。
- **Gongshu Workspace v0.6**：在 v0.5 同一 Scene Snapshot 空间链之上运行官方 GR-ConvNet RGB-D 抓取检测，输出真实 Quality / Angle / Width maps、Top-K 候选、逐候选可执行性与透明排名，并只在存在可执行候选时进入 `GRASP_READY`。
- **Gongshu Dynamic Validation v0.7**：当前 `GRASP_READY` 计划可进入 Panda/MuJoCo 连续动力学动画；支持标称场景和目标偏移压测，最终 SUCCESS / FAILED 来自真实接触、桌面碰撞、抬升高度和稳定窗口，不使用固定结果。
- **Jingwei Camera v1**：通过 Gongshu 的 Source / Camera Setup 提供手机 LAN 实时 RGB 输入、扫码配对与高清拍照上传。
- **XUANSHU LAB Desktop**：Windows 上的 PySide6 + Qt WebEngine 桌面容器、统一门户、本地服务和单实例启动。
- **Hetu Preview**：仅为预览入口，不运行尚未完成的世界模型。

真实 Camera 主链路目前严格限定为：

```text
Phone Camera → Frozen RGB Frame → Manual Target → Verified Depth
→ Camera Intrinsics → Target Point Cloud / XYZ → Geometry Sanity → SPATIAL_READY
→ GR-ConvNet Grasp Maps → Top-K → Feasibility Filtering
→ Best Executable Grasp → GRASP_READY
```

Camera 实时画面通过私有局域网 WebRTC 传输，只在内存中保留最新 RGB 帧；高清拍照先进入 PC 内存预览，只有用户明确保存时才写入 `artifacts/camera/captures/`。

Target Perception 只输出与同一冻结帧绑定的实例掩膜、边界框、二维中心和可选语义信息。FastSAM-s 未提供可靠语义类别，因此默认显示 `未知目标 Unknown Object`，但仍允许用户选择。v0.5 Spatial 只消费该冻结 Scene Snapshot，不会重新抽取 Live RGB 帧；RGB、Mask、Depth、Intrinsics、Point Cloud 与 XYZ 必须共享同一个 `geometry_chain_id`。

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

当前验证环境包括 NVIDIA GeForce RTX 3060 Laptop GPU、PyTorch 2.13.0+cu126、torchvision 0.28.0+cu126、PySide6 6.8.3、OpenCV 4.11、MuJoCo 3.9.0、robosuite 1.5.2、Ultralytics 8.4.128、aiohttp 3.14.3、aiortc 1.15.0 和 cryptography 50.0.1。抓取检测默认 `AUTO`：CUDA 可用时使用 GPU，否则保留 CPU fallback。

## 安装

项目使用 `pyproject.toml` 作为 Python 依赖的唯一来源，不需要额外维护重复的 `requirements.txt`。

在项目根目录运行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

模型权重不随 Git 源码仓库发布。FastSAM 运行时查找顺序固定为 `Release Bundle → artifacts/models/FastSAM-s.pt → FastSAM 用户级 Cache → 官方下载`；默认缓存位于 `%LOCALAPPDATA%\Vision2Grasp\model-cache`，可通过 FastSAM 专用的 `VISION2GRASP_FASTSAM_CACHE` 覆盖。Depth Anything 与 GR-ConvNet 各自使用 `Release Bundle → artifacts/models → 用户级 Cache → 官方下载` resolver，并在加载前校验大小和 SHA-256。Depth backend 使用官方 `Depth-Anything-V2` metric runtime（代码 commit `a561b849…`）与 indoor metric Small 权重，保持 CPU persistent worker、`518` 输入尺寸和 lazy load。v0.6 使用官方 `skumra/robotic-grasping` Jacquard RGB-D GR-ConvNet3 checkpoint（revision `epoch_48_iou_0.93`，SHA-256 `adfb2cbb…`，BSD-3-Clause），`224×224` 目标感知 crop、AUTO CUDA/CPU 与进程内持久模型。模型解析、下载、校验、加载或推理失败会返回真实错误，不会伪造 READY。完整来源与许可证见 `THIRD_PARTY_NOTICES.md`。

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

进入 Gongshu 后不再显示独立 Camera Input 页面。默认 Pipeline State 为 `LIVE`，Live RGB 是主视图；点击辅助视图可进入 Manual Pin，选择 Auto Follow 后恢复阶段跟随。Phone Live RGB 连接后先点击 `分析目标 Analyze Targets`：本地服务冻结一帧、生成实例候选并在原图上显示掩膜；点击候选后才进入 `TARGET_SELECTED` 并启用空间链。v0.6 严格复用同一个 Scene Snapshot，依次进入 `SCENE_CAPTURED → SPATIAL_ANALYSIS → SPATIAL_READY → GRASP_PLANNING → GRASP_READY / PLANNING_REJECTED`。空间与抓取主视图显示真实 backend stage、elapsed time 和模型冷/热状态，没有虚假百分比或固定成功。Research Mode 显示完整 Top-K、Reject 原因和诊断图层；Demo Mode 调用同一真实算法，并通过 Graspability Preflight 优先提示可执行候选。Quality / Angle / Width / Candidates 四层可直接切换。

Phone Mode 的 Camera Intrinsics 优先级预留为 `CALIBRATED → SENSOR_METADATA → MODEL_PREDICTED → NOMINAL_FOV`。当前实现支持首尾两项：默认无需标定，直接回退到 Nominal FOV；若存在 `%LOCALAPPDATA%\Vision2Grasp\camera-intrinsics.json`（或 `VISION2GRASP_CAMERA_INTRINSICS` 指定文件），则可按逻辑 `camera_name` 提供 `width / height / fx / fy / cx / cy`。配置不包含 Honor Magic4 或任何具体手机型号参数，且只有宽高比一致时才允许按分辨率缩放已标定内参。

当前默认尺度路径明确为 `scale_mode = DIRECT`：它不使用桌面或已知物体先验，也不会在尺度异常时自动修正结果。单目 metric-scaled 模型跨手机、焦段和近距离小物体时仍可能产生系统性绝对尺度偏差，因此 `ABNORMAL_SCALE` 与 Panda `0.01–0.08 m` 宽度保护继续生效。后续可选的轻量 `Scale Assistance` 方案是不依赖标准桌子的“单一已知长度”：用户可输入当前目标或同平面任意参考物的一条真实长度，系统只计算一个统一尺度因子并同时作用于 Depth / XYZ / Extent；结果仍标记 `APPROX_METRIC + REFERENCE + UNCALIBRATED`，不得升级为严格 Metric。该辅助模式本轮尚未启用，Direct Mode 仍是默认且完整保留。

v0.6 已按 `Grasp Detection → Top-K Candidates → Feasibility Filtering → Candidate Ranking → Best Executable Grasp` 完成。默认 `Top-K=8`，候选逐一检查 target binding、quality、边缘余量、有效深度、几何置信度、异常尺度与 Panda 夹爪宽度；最高 quality 候选被拒绝时会继续评估其余候选。Panda 宽度直接复用 `[control]` 的 `0.01–0.08 m` 权威配置，`maximum_object_extent_m = 0.35` 没有放宽。由于尚无 Camera→Robot 外参，workspace reachability 与 collision feasibility 明确为 `UNKNOWN`，不伪造成可达或无碰撞。

v0.7 已接入动态 MuJoCo Success + Failure Visualization。`NOMINAL` 执行当前 GraspPlan 的标称验证；`TARGET_OFFSET_STRESS` 仅把仿真目标相对原计划偏移 `0.14 m`，Panda 仍执行同一轨迹，最终由物理结果决定失败类型。MJPEG 连续显示 HOME → PRE_GRASP → APPROACH → ALIGN → CLOSE → LIFT → VERIFY → SUCCESS / FAILED，最终帧标注物理结论和原因；API 同时保留实际状态历史。扫码、证书、连接状态与高清 Capture 仍位于 `连接设置 Camera Setup`；原离线运行读取位于 `历史运行 History` 次级入口。

## Windows Release 预留

源码仓库保持轻量；正式 Release 应先用后续冻结工具准备自包含 Windows 应用目录，再运行：

```powershell
.\.venv\Scripts\python.exe .\scripts\build_release.py --verify-only --offline
.\.venv\Scripts\python.exe .\scripts\build_release.py `
  --prepared-app .\dist\Vision2Grasp `
  --output .\artifacts\releases\Vision2Grasp-windows-x64.zip
```

构建器检查运行依赖与模型完整性，把经过 SHA-256 校验的 FastSAM / Depth Anything V2 / GR-ConvNet 复制到 `models/`，写入 `release-models.json` 和第三方声明后生成 ZIP。`--prepared-app` 必须已经包含可运行 EXE 或源码启动器及 `frontend/`；该脚本不把模型写回 Git，也不把未冻结的源码目录误称为自包含 EXE。

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
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe .\scripts\benchmark_grasp_v06.py --device auto
.\.venv\Scripts\python.exe -m pip check
```

## 当前限制

- 真实 Camera v0.6 主链路可生成 RGB Frame、手动目标、单目近似深度、相机内参、目标点云、Camera Frame XYZ 与 map-derived Top-K Grasp；它不是标定后的 Camera→Robot / World 坐标闭环。
- 单目绝对尺度在近距离小目标上可能偏离真实数量级；Nominal FOV 只能提供投影比例，不能纠正深度模型的绝对尺度。系统会保留真实输出并由 `ABNORMAL_SCALE / WIDTH_LIMIT` 拒绝不合理计划，不会通过放宽阈值或静默缩放伪造可执行结果。
- Physical Phone v0.6 验收仍由用户完成，状态为 `PENDING USER VALIDATION`；Phone Mode 不包含任何具体手机型号硬编码，自动化和静态样本结果不得描述为实体手机精度实测。
- USB Camera、Network Stream、RGB-D Camera 尚未作为正式输入实现。
- 尚未接入真实机械臂、外参标定、在线碰撞场景重建或物理执行闭环；当前 SUCCESS 仅表示 Simulation Validation。
- `TARGET_OFFSET_STRESS` 是可复现的 simulation-only 扰动场景，用于演示真实失败动力学，不代表实体环境发生了同样的目标移动。
- Hetu 只提供预览入口，没有世界模型算法。
- 尚未冻结正式自包含 Windows EXE 构建工具链；当前只提供经过测试的 release 模型校验与 ZIP packaging 预留。
- 运行产物、用户图片、证书私钥和模型权重均为本地数据，不随仓库发布。

## 许可证与第三方边界

本仓库目前**尚未选择项目级开源许可证**。公开源代码不等于自动授予复制、修改或分发权；正式发布前应由项目所有者选择并添加合适的 `LICENSE`。

- PySide6 / Qt 开源版本涉及 LGPLv3；Qt WebEngine 还包含 Chromium 第三方组件。未来分发 EXE 时需完成动态链接、许可证文本和第三方声明审计。
- v0.4 通过 Ultralytics 运行 FastSAM-s；当前 FastSAM 上游仓库、Ultralytics 运行时与 Ultralytics assets 仓库均声明 AGPL-3.0 系列许可。闭源、内部商业或产品化使用前仍应分别确认运行时、权重及上游代码的适用许可。
- v0.5 使用 Apache-2.0 的 Depth Anything V2 Small 系列官方 indoor metric `.pth` 权重及固定 commit 的官方 metric runtime；正式分发前仍需保留模型卡、许可证与依赖声明，并评估模型训练数据和用途边界。
- v0.6 新增的 GR-ConvNet 最小 runtime 与官方 Jacquard RGB-D checkpoint 均固定到 `skumra/robotic-grasping` 同一 revision，并按 BSD-3-Clause 保留许可证和来源；未引入 GPL、AGPL、Non-Commercial 或来源不明的抓取 baseline。
- Camera v1 直接使用 aiortc、aiohttp、PyAV、cryptography 和 qrcode；发布二进制或安装包前应保留相应许可证和传递依赖声明。
- MuJoCo、robosuite、PyTorch、torchvision、OpenCV、NumPy 等算法依赖也需要在正式分发前形成完整的第三方清单。
- 仓库中的 UI 图片作为源代码资产被跟踪；公开发布前仍应由项目所有者确认这些图片的原创性、授权来源和可再分发范围。它们不应与 `artifacts/` 下的实验图片、用户抓拍或模型权重混淆。

以上仅说明当前已识别的许可证边界，不构成法律意见，也没有修改任何第三方许可证。
