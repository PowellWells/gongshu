# XUANSHU LAB · 玄枢实验室

XUANSHU LAB v0.1 是一个真正可运行的 Windows AI / 机器人科研桌面平台。当前版本优先完成成熟、稳定、可扩展的软件骨架，不宣称一次性完成全部机器人或世界模型算法。

桌面容器使用 PySide6，但所有用户可见的产品界面仍由原版 HTML / CSS / JavaScript 提供。`QWebEngineView` 铺满 Windows 窗口，直接载入原开机动画、玄枢门户和各 Workspace；PySide6 只负责窗口、本地服务生命周期、日志、单实例和后续打包。

## 一键启动

双击项目根目录的 [Start-XUANSHU-LAB.cmd](Start-XUANSHU-LAB.cmd)。

启动器会：

1. 使用项目虚拟环境启动 PySide6 桌面程序；
2. 启动或复用 `127.0.0.1:8765` 上兼容的本地科研服务；
3. 播放原版 HTML 开机动画，进入原版玄枢门户，并在同一窗口内运行 Workspace；
4. 再次双击时唤醒已有窗口，不重复启动平台实例。

原 [Start-Vision2Grasp.cmd](Start-Vision2Grasp.cmd) 继续保留，供只启动公输 Web 工作台时使用。

## Jingwei Camera v1 · Local RGB Acquisition

公输真实场景页当前冻结为纯摄像头接入版本，不启动 YOLO、Depth、点云、Grasp 或 MuJoCo。两个正式输入能力会同时随本地服务启动：

```text
LAN Live    手机后置摄像头 → LAN WebRTC → PC 持续 RGB Frames → CAMERA INPUT 实时画面
LAN Capture 手机原生高清拍照 → LAN 原图上传 → PC 内存预览 → 用户明确点击后才保存
```

WebRTC 不配置 STUN / TURN，也不使用 Cloudflare；Cloud Relay、Cloud Storage、Internet Upload 和实时录像默认全部关闭。PC 端显示实际收到的分辨率、两秒滚动窗口接收 FPS、数据通道往返时延的一半、连接状态和递增帧版本。实时画面只在内存中保留最新一帧，不落盘。

### 荣耀 Magic4 首次连接

1. 手机与电脑连接同一个普通 Wi-Fi；不要使用开启“客户端隔离”的访客网络，临时关闭手机 VPN。
2. 双击 `Start-XUANSHU-LAB.cmd`，进入“公输 Gongshu”，保持 `REAL SCENE MODE`。
3. Windows 首次询问防火墙权限时，只允许“专用网络”，不要允许公用网络。程序本身不会修改防火墙规则。
4. 先用手机扫描 PC 右侧的 `LOCAL CA SETUP` 二维码，下载 `xuanshu-camera-ca.crt`。
5. 在荣耀设置中搜索“安装证书”，选择“CA 证书 / 从存储设备安装”，核对手机页面与 PC 显示的 SHA-256 指纹后安装。系统可能要求先设置锁屏，并提示该 CA 可检查网络流量；这是 Android 对用户 CA 的标准警示。
6. 完全关闭并重新打开 Chrome，再扫描 `PAIRING` 二维码。二维码中的一次性令牌五分钟后失效，或在成功配对后立即失效。
7. 手机点击 `START CAMERA`，允许后置摄像头；点击 `START LIVE` 后，PC 的 `CAMERA INPUT` 应持续显示实时画面及 FPS、分辨率、延迟和状态。
8. 在同一手机页面切换到 `CAPTURE` 可调用高清拍照。PC 收到原始 JPEG / PNG / WebP 后仅保存在内存；只有点击 PC 的“保存高清原图”才写入 `artifacts/camera/captures/`。

本地 CA 只需在同一部手机安装一次。CA 私钥和服务端私钥位于 Git 忽略的 `artifacts/camera/secrets/`，不得复制到手机、提交 Git 或公开分享。若电脑 LAN IP 改变，服务会在下次启动时为当前私网地址重新签发服务端证书，手机无需重新安装 CA。

### 连接排查

- 扫码后页面打不开：确认手机和 PC 在同一网段、Wi-Fi 没有客户端隔离、Windows 网络类型是“专用”，并允许 Python 访问专用网络；配对使用 TCP `8766`（HTTPS）和 `8767`（首次证书设置），WebRTC Live 还会在同一私网内协商临时 UDP 端口，不需要路由器端口转发。
- 页面显示 `HTTPS REQUIRED`：本地 CA 尚未成功安装或 Chrome 尚未重启；不要跳过浏览器证书警告继续使用。
- 已配对但没有画面：手机必须先允许摄像头，再点击 `START LIVE`；PC 状态应从 `PAIRED → CONNECTING → LIVE`，且 `frame_revision` 持续增长。
- 断线后：在 PC 点击“生成新配对”，重新扫码即可，不需要重启整个程序；旧 Session 会立即失效。
- 二维码指向错误网卡：关闭不使用的虚拟网卡 / VPN 后重启平台，或开发运行时显式配置正确 LAN 地址。

CameraProvider 的稳定输出边界是 `RGB Frame + Timestamp + Resolution + Camera Source + Camera Status`。当前实现为 `PhoneLANProvider`，前端已保留 USB / Network Stream / RGB-D 状态，但本版本不声称它们已经可用。

## 三个 Workspace

- **经纬 · Jingwei Moment**：可运行的本地图像理解工作台。
- **公输 · Gongshu Vision2Grasp**：可运行的真实场景优先、MuJoCo 仿真验证机器人抓取工作台；当前真实目标固定为 `bottle`。
- **河图 · Hetu Preview**：沿用原门户中的世界模型预告入口；不运行未完成模型，不显示虚假结果。

经纬和公输页面都提供“返回玄枢主页”入口；桌面层另保留 `Alt+Home` 作为备用返回快捷键。`F5` 或 `Ctrl+R` 刷新当前页面，`Ctrl+Shift+L` 临时显示或隐藏本地运行日志。

## 软件架构

```text
Start-XUANSHU-LAB.cmd
→ run_xuanshu_lab.py
→ xuanshu_lab.app（启动、单实例）
→ xuanshu_lab.shell（Windows 窗口、隐藏日志、快捷键）
→ 全窗口 QWebEngineView → /index.html
   ├─ 原版 HTML 开机动画
   ├─ 原版玄枢门户
   ├─ Jingwei Moment → /apps/moment/
   ├─ Gongshu Grasp  → /apps/gongshu/
   └─ Hetu Preview   → 原门户预告入口
→ LocalServiceController
→ run_vision2grasp_app.py / 本地 API / 现有算法模块
```

Workspace 的框架无关契约位于 `src/xuanshu_lab/contracts.py`，默认注册表位于 `src/xuanshu_lab/registry.py`。新增研究域应注册新的 `WorkspaceSpec` 并在门户提供对应前端入口，不应把领域 UI 或算法写进桌面 Shell。

## 开发运行

```powershell
$env:PYTHONPATH = "G:\Vision2Grasp\src"
& "G:\Vision2Grasp\.venv\Scripts\python.exe" "G:\Vision2Grasp\run_xuanshu_lab.py"
```

安装或修复环境：

```powershell
& "G:\Vision2Grasp\.venv\Scripts\python.exe" -m pip install -e "G:\Vision2Grasp"
```

## 验证

```powershell
$env:PYTHONPATH = "G:\Vision2Grasp\src"
& "G:\Vision2Grasp\.venv\Scripts\python.exe" -m compileall -q "G:\Vision2Grasp\src" "G:\Vision2Grasp\tests" "G:\Vision2Grasp\run_xuanshu_lab.py" "G:\Vision2Grasp\run_vision2grasp_app.py"
& "G:\Vision2Grasp\.venv\Scripts\python.exe" -m unittest discover -s "G:\Vision2Grasp\tests" -v
& "G:\Vision2Grasp\.venv\Scripts\python.exe" -m pip check
```

## 当前冻结环境

```text
Windows 11
Python 3.12.5
PySide6 / Qt 6.8.3
OpenCV 4.11.0
MuJoCo 3.9.0
robosuite 1.5.2
PyTorch 2.13.0+cpu
Ultralytics 8.4.128
aiohttp 3.14.3
aiortc 1.15.0
cryptography 50.0.1
qrcode 8.2
```

## 许可证边界

- PySide6 / Qt 开源版本涉及 LGPLv3；Qt WebEngine 还包含 Chromium 的第三方许可证。未来分发 EXE 时必须同时完成动态链接、许可证文本和第三方声明审计。
- Ultralytics 软件与官方 YOLO11 权重默认采用 AGPL-3.0。当前仅用于本地个人 / 研究演示；闭源、内部商业或产品化前必须履行相应义务或取得商业许可。
- Camera v1 使用 aiortc（BSD-3-Clause）、aiohttp（Apache-2.0，且包含 MIT 许可的传递代码）、cryptography（Apache-2.0 OR BSD-3-Clause）和 qrcode（BSD-3-Clause）。正式分发时应随安装包保留各依赖的许可证与传递依赖声明。
- 本仓库当前没有擅自替整个项目选择统一许可证。

## v0.1 边界

已经完成的是桌面平台、三 Workspace 骨架和现有功能接入。尚未包含：正式安装包 / EXE、自动更新、账户或云同步、Hetu 世界模型算法、真实机器人控制，以及真实抓取候选到 MuJoCo 的完整验证回写。
