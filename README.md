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
```

## 许可证边界

- PySide6 / Qt 开源版本涉及 LGPLv3；Qt WebEngine 还包含 Chromium 的第三方许可证。未来分发 EXE 时必须同时完成动态链接、许可证文本和第三方声明审计。
- Ultralytics 软件与官方 YOLO11 权重默认采用 AGPL-3.0。当前仅用于本地个人 / 研究演示；闭源、内部商业或产品化前必须履行相应义务或取得商业许可。
- 本仓库当前没有擅自替整个项目选择统一许可证。

## v0.1 边界

已经完成的是桌面平台、三 Workspace 骨架和现有功能接入。尚未包含：正式安装包 / EXE、自动更新、账户或云同步、Hetu 世界模型算法、真实机器人控制，以及真实抓取候选到 MuJoCo 的完整验证回写。
