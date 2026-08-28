# XUANSHU LAB · Jingwei / Vision2Grasp

XUANSHU LAB（玄枢实验室）是一个 Windows AI / 机器人科研桌面平台。本仓库目前包含统一桌面壳、Jingwei Moment 图像理解工作台、Gongshu Vision2Grasp 抓取研究代码，以及 Hetu 预览入口。

当前版本的目标是提供可运行、可扩展的软件骨架和本地研究工具，不宣称已经完成真实机器人端到端抓取或世界模型能力。PySide6 负责桌面窗口和本地服务生命周期，用户界面由仓库内的 HTML / CSS / JavaScript 提供。

## 当前实现范围

- **Jingwei Moment**：本地图像导入、规则化分析与可视化工作台。
- **Gongshu Vision2Grasp**：已有分割、几何定位、抓取候选、Panda 控制接口、MuJoCo / robosuite 仿真与结果导出代码。
- **Jingwei Camera v1**：在 Gongshu 的真实场景页提供手机 LAN 实时 RGB 输入与高清拍照上传。
- **XUANSHU LAB Desktop**：Windows 上的 PySide6 + Qt WebEngine 桌面容器、统一门户、本地服务和单实例启动。
- **Hetu Preview**：仅为预览入口，不运行尚未完成的世界模型。

真实 Camera 主链路目前严格限定为：

```text
Phone Camera → LAN → PC → RGB Frame
```

Camera 实时画面通过私有局域网 WebRTC 传输，只在内存中保留最新 RGB 帧；高清拍照先进入 PC 内存预览，只有用户明确保存时才写入 `artifacts/camera/captures/`。

下面这条链路**尚未接入真实 Camera 主链路，也不应视为当前已完成功能**：

```text
YOLO → Depth → Grasp → MuJoCo
```

仓库中已有 YOLO、Depth / 几何、Grasp 和 MuJoCo 相关算法与仿真代码，但它们目前属于独立研究模块、离线验证能力或后续集成基础。

## Camera 安全与网络边界

- WebRTC 不配置 STUN / TURN，不使用 Cloudflare；Cloud Relay、Cloud Storage、Internet Upload 和实时录像默认关闭。
- 配对使用五分钟有效的一次性 Token；成功配对后立即失效，刷新配对会使旧 Session 失效。
- 本地 CA 私钥和服务端私钥生成在 `artifacts/camera/secrets/`，该目录被 Git 忽略。不要复制、提交或公开这些文件。
- 手机和 PC 必须位于同一可信私有局域网。程序不会修改 Windows 防火墙规则。
- CameraProvider 的当前稳定输出边界是 `RGB Frame + Timestamp + Resolution + Camera Source + Camera Status`。
- 当前正式实现是 `PhoneLANProvider`；USB、Network Stream 和 RGB-D 仅保留接口或状态，不代表已经可用。

### 手机首次连接

1. 让手机与电脑连接同一个普通 Wi-Fi，避免开启客户端隔离的访客网络，并临时关闭手机 VPN。
2. 启动 XUANSHU LAB，进入 Gongshu 并保持 `REAL SCENE MODE`。
3. Windows 首次询问防火墙权限时，只允许“专用网络”。
4. 用手机扫描 `LOCAL CA SETUP` 二维码，安装本地 CA，并核对手机页面与 PC 显示的 SHA-256 指纹。
5. 完全关闭并重新打开 Chrome，再扫描 `PAIRING` 二维码。
6. 手机允许后置摄像头，点击 `START CAMERA` 和 `START LIVE`。
7. 如需高清照片，切换到 `CAPTURE`；PC 端收到预览后，再由用户决定是否保存原图。

配对页默认使用 TCP `8766`（HTTPS）和 `8767`（首次证书设置）；WebRTC 会在同一私网内协商临时 UDP 端口。LAN IP 改变后，服务会在下次启动时为当前私网地址重新签发服务端证书。

## 环境要求

- Windows 11（当前已验证平台）
- Python 3.12.x（`pyproject.toml` 限定 `>=3.12,<3.13`）
- 支持 Qt WebEngine 的 Windows 桌面环境
- 同一私有局域网内的手机与 PC（仅 Camera v1 需要）
- MuJoCo / YOLO 模块需要额外的 CPU、内存和磁盘空间；它们不是 Camera RGB 接入的前置条件

当前验证环境包括 PySide6 6.8.3、OpenCV 4.11、MuJoCo 3.9.0、robosuite 1.5.2、PyTorch 2.13.0 CPU、Ultralytics 8.4.128、aiohttp 3.14.3、aiortc 1.15.0 和 cryptography 50.0.1。

## 安装

项目使用 `pyproject.toml` 作为 Python 依赖的唯一来源，不需要额外维护重复的 `requirements.txt`。

在项目根目录运行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

YOLO 权重不随 Git 仓库发布。需要运行相关离线算法时，请从模型官方发布渠道获取 `yolo11n-seg.pt`，放到 `artifacts/models/`，并自行确认许可证和文件完整性。Camera RGB 接入不需要该权重。

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

- 真实 Camera 主链路只提供 RGB Frame，不提供真实深度、点云、抓取候选或 MuJoCo 回写。
- USB Camera、Network Stream、RGB-D Camera 尚未作为正式输入实现。
- 尚未接入真实机器人控制，也没有真实场景完整闭环验证。
- Hetu 只提供预览入口，没有世界模型算法。
- 尚未提供正式安装包、自动更新、账户、云同步或互联网中继。
- 运行产物、用户图片、证书私钥和模型权重均为本地数据，不随仓库发布。

## 许可证与第三方边界

本仓库目前**尚未选择项目级开源许可证**。公开源代码不等于自动授予复制、修改或分发权；正式发布前应由项目所有者选择并添加合适的 `LICENSE`。

- PySide6 / Qt 开源版本涉及 LGPLv3；Qt WebEngine 还包含 Chromium 第三方组件。未来分发 EXE 时需完成动态链接、许可证文本和第三方声明审计。
- Ultralytics 软件及官方 YOLO 权重采用 AGPL-3.0 系列许可。闭源、内部商业或产品化使用前，应确认 AGPL 义务或取得适用的商业许可。
- Camera v1 直接使用 aiortc、aiohttp、PyAV、cryptography 和 qrcode；发布二进制或安装包前应保留相应许可证和传递依赖声明。
- MuJoCo、robosuite、PyTorch、torchvision、OpenCV、NumPy 等算法依赖也需要在正式分发前形成完整的第三方清单。
- 仓库中的 UI 图片作为源代码资产被跟踪；公开发布前仍应由项目所有者确认这些图片的原创性、授权来源和可再分发范围。它们不应与 `artifacts/` 下的实验图片、用户抓拍或模型权重混淆。

以上仅说明当前已识别的许可证边界，不构成法律意见，也没有修改任何第三方许可证。
