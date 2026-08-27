# XUANSHU LAB · 玄枢实验室

XUANSHU LAB v0.1 是一个真正可运行的 Windows AI / 机器人科研桌面平台。当前版本优先完成成熟、稳定、可扩展的软件骨架，不宣称一次性完成全部机器人或世界模型算法。

桌面外壳使用 PySide6；现有 Web 工作台通过 `QWebEngineView` 嵌入。桌面层统一负责 Workspace 注册、导航、本地服务生命周期、状态、日志、单实例和窗口偏好，各研究域继续独立演进。

## 一键启动

双击项目根目录的 [Start-XUANSHU-LAB.cmd](Start-XUANSHU-LAB.cmd)。

启动器会：

1. 使用项目虚拟环境启动 PySide6 桌面程序；
2. 启动或复用 `127.0.0.1:8765` 上兼容的本地科研服务；
3. 打开 XUANSHU LAB 总览，并在桌面窗口内运行 Workspace；
4. 再次双击时唤醒已有窗口，不重复启动平台实例。

原 [Start-Vision2Grasp.cmd](Start-Vision2Grasp.cmd) 继续保留，供只启动公输 Web 工作台时使用。

## 三个 Workspace

- **经纬 · Jingwei Moment**：可运行的本地图像理解工作台。
- **公输 · Gongshu Vision2Grasp**：可运行的真实场景优先、MuJoCo 仿真验证机器人抓取工作台；当前真实目标固定为 `bottle`。
- **河图 · Hetu Preview**：世界模型软件预告页，展示未来的空间表征、时序预测和仿真桥接模块；不运行未完成模型，不显示虚假结果。

## 软件架构

```text
Start-XUANSHU-LAB.cmd
→ run_xuanshu_lab.py
→ xuanshu_lab.app（启动、单实例、Splash）
→ xuanshu_lab.shell（窗口、导航、日志、状态）
→ WorkspaceRegistry
   ├─ Jingwei Moment   → QWebEngineView → /apps/moment/
   ├─ Gongshu Grasp    → QWebEngineView → /apps/gongshu/
   └─ Hetu Preview     → 原生 PySide6 预告页
→ LocalServiceController
→ run_vision2grasp_app.py / 本地 API / 现有算法模块
```

Workspace 的框架无关契约位于 `src/xuanshu_lab/contracts.py`，默认注册表位于 `src/xuanshu_lab/registry.py`。新增研究域应注册新的 `WorkspaceSpec` 并提供对应页面，不应把领域算法写进桌面 Shell。

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
```

## 许可证边界

- PySide6 / Qt 开源版本涉及 LGPLv3；Qt WebEngine 还包含 Chromium 的第三方许可证。未来分发 EXE 时必须同时完成动态链接、许可证文本和第三方声明审计。
- Ultralytics 软件与官方 YOLO11 权重默认采用 AGPL-3.0。当前仅用于本地个人 / 研究演示；闭源、内部商业或产品化前必须履行相应义务或取得商业许可。
- 本仓库当前没有擅自替整个项目选择统一许可证。

## v0.1 边界

已经完成的是桌面平台、三 Workspace 骨架和现有功能接入。尚未包含：正式安装包 / EXE、自动更新、账户或云同步、Hetu 世界模型算法、真实机器人控制，以及真实抓取候选到 MuJoCo 的完整验证回写。
