# Gongshu / 公输

<p align="center">
  <strong>Modular Robot Vision and Grasping Experimentation Platform</strong>
</p>

<p align="center">
  <a href="README.md">简体中文</a> ·
  <a href="README_EN.md">English</a> ·
  <a href="README_JA.md">日本語</a> ·
  <a href="README_KO.md">한국어</a>
</p>

<p align="center">
  <a href="https://github.com/PowellWells/gongshu/tree/v0.1.0"><img alt="版本 v0.1.0" src="https://img.shields.io/badge/release-v0.1.0-2563eb?style=flat-square"></a>
  <a href="#current-status"><img alt="开源基线" src="https://img.shields.io/badge/status-open--source%20baseline-0f766e?style=flat-square"></a>
  <a href="pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white"></a>
  <a href="#requirements"><img alt="Windows 11" src="https://img.shields.io/badge/platform-Windows%2011-0078D4?style=flat-square&amp;logo=windows11&amp;logoColor=white"></a>
  <a href="tests"><img alt="197 项测试通过" src="https://img.shields.io/badge/tests-197%20passed-brightgreen?style=flat-square"></a>
  <a href="https://github.com/PowellWells/gongshu/stargazers"><img alt="GitHub Stars" src="https://img.shields.io/github/stars/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="https://github.com/PowellWells/gongshu/issues"><img alt="GitHub Issues" src="https://img.shields.io/github/issues/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="LICENSE"><img alt="Apache-2.0 开源许可证" src="https://img.shields.io/badge/license-Apache--2.0-2563eb?style=flat-square"></a>
</p>

Gongshu 是一个面向机器人视觉与抓取研究的模块化实验平台，连接视觉输入、空间理解、抓取规划与仿真验证。

![Gongshu 项目概念宣传图](assets/demo-cover.png)

> 项目概念宣传图 Concept Cover。v0.1.0 的实际能力边界以本文的 Current Status 与 Features 为准。

## Overview

Gongshu 为视觉驱动机器人操作实验提供可追踪的工作流，覆盖 RGB 输入、兼容的 RGB-D 数据接口、目标感知、深度与点云处理、空间理解、抓取候选生成，以及 MuJoCo / robosuite 仿真验证。工作台用于检查中间结果、比较处理条件并保存可复现实验产物。

v0.1.0 的真实视觉输入由同一可信局域网内的手机摄像头提供；RGB-D 由仿真或兼容数据源接口提供。Franka Panda 抓取在 MuJoCo / robosuite 中验证。本版本不包含经过验证的真实机器人端到端抓取，也不将单目深度或仿真结果表述为真实硬件测量。

## Pipeline

![Gongshu 研究流程](assets/pipeline.png)

```text
Phone Camera / RGB-D Camera
              ↓
      Visual Perception
              ↓
     Spatial Understanding
              ↓
       Grasp Planning
              ↓
      MuJoCo Validation
```

v0.1.0 已实现 Phone Camera RGB 输入，并提供仿真和兼容数据源的 RGB-D 处理接口；真实 RGB-D Camera 接入仍是后续扩展方向。当前单目深度输出用于研究与仿真流程，不等同于经过 RGB-D 传感器标定的真实尺度测量。

## Features

- **Desktop Research Workspace**：四视图研究工作区集中展示实时视觉、空间感知、抓取规划与 MuJoCo 验证。
- **Phone Camera RGB Input**：手机通过可信私有局域网向 PC 提供实时 RGB 视频和高清拍照输入。
- **Camera Setup / QR Pairing**：本地 CA、短时配对令牌与二维码引导的局域网相机连接流程。
- **Real-time Visual Perception**：FastSAM 实例区域、Mask 与 Bounding Box Overlay，并支持目标点击锁定和轻量跟踪。
- **Spatial Perception Interface**：同一 Scene Snapshot 上的 Depth、Point Cloud、目标 XYZ 与相机内参状态展示。
- **Grasp Planning Interface**：GR-ConvNet 抓取图、Top-K 候选、可执行性检查和候选排名。
- **MuJoCo / robosuite Validation Interface**：Franka Panda 连续动力学仿真、结果状态、会话内 Recording 与 Replay。
- **Multi-condition Testing Interface**：Normal、Blur、Low-Light 与组合条件下的可解释处理和 Research Mode 压力测试。

## Demo

### Gongshu v0.1.0 概览

<video src="GITHUB_USER_ATTACHMENT_VIDEO_URL" controls width="100%">
</video>

Gongshu v0.1.0 演示视频展示机器人视觉与抓取实验平台的完整流程，包括视觉输入、目标感知、空间理解、抓取规划以及 MuJoCo 仿真验证。

视频文件同时保存在 GitHub Release Assets 中，方便下载查看：[下载 Gongshu v0.1.0 演示视频](https://github.com/PowellWells/gongshu/releases/download/v0.1.0/gongshu-v0.1.0-demo.mp4)。

### Project Screenshots

![Gongshu 桌面研究工作区](assets/overview.png)

上图为真实 Gongshu 桌面研究工作区启动状态。相机接入后，Live RGB 会显示实时画面、目标区域和锁定状态，其余视图沿同一目标快照更新。

## Quick Start

### Requirements

- Windows 11（当前验证平台）
- Python 3.12.x（`>=3.12,<3.13`）
- Phone Camera 功能需要手机与 PC 位于同一可信私有局域网
- CUDA 为可选项；无可用 GPU 时保留 CPU fallback

### Installation

```powershell
git clone https://github.com/PowellWells/gongshu.git
cd gongshu
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

`pyproject.toml` 是项目依赖的权威来源；`requirements.txt` 提供常规环境安装入口：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

模型权重不随 Git 源码仓库发布。FastSAM、Depth Anything V2 与 GR-ConvNet 会按项目既有的模型解析规则查找本地 Release Bundle、`artifacts/models/`、用户缓存或官方来源；具体来源和许可证边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

### Launch

直接打开 Gongshu：

```text
Start-Vision2Grasp.cmd
```

或从 XUANSHU LAB 门户进入：

```text
Start-XUANSHU-LAB.cmd
```

PowerShell 启动方式：

```powershell
.\.venv\Scripts\python.exe .\run_vision2grasp_app.py
```

默认工作台地址为 `http://127.0.0.1:8765/apps/gongshu/index.html`。首次连接手机时，在 Gongshu 中打开 **连接设置 Camera Setup**，按本地 CA 与 Pairing 二维码引导完成连接。

## Project Structure

```text
gongshu/
├── assets/                     GitHub README 展示素材
├── configs/                    默认实验配置
├── contracts/                  运行结果数据契约
├── frontend/                   Gongshu 与 XUANSHU LAB 前端
├── scripts/                    启动、基准与发布脚本
├── src/vision2grasp/           感知、空间、抓取、控制与仿真模块
├── src/xuanshu_lab/            桌面研究平台运行层
├── tests/                      单元测试与集成测试
├── requirements.txt            环境安装依赖
├── VERSION.md                  发布版本信息
└── run_vision2grasp_app.py     Gongshu 本地服务入口
```

运行时生成的模型、证书、相机 Session、用户数据、实验输出和日志位于被 Git 忽略的本地目录，不随源码发布。

## Validation

```powershell
.\.venv\Scripts\python.exe -m compileall -q .\src .\tests .\run_vision2grasp_app.py .\run_bottle_pipeline.py .\stage0_lift_smoke.py
.\.venv\Scripts\python.exe -m unittest discover -s .\tests -v
.\.venv\Scripts\python.exe -m pip check
node --check .\frontend\apps\gongshu\gongshu.js
node --check .\frontend\apps\gongshu\real-scene.js
node --check .\frontend\apps\gongshu\phone-camera\phone-camera.js
```

## Current Status

**当前版本 Current version：Open-Source Baseline v0.1.0**

v0.1.0 建立了 Apache-2.0 项目许可、开源范围与治理冻结基线，并保留现有视觉输入、空间理解、抓取规划和仿真验证能力。真实机器人部署仍属于后续方向；本版本不包含经过验证的真实机器人端到端能力。

## Future Extension

- RGB-D Camera
- Real Robot Integration
- 6D Grasp Research

## License and Third-Party Notice

Gongshu 自有源码采用 [Apache License 2.0](LICENSE)。第三方代码、模型、素材与运行时保留各自许可证；Apache-2.0 声明不覆盖这些第三方内容。使用或再分发前请阅读 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 [GONGSHU_SCOPE.md](GONGSHU_SCOPE.md)。
