# Gongshu / 公输

`Vision2Grasp — Robot Vision and Grasp Research Pipeline`

Gongshu（公输）是 XUANSHU AI 体系中的具身智能产品线，面向 Robot Action、Manipulation 与 Grasp 研究。本仓库承载其内部工程 Vision2Grasp，包括机器人视觉、几何定位、抓取规划、控制接口、仿真验证，以及真实场景 Camera 接入。

当前版本是一套可运行、可扩展的本地研究代码与实验工作台，不宣称已经完成真实机器人端到端抓取闭环。

## 当前实现范围

- **Phone Camera**：手机通过可信私有局域网向 PC 提供实时 RGB 视频与高清拍照。
- **Robot Vision**：提供 YOLO 分割适配器、OpenCV 图像源和真实场景处理接口。
- **Geometry**：提供平面标定、掩码深度定位和几何数据契约。
- **Grasp Planning**：提供平面与 PCA 顶部抓取候选算法。
- **Robot Control**：提供 Panda OSC 控制接口与执行适配器。
- **Simulation**：提供 MuJoCo / robosuite Bottle Lift 研究与验证模块。
- **Evaluation**：提供抓取和抬升结果评估及运行产物导出。

## 真实 Camera 边界

当前真实 Camera 主链路严格限定为：

```text
Phone Camera → LAN → PC → RGB Frame
```

Camera 实时画面通过私有局域网 WebRTC 传输，只在内存中保留最新 RGB 帧。高清照片先进入 PC 内存预览，只有用户明确保存时才写入 `artifacts/camera/captures/`。

下面这条链路是仓库中已有研究模块与后续真实场景集成路线，**不是当前已经完成的真实端到端系统**：

```text
RGB → YOLO → Depth → Grasp Planning → Robot Control → MuJoCo Validation
```

YOLO、Depth / Geometry、Grasp、Robot Control 和 MuJoCo 代码目前可以用于独立研究、离线验证或仿真实验，但尚未与 Phone Camera 形成经过验证的完整真实场景闭环。

## Camera 安全与网络边界

- WebRTC 不配置 STUN / TURN；Cloud Relay、Cloud Storage、Internet Upload 和实时录像默认关闭。
- 配对使用五分钟有效的一次性 Token；成功配对后立即失效，刷新配对会使旧 Session 失效。
- 本地 CA 私钥和服务端私钥生成在 `artifacts/camera/secrets/`；该目录被 Git 忽略。
- 手机和 PC 必须位于同一可信私有局域网，程序不会修改 Windows 防火墙规则。
- CameraProvider 的当前稳定输出边界是 `RGB Frame + Timestamp + Resolution + Camera Source + Camera Status`。
- 当前正式实现是 `PhoneLANProvider`；USB、Network Stream 和 RGB-D 仅保留接口或未来状态，不代表已经可用。

### 手机首次连接

1. 让手机与电脑连接同一个普通 Wi-Fi，避免使用开启客户端隔离的访客网络，并临时关闭手机 VPN。
2. 运行 `Start-Vision2Grasp.cmd`，打开 Gongshu 工作台并保持 `REAL SCENE MODE`。
3. Windows 首次询问防火墙权限时，只允许“专用网络”。
4. 用手机扫描 `LOCAL CA SETUP` 二维码，安装本地 CA，并核对手机页面与 PC 显示的 SHA-256 指纹。
5. 完全关闭并重新打开 Chrome，再扫描 `PAIRING` 二维码。
6. 手机允许后置摄像头，点击 `START CAMERA` 和 `START LIVE`。
7. 如需高清照片，切换到 `CAPTURE`；PC 收到预览后，再由用户决定是否保存原图。

默认端口为 TCP `8765`（PC 工作台）、`8766`（手机 HTTPS）和 `8767`（首次证书设置）。WebRTC 会在同一私网内协商临时 UDP 端口。LAN IP 改变后，服务会在下次启动时为当前私网地址重新签发服务端证书。

## 环境要求

- Windows 11（当前已验证平台）
- Python 3.12.x（`pyproject.toml` 限定 `>=3.12,<3.13`）
- 同一可信私有局域网内的手机与 PC（仅 Phone Camera 需要）
- MuJoCo / YOLO 模块需要额外的 CPU、内存和磁盘空间；它们不是 Camera RGB 接入的前置条件

当前依赖配置包括 OpenCV、NumPy、aiohttp、aiortc、PyAV、cryptography、qrcode、MuJoCo、robosuite、PyTorch、torchvision 和 Ultralytics。

## 安装

项目使用 `pyproject.toml` 作为 Python 依赖来源：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

YOLO 权重不随 Git 仓库发布。需要运行相关研究模块时，请从模型官方发布渠道获取兼容权重，并放入本地 `artifacts/models/`。使用者需要自行确认模型许可和文件完整性。Phone Camera RGB 接入不需要 YOLO 权重。

## 启动

双击：

```text
Start-Vision2Grasp.cmd
```

或在 PowerShell 中运行：

```powershell
.\.venv\Scripts\python.exe .\run_vision2grasp_app.py
```

启动器基于自身所在目录解析项目路径，不要求仓库位于特定盘符。默认工作台地址为：

```text
http://127.0.0.1:8765/apps/gongshu/index.html
```

## 项目结构

```text
gongshu/
├─ configs/                    Vision2Grasp 默认配置
├─ contracts/                  运行结果数据契约
├─ frontend/apps/gongshu/      Gongshu 工作台与 Phone Camera 页面
├─ scripts/                    Windows 启动脚本
├─ src/vision2grasp/           感知、几何、抓取、控制、仿真与 Camera 模块
├─ tests/                      单元测试与集成测试
├─ run_vision2grasp_app.py     本地 Web/API 服务入口
├─ run_bottle_pipeline.py      Bottle Lift 研究管线入口
├─ stage0_lift_smoke.py        MuJoCo / robosuite 环境烟雾测试
└─ Start-Vision2Grasp.cmd      Windows 启动入口
```

运行时生成的 `artifacts/`、`frontend/runtime/`、Camera captures、证书、私钥、Session、日志和模型权重均被 Git 忽略。

## 验证

```powershell
.\.venv\Scripts\python.exe -m compileall -q .\src .\tests .\run_vision2grasp_app.py .\run_bottle_pipeline.py .\stage0_lift_smoke.py
.\.venv\Scripts\python.exe -m unittest discover -s .\tests -v
.\.venv\Scripts\python.exe -m pip check
node --check .\frontend\apps\gongshu\gongshu.js
node --check .\frontend\apps\gongshu\real-scene.js
node --check .\frontend\apps\gongshu\phone-camera\phone-camera.js
```

## 当前限制

- 真实 Camera 主链路只提供 RGB Frame，不提供真实深度、点云、抓取候选或 MuJoCo 回写。
- USB Camera、Network Stream 和 RGB-D Camera 尚未作为正式输入实现。
- 尚未接入真实机器人控制，也没有真实场景完整闭环验证。
- 尚未提供正式安装包、自动更新、账户、云同步或互联网中继。
- 运行产物、用户图片、证书私钥和模型权重均为本地数据，不随仓库发布。

## 许可证与第三方边界

本仓库目前**尚未选择项目级开源许可证，也没有 `LICENSE` 文件**。公开可见的源代码不应被理解为已经自动获得复制、修改或再分发授权。正式发布前，项目所有者仍需结合依赖、模型和计划中的分发方式选择许可证。

- Ultralytics 软件和官方模型的许可边界需要在发布及商业使用前单独确认。
- MuJoCo、robosuite、PyTorch、torchvision、OpenCV、NumPy、aiohttp、aiortc、PyAV、cryptography 和 qrcode 均保留各自许可证。
- 如未来分发可执行文件、容器、预训练权重或数据集，需要重新执行第三方许可证与 Notice 审查。

以上内容是工程发布边界说明，不构成法律意见，也没有修改任何第三方许可证。
