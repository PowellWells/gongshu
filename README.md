# 公输 Gongshu Robotics · Vision2Grasp

Vision2Grasp 现在采用 **Real-world-first, Simulation-validated** 路线：默认直接读取电脑摄像头、Android 网络摄像头或单张照片，只识别 `bottle`，在真实画面上完成检测、桌面平面定位与顶抓候选规划；原有 MuJoCo / robosuite 单瓶抓取闭环完整保留在 Simulation Mode 中用于验证。

继续开发前请先阅读 [CODEX_HANDOFF.md](CODEX_HANDOFF.md)。

## 一键使用

Windows 下双击项目根目录的 [Start-Vision2Grasp.cmd](Start-Vision2Grasp.cmd)。启动器会启动统一的本地应用并打开公输工作台，默认进入 **REAL SCENE MODE**，不会先强制运行耗时的仿真。

首次使用电脑摄像头：

1. 把电脑摄像头固定在桌面上方或斜上方，之后不要移动相机。
2. 在桌面划定一个长方形测量区域，用尺子量出实际宽度和高度，填入页面的毫米输入框。
3. 点击“四点标定”，依次点击画面中的 **原点、+X、+X+Y、+Y** 四个角。
4. 把一个 `bottle` 放进标定区域。页面会显示类别、置信度、桌面坐标、平面朝向、估计夹爪开口和三个候选。

输入来源：

- **电脑摄像头**：启动后默认使用索引 0。
- **Android**：手机与电脑连接同一 Wi-Fi；在手机网络摄像头应用中启动视频服务，把它提供的 `http://`、`https://` 或 `rtsp://` 视频地址粘贴到页面。
- **单张照片**：点击“选择照片”。换用不同分辨率的照片后，需要针对该照片重新做四点标定。

点击顶部 **SIMULATION MODE** 可回到原有四视图仿真工作台，再点击“运行单瓶仿真”执行固定种子闭环。

> 普通 RGB 摄像头没有真实深度。本项目当前只给出经过尺子标定的桌面平面 `X/Y`；目标尺寸、朝向和夹爪开口明确标为估计值，不会伪造 `Z` 或深度数据。

## 手动启动

```powershell
$env:PYTHONPATH = "G:\Vision2Grasp\src"
& "G:\Vision2Grasp\.venv\Scripts\python.exe" "G:\Vision2Grasp\run_vision2grasp_app.py" --host 127.0.0.1 --port 8765
```

浏览器地址为 `http://127.0.0.1:8765/apps/gongshu/index.html`。真实场景功能依赖本地 API，因此不要改用普通 `python -m http.server`。

## 当前模块

- `sources`：电脑摄像头、Android HTTP/RTSP 视频流和单张 RGB 图像输入。
- `perception`：CPU 版 YOLO11n-seg 实例分割，Real Scene Mode 当前固定只保留 `bottle`。
- `geometry`：真实场景四点桌面标定与平面定位；仿真场景 Mask + Depth 三维反投影。
- `grasp`：真实场景平面顶抓三候选；仿真场景 PCA / 圆拟合顶抓规划。
- `control`：Panda 确定性抓取状态机，仅用于仿真闭环。
- `simulation`：robosuite RGB-D、机器人动作和本体状态。
- `visualization`：真实画面叠加，以及 RGB、Depth、Grasp、MuJoCo 四视图。
- `evaluation`：仿真执行后的隔离评价；主路径不读取物体真值。

跨模块数据通过 `vision2grasp.contracts` 交换。真实 RGB 帧和 RGB-D 帧是不同契约，避免把普通相机数据误称为深度数据。

## 已验证环境

```text
Windows 11
Python 3.12.5
MuJoCo 3.9.0
robosuite 1.5.2
OpenCV 4.11.0
PyTorch 2.13.0+cpu
torchvision 0.28.0+cpu
Ultralytics 8.4.128
```

## 本地检查

```powershell
$env:PYTHONPATH = "G:\Vision2Grasp\src"
& "G:\Vision2Grasp\.venv\Scripts\python.exe" -m compileall -q "G:\Vision2Grasp\src" "G:\Vision2Grasp\tests" "G:\Vision2Grasp\run_vision2grasp_app.py"
& "G:\Vision2Grasp\.venv\Scripts\python.exe" -m unittest discover -s "G:\Vision2Grasp\tests" -v
& "G:\Vision2Grasp\.venv\Scripts\python.exe" -m pip check
```

单独运行原有仿真闭环：

```powershell
& "G:\Vision2Grasp\.venv\Scripts\python.exe" "G:\Vision2Grasp\run_bottle_pipeline.py"
```

## 第三方许可证边界

Ultralytics 软件和官方 YOLO11 预训练权重默认采用 AGPL-3.0。当前只按本地个人 / 研究演示用途使用；如果未来需要闭源、内部商业或产品化部署，必须先确认能够履行 AGPL-3.0 的开源义务，或取得 Ultralytics 商业许可。本仓库目前没有擅自替整个项目选择许可证。

## 尚待现场验收

- 用用户实际 Android 串流地址验证连接稳定性。
- 在真实固定相机下，用尺子选取 5–10 个独立检查点统计桌面平面定位误差。
- 把真实候选坐标映射到 MuJoCo，并将仿真验证结果回写 Real Scene Mode；当前界面诚实显示 `NOT_RUN / VALIDATOR PENDING`。
