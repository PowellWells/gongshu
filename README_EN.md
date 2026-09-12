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
  <a href="https://github.com/PowellWells/gongshu/tree/v0.1.0"><img alt="Release v0.1.0" src="https://img.shields.io/badge/release-v0.1.0-2563eb?style=flat-square"></a>
  <a href="#roadmap"><img alt="Open-source baseline" src="https://img.shields.io/badge/status-open--source%20baseline-0f766e?style=flat-square"></a>
  <a href="pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white"></a>
  <a href="#requirements"><img alt="Windows 11" src="https://img.shields.io/badge/platform-Windows%2011-0078D4?style=flat-square&amp;logo=windows11&amp;logoColor=white"></a>
  <a href="tests"><img alt="197 tests passed" src="https://img.shields.io/badge/tests-197%20passed-brightgreen?style=flat-square"></a>
  <a href="https://github.com/PowellWells/gongshu/stargazers"><img alt="GitHub Stars" src="https://img.shields.io/github/stars/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="https://github.com/PowellWells/gongshu/issues"><img alt="GitHub Issues" src="https://img.shields.io/github/issues/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="LICENSE"><img alt="Apache-2.0 License" src="https://img.shields.io/badge/license-Apache--2.0-2563eb?style=flat-square"></a>
</p>

Gongshu is an open-source, modular experimentation platform for robot vision, spatial understanding, grasp planning, and simulation validation.

![Gongshu concept cover](assets/demo-cover.png)

> Project concept cover. This document defines the actual capability boundaries of v0.1.0.

## Overview

Gongshu helps researchers organize robot-vision and grasping experiments in one workspace and inspect intermediate results from input through simulation validation. The current open-source baseline focuses on four capability areas:

- **RGB / RGB-D visual input**: phone-camera RGB input plus RGB-D data interfaces for simulation or compatible data sources.
- **Spatial understanding**: depth, point clouds, target XYZ coordinates, and camera-intrinsics information.
- **Grasp planning**: grasp-candidate generation, feasibility checks, and ranking for result comparison.
- **Simulation validation**: experimental grasp validation with MuJoCo / robosuite and Franka Panda.

v0.1.0 is the Gongshu open-source baseline. Real visual input currently comes from a phone camera on the same trusted LAN; physical RGB-D camera integration remains a future direction. This release does not include validated end-to-end real-robot grasping and does not present monocular depth or simulation results as physical-hardware measurements.

## Demo

### Gongshu v0.1.0 Overview

<video src="https://github.com/user-attachments/assets/12a7abca-c202-45ff-b3dd-485dfb8e599a" controls width="100%">
</video>

The demo shows the Gongshu v0.1.0 experience across visual input, target perception, spatial understanding, grasp planning, and MuJoCo-based simulation validation.

The video is also available in GitHub Release Assets: [Download the Gongshu v0.1.0 demo video](https://github.com/PowellWells/gongshu/releases/download/v0.1.0/gongshu-v0.1.0-demo.mp4).

## Quick Start — Run Gongshu in 5 Minutes

### Requirements

- Windows 11 (currently validated platform)
- Python 3.12.x (`>=3.12,<3.13`)
- A phone and PC on the same trusted private LAN for Phone Camera input
- CUDA is optional; CPU fallback remains available

### Installation

```powershell
git clone https://github.com/PowellWells/gongshu.git
cd gongshu
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

`pyproject.toml` is the authoritative dependency source. The conventional `requirements.txt` installation entry is also available:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Model weights are not distributed in the Git source repository. FastSAM, Depth Anything V2, and GR-ConvNet follow the project's existing resolver order across a local Release Bundle, `artifacts/models/`, the user cache, and official sources. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for source and license boundaries.

### Launch

Open Gongshu directly:

```text
Start-Vision2Grasp.cmd
```

Or launch it with PowerShell:

```powershell
.\.venv\Scripts\python.exe .\run_vision2grasp_app.py
```

The default workspace URL is `http://127.0.0.1:8765/apps/gongshu/index.html`. For the first phone connection, open **Camera Setup** in Gongshu and follow the local CA and pairing QR instructions.

You can also enter through the existing XUANSHU LAB portal:

```text
Start-XUANSHU-LAB.cmd
```

<details>
<summary>Repository layout</summary>

```text
gongshu/
├── assets/                     GitHub README assets
├── configs/                    Default experiment configuration
├── contracts/                  Run-result data contracts
├── frontend/                   Gongshu and XUANSHU LAB frontend
├── scripts/                    Launch, benchmark, and release scripts
├── src/vision2grasp/           Perception, spatial, grasp, control, and simulation modules
├── src/xuanshu_lab/            Desktop research-platform runtime
├── tests/                      Unit and integration tests
├── requirements.txt            Environment dependencies
├── VERSION.md                  Release version information
└── run_vision2grasp_app.py     Gongshu local-service entry point
```

Runtime models, certificates, camera sessions, user data, experiment outputs, and logs are stored in Git-ignored local directories and are not included in the source release.

</details>

## Features

### Visual Perception

Accepts RGB / RGB-D data and provides target regions, masks, bounding-box overlays, target locking, and lightweight tracking.

### Spatial Understanding

Displays depth, point clouds, target XYZ coordinates, and camera-intrinsics status on the same Scene Snapshot.

### Grasp Planning

Provides GR-ConvNet grasp maps, Top-K grasp candidates, feasibility checks, and candidate ranking.

### Simulation Validation

Runs continuous-dynamics simulation with MuJoCo / robosuite and Franka Panda, with in-session recording and replay.

### Experiment Workspace

Uses a four-view workspace for visual, spatial, grasping, and simulation results, with Normal, Blur, Low-Light, and other experimental conditions.

### Modular Extension

Modular interfaces support future compatible data sources, research modules, and grasp algorithms while keeping the core platform boundary clear.

## System Preview / Screenshots

![Gongshu desktop research workspace](assets/overview.png)

The screenshot shows the Gongshu desktop research workspace at startup. After camera connection, Live RGB displays the stream, target regions, and lock state; the other views update from the same target snapshot.

## Roadmap

- [x] **v0.1 Open-source baseline**: establish the Apache-2.0 license, open-source scope, governance baseline, and current experiment workspace.
- [ ] **RGB-D camera integration**: a future extension direction; specific hardware and timing have not been determined.
- [ ] **More grasp-algorithm support**: to be evaluated incrementally based on reproducibility, license compatibility, and maintenance capacity.
- [ ] **Real-robot validation**: a future research direction, not a claim of current end-to-end real-robot capability.

The roadmap communicates maintenance directions and is not a commitment to specific features or release dates.

## Contributing

Reproducible bug reports, documentation improvements, tests, and platform contributions within the project boundary are welcome. Read the [contribution guide](CONTRIBUTING.md) and [community code of conduct](CODE_OF_CONDUCT.md) before participating. Report security issues privately according to the [security policy](SECURITY.md).

Before opening a pull request, run the checks relevant to your change. The current baseline commands are:

```powershell
.\.venv\Scripts\python.exe -m compileall -q .\src .\tests .\run_vision2grasp_app.py .\run_bottle_pipeline.py .\stage0_lift_smoke.py
.\.venv\Scripts\python.exe -m unittest discover -s .\tests -v
.\.venv\Scripts\python.exe -m pip check
node --check .\frontend\apps\gongshu\gongshu.js
node --check .\frontend\apps\gongshu\real-scene.js
node --check .\frontend\apps\gongshu\phone-camera\phone-camera.js
```

## License

Gongshu-owned source code is licensed under the [Apache License 2.0](LICENSE). Third-party code, models, assets, and runtimes retain their respective licenses and are not covered by the repository's Apache-2.0 declaration. Read [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [GONGSHU_SCOPE.md](GONGSHU_SCOPE.md) before use or redistribution.
