# Gongshu / 公输

<p align="center">
  <strong>비전 기반 로봇 매니퓰레이션 연구 플랫폼</strong>
</p>

<p align="center">
  <a href="README.md">简体中文</a> ·
  <a href="README_EN.md">English</a> ·
  <a href="README_JA.md">日本語</a> ·
  <a href="README_KO.md">한국어</a>
</p>

<p align="center">
  <a href="https://github.com/PowellWells/gongshu/tree/v0.1.0"><img alt="릴리스 v0.1.0" src="https://img.shields.io/badge/release-v0.1.0-2563eb?style=flat-square"></a>
  <a href="#current-status"><img alt="연구 플랫폼 프로토타입" src="https://img.shields.io/badge/status-research%20prototype-0f766e?style=flat-square"></a>
  <a href="pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white"></a>
  <a href="#requirements"><img alt="Windows 11" src="https://img.shields.io/badge/platform-Windows%2011-0078D4?style=flat-square&amp;logo=windows11&amp;logoColor=white"></a>
  <a href="tests"><img alt="테스트 197개 통과" src="https://img.shields.io/badge/tests-197%20passed-brightgreen?style=flat-square"></a>
  <a href="https://github.com/PowellWells/gongshu/stargazers"><img alt="GitHub Stars" src="https://img.shields.io/github/stars/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="https://github.com/PowellWells/gongshu/issues"><img alt="GitHub Issues" src="https://img.shields.io/github/issues/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="#license-and-third-party-notice"><img alt="프로젝트 라이선스 미선언" src="https://img.shields.io/badge/license-not%20declared-lightgrey?style=flat-square"></a>
</p>

Gongshu는 실제 비전 입력, 공간 이해, 파지 계획, 시뮬레이션 검증을 연결하는 데스크톱 연구 플랫폼입니다.

![Gongshu 콘셉트 커버](assets/demo-cover.png)

> 프로젝트 콘셉트 이미지입니다. v0.1.0의 실제 기능 범위는 Current Status와 Features를 기준으로 합니다.

## Overview

Gongshu는 카메라 입력부터 MuJoCo 검증까지 비전 기반 로봇 매니퓰레이션 연구를 위한 통합 워크스페이스를 제공합니다. 대상 인식, 깊이와 포인트 클라우드, 파지 후보, 물리 시뮬레이션을 추적 가능한 하나의 흐름으로 구성하여 중간 결과 확인, 시각 조건 비교, 실험 재현을 지원합니다.

현재 버전은 소프트웨어 플랫폼과 시뮬레이션 연구에 초점을 둡니다. 동일한 신뢰할 수 있는 LAN의 휴대전화 카메라에서 실제 RGB 영상을 입력받고, Franka Panda의 파지 동작을 MuJoCo에서 검증합니다. 시뮬레이션 결과를 실제 로봇 실험 결과로 표현하지 않습니다.

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

v0.1.0에는 Phone Camera RGB 입력이 구현되어 있습니다. RGB-D Camera는 향후 확장 항목입니다. 현재 단안 깊이 출력은 연구와 시뮬레이션 워크플로를 위한 것이며, 보정된 RGB-D 센서의 실제 스케일 측정과 동일하지 않습니다.

## Features

- **Desktop Research Workspace**: Live RGB, 공간 인식, 파지 계획, MuJoCo 검증을 함께 보여 주는 4분할 워크스페이스.
- **Phone Camera RGB Input**: 신뢰할 수 있는 사설 LAN을 통한 휴대전화 실시간 RGB 영상과 고해상도 촬영 입력.
- **Camera Setup / QR Pairing**: 로컬 CA, 단기 페어링 토큰, QR 안내 기반 카메라 연결.
- **Real-time Visual Perception**: FastSAM 인스턴스 영역, Mask, Bounding Box Overlay, 클릭 대상 잠금, 경량 추적.
- **Spatial Perception Interface**: 동일한 Scene Snapshot에 연결된 Depth, Point Cloud, 대상 XYZ, 카메라 내부 파라미터 상태.
- **Grasp Planning Interface**: GR-ConvNet 파지 맵, Top-K 후보, 실행 가능성 검사, 후보 순위화.
- **MuJoCo Validation Interface**: Franka Panda 동역학 시뮬레이션, 결과 상태, 세션 내 Recording과 Replay.
- **Multi-condition Testing Interface**: Normal, Blur, Low-Light 및 복합 조건의 설명 가능한 처리와 Research Mode 스트레스 테스트.

## Demo

### Demo Video

[Gongshu v0.1.0 데모 영상 보기 / 다운로드](https://github.com/PowellWells/gongshu/releases/download/v0.1.0/gongshu-v0.1.0-demo.mp4)

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

**현재 버전: Research Platform Prototype v0.1.0**

소프트웨어 연구 플랫폼, 실제 RGB 입력 경로, 시뮬레이션 검증 워크플로가 구현되어 있습니다. 실제 로봇 배포는 실험 장비와 조건이 마련된 이후 진행할 예정입니다. 이 릴리스에는 실제 로봇의 엔드투엔드 배포가 포함되지 않으며 단안 깊이 또는 MuJoCo 출력을 실제 하드웨어 측정값으로 표현하지 않습니다.

## Future Extension

- RGB-D Camera
- Real Robot Integration
- 6D Grasp Research

## License and Third-Party Notice

현재 이 저장소에는 프로젝트 수준의 오픈 소스 라이선스가 선언되어 있지 않습니다. 서드파티 코드, 모델, 런타임에는 각각의 라이선스가 적용됩니다. 사용하거나 재배포하기 전에 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 확인하십시오.
