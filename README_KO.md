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
  <a href="https://github.com/PowellWells/gongshu/tree/v0.1.0"><img alt="릴리스 v0.1.0" src="https://img.shields.io/badge/release-v0.1.0-2563eb?style=flat-square"></a>
  <a href="#current-status"><img alt="오픈 소스 베이스라인" src="https://img.shields.io/badge/status-open--source%20baseline-0f766e?style=flat-square"></a>
  <a href="pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white"></a>
  <a href="#requirements"><img alt="Windows 11" src="https://img.shields.io/badge/platform-Windows%2011-0078D4?style=flat-square&amp;logo=windows11&amp;logoColor=white"></a>
  <a href="tests"><img alt="테스트 197개 통과" src="https://img.shields.io/badge/tests-197%20passed-brightgreen?style=flat-square"></a>
  <a href="https://github.com/PowellWells/gongshu/stargazers"><img alt="GitHub Stars" src="https://img.shields.io/github/stars/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="https://github.com/PowellWells/gongshu/issues"><img alt="GitHub Issues" src="https://img.shields.io/github/issues/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="LICENSE"><img alt="Apache-2.0 라이선스" src="https://img.shields.io/badge/license-Apache--2.0-2563eb?style=flat-square"></a>
</p>

Gongshu는 시각 입력, 공간 이해, 파지 계획, 시뮬레이션 검증을 연결하는 로봇 비전 및 파지 연구용 모듈형 실험 플랫폼입니다.

![Gongshu 콘셉트 커버](assets/demo-cover.png)

> 프로젝트 콘셉트 이미지입니다. v0.1.0의 실제 기능 범위는 Current Status와 Features를 기준으로 합니다.

## Overview

Gongshu는 비전 기반 로봇 조작 실험을 위한 추적 가능한 워크플로를 제공하며 RGB 입력, 호환 RGB-D 데이터 인터페이스, 대상 인식, 깊이 및 포인트 클라우드 처리, 공간 이해, 파지 후보 생성, MuJoCo / robosuite 검증을 다룹니다. 워크스페이스에서 중간 결과를 확인하고 처리 조건을 비교하며 재현 가능한 실행 산출물을 저장할 수 있습니다.

v0.1.0의 실제 영상 입력은 동일한 신뢰할 수 있는 LAN의 휴대전화 카메라에서 제공되며, RGB-D 데이터는 시뮬레이션 또는 호환 데이터 소스 인터페이스를 통해 제공됩니다. Franka Panda 파지는 MuJoCo / robosuite에서 검증됩니다. 이 릴리스에는 검증된 실제 로봇 엔드투엔드 파지 시스템이 포함되지 않으며, 단안 깊이나 시뮬레이션 결과를 실제 하드웨어 측정값으로 표현하지 않습니다.

## Pipeline

![Gongshu 연구 파이프라인](assets/pipeline.png)

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

v0.1.0에는 Phone Camera RGB 입력이 구현되어 있으며, 시뮬레이션 및 호환 데이터 소스를 위한 RGB-D 처리 인터페이스가 제공됩니다. 실제 RGB-D Camera 통합은 향후 확장 항목입니다. 현재 단안 깊이 출력은 연구와 시뮬레이션 워크플로를 위한 것이며, 보정된 RGB-D 센서의 실제 스케일 측정과 동일하지 않습니다.

## Features

- **Desktop Research Workspace**: Live RGB, 공간 인식, 파지 계획, MuJoCo 검증을 함께 보여 주는 4분할 워크스페이스.
- **Phone Camera RGB Input**: 신뢰할 수 있는 사설 LAN을 통한 휴대전화 실시간 RGB 영상과 고해상도 촬영 입력.
- **Camera Setup / QR Pairing**: 로컬 CA, 단기 페어링 토큰, QR 안내 기반 카메라 연결.
- **Real-time Visual Perception**: FastSAM 인스턴스 영역, Mask, Bounding Box Overlay, 클릭 대상 잠금, 경량 추적.
- **Spatial Perception Interface**: 동일한 Scene Snapshot에 연결된 Depth, Point Cloud, 대상 XYZ, 카메라 내부 파라미터 상태.
- **Grasp Planning Interface**: GR-ConvNet 파지 맵, Top-K 후보, 실행 가능성 검사, 후보 순위화.
- **MuJoCo / robosuite Validation Interface**: Franka Panda 동역학 시뮬레이션, 결과 상태, 세션 내 Recording과 Replay.
- **Multi-condition Testing Interface**: Normal, Blur, Low-Light 및 복합 조건의 설명 가능한 처리와 Research Mode 스트레스 테스트.

## Demo

### Gongshu v0.1.0 개요

<video src="GITHUB_USER_ATTACHMENT_VIDEO_URL" controls width="100%">
</video>

Gongshu v0.1.0 데모는 시각 입력, 대상 인식, 공간 이해, 파지 계획, MuJoCo 기반 검증으로 이어지는 실험 워크플로를 보여 줍니다.

동영상 파일은 다운로드해서 확인할 수 있도록 GitHub Release Assets에도 보관됩니다: [Gongshu v0.1.0 데모 동영상 다운로드](https://github.com/PowellWells/gongshu/releases/download/v0.1.0/gongshu-v0.1.0-demo.mp4).

### Project Screenshots

![Gongshu 데스크톱 연구 워크스페이스](assets/overview.png)

위 이미지는 실제 Gongshu 시작 화면입니다. 카메라 연결 후 Live RGB에 영상, 대상 영역, 잠금 상태가 표시되며 다른 뷰는 동일한 대상 스냅샷을 기준으로 갱신됩니다.

## Quick Start

### Requirements

- Windows 11(현재 검증된 플랫폼)
- Python 3.12.x(`>=3.12,<3.13`)
- Phone Camera 사용 시 휴대전화와 PC가 동일한 신뢰할 수 있는 사설 LAN에 연결되어 있어야 함
- CUDA는 선택 사항이며 CPU fallback을 사용할 수 있음

### Installation

```powershell
git clone https://github.com/PowellWells/gongshu.git
cd gongshu
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

`pyproject.toml`이 의존성의 기준 문서입니다. 일반적인 환경 설치를 위해 `requirements.txt`도 제공합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

모델 가중치는 Git 저장소에 포함되지 않습니다. FastSAM, Depth Anything V2, GR-ConvNet은 기존 탐색 순서에 따라 로컬 Release Bundle, `artifacts/models/`, 사용자 캐시, 공식 배포처를 확인합니다. 출처와 라이선스 범위는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 확인하십시오.

### Launch

Gongshu 직접 실행:

```text
Start-Vision2Grasp.cmd
```

XUANSHU LAB 포털에서 실행:

```text
Start-XUANSHU-LAB.cmd
```

PowerShell 실행:

```powershell
.\.venv\Scripts\python.exe .\run_vision2grasp_app.py
```

기본 워크스페이스 URL은 `http://127.0.0.1:8765/apps/gongshu/index.html`입니다. 휴대전화를 처음 연결할 때는 Gongshu에서 **Camera Setup**을 열고 로컬 CA와 Pairing QR 안내를 따르십시오.

## Project Structure

```text
gongshu/
├── assets/                     GitHub README 자료
├── configs/                    기본 실험 설정
├── contracts/                  실행 결과 데이터 계약
├── frontend/                   Gongshu 및 XUANSHU LAB 프런트엔드
├── scripts/                    실행, 벤치마크, 릴리스 스크립트
├── src/vision2grasp/           인식, 공간, 파지, 제어, 시뮬레이션 모듈
├── src/xuanshu_lab/            데스크톱 연구 플랫폼 런타임
├── tests/                      단위 및 통합 테스트
├── requirements.txt            환경 의존성
├── VERSION.md                  릴리스 버전 정보
└── run_vision2grasp_app.py     Gongshu 로컬 서비스 진입점
```

런타임 모델, 인증서, 카메라 세션, 사용자 데이터, 실험 출력, 로그는 Git에서 제외된 로컬 디렉터리에 저장되며 소스 릴리스에 포함되지 않습니다.

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

**현재 버전: Open-Source Baseline v0.1.0**

v0.1.0은 Apache-2.0 프로젝트 라이선스, 오픈 소스 범위, 거버넌스 동결 베이스라인을 확립하면서 기존 시각 입력, 공간 이해, 파지 계획, 시뮬레이션 검증 기능을 유지합니다. 실제 로봇 배포는 향후 과제이며, 이 릴리스에는 검증된 실제 로봇 엔드투엔드 기능이 포함되지 않습니다.

## Future Extension

- RGB-D Camera
- Real Robot Integration
- 6D Grasp Research

## License and Third-Party Notice

Gongshu가 소유한 소스 코드는 [Apache License 2.0](LICENSE)에 따라 제공됩니다. 서드파티 코드, 모델, 자산, 런타임에는 각각의 라이선스가 적용되며 저장소의 Apache-2.0 선언 범위에 포함되지 않습니다. 사용하거나 재배포하기 전에 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)와 [GONGSHU_SCOPE.md](GONGSHU_SCOPE.md)를 확인하십시오.
