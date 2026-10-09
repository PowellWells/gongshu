# Gongshu / 公输

<p align="center">
  <strong>Modular Robot Intelligence and Grasping Experimentation Platform</strong>
</p>

<p align="center">
  <a href="README.md">简体中文</a> ·
  <a href="README_EN.md">English</a> ·
  <a href="README_JA.md">日本語</a> ·
  <a href="README_KO.md">한국어</a>
</p>

<p align="center">
  <a href="https://github.com/PowellWells/gongshu/tree/v0.1.0"><img alt="릴리스 v0.1.0" src="https://img.shields.io/badge/release-v0.1.0-2563eb?style=flat-square"></a>
  <a href="#roadmap"><img alt="오픈 소스 베이스라인" src="https://img.shields.io/badge/status-open--source%20baseline-0f766e?style=flat-square"></a>
  <a href="pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white"></a>
  <a href="#requirements"><img alt="Windows 11" src="https://img.shields.io/badge/platform-Windows%2011-0078D4?style=flat-square&amp;logo=windows11&amp;logoColor=white"></a>
  <a href="tests"><img alt="테스트 197개 통과" src="https://img.shields.io/badge/tests-197%20passed-brightgreen?style=flat-square"></a>
  <a href="https://github.com/PowellWells/gongshu/stargazers"><img alt="GitHub Stars" src="https://img.shields.io/github/stars/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="https://github.com/PowellWells/gongshu/issues"><img alt="GitHub Issues" src="https://img.shields.io/github/issues/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="LICENSE"><img alt="Apache-2.0 라이선스" src="https://img.shields.io/badge/license-Apache--2.0-2563eb?style=flat-square"></a>
</p>

Gongshu는 시각 입력, 공간 이해, 파지 계획, 시뮬레이션 검증, 실험 체계와 지능형 의사결정을 통합하는 오픈 소스 모듈형 로봇 지능 플랫폼입니다. Experiment Lab은 실험 구성과 분석을 담당하고, Xiezhi는 Gongshu 내부의 알고리즘 및 의사결정 기능으로 동작하며 독립 제품이 아닙니다.

현재 제품 아키텍처는 [XUANSHU AI Architecture Freeze v3.0](XUANSHU_ARCHITECTURE_FREEZE_V3.0.md)을 따릅니다.

![Gongshu 콘셉트 커버](assets/demo-cover.png)

> 프로젝트 콘셉트 이미지입니다. v0.1.0의 실제 기능 범위는 이 문서의 설명을 기준으로 합니다.

## Overview

Gongshu는 연구자가 하나의 워크스페이스에서 로봇 비전, 파지 및 지능형 의사결정 실험을 구성하고 입력부터 시뮬레이션 검증까지의 중간 결과를 확인할 수 있도록 지원합니다. 플랫폼은 다음 다섯 가지 기능 영역을 포함합니다.

- **RGB / RGB-D 시각 입력**: 휴대전화 카메라 RGB 입력과 시뮬레이션 또는 호환 데이터 소스를 위한 RGB-D 데이터 인터페이스.
- **공간 이해**: 깊이, 포인트 클라우드, 대상 XYZ 좌표, 카메라 내부 파라미터 등의 공간 정보.
- **파지 계획**: 결과 비교를 위한 파지 후보 생성, 실행 가능성 검사, 순위화.
- **시뮬레이션 검증**: MuJoCo / robosuite와 Franka Panda를 사용한 실험적 파지 검증.
- **실험 및 의사결정 지능**: Experiment Lab이 Trial, 평가 및 비교를 구성하고, 내부 Xiezhi 모듈이 알고리즘 의사결정, 위험 평가 및 전략 발전을 담당합니다.

v0.1.0은 Gongshu의 오픈 소스 베이스라인입니다. 실제 영상 입력은 현재 동일한 신뢰할 수 있는 LAN의 휴대전화 카메라에서 제공되며, 실제 RGB-D 카메라 통합은 향후 방향입니다. 이 릴리스에는 검증된 실제 로봇 엔드투엔드 파지가 포함되지 않으며, 단안 깊이나 시뮬레이션 결과를 실제 하드웨어 측정값으로 표현하지 않습니다.

## Demo

### Gongshu v0.1.0 개요

<video src="https://github.com/user-attachments/assets/12a7abca-c202-45ff-b3dd-485dfb8e599a" controls width="100%">
</video>

데모는 Gongshu v0.1.0의 시각 입력, 대상 인식, 공간 이해, 파지 계획, MuJoCo 기반 시뮬레이션 검증 경험을 보여 줍니다.

동영상은 GitHub Release Assets에서도 받을 수 있습니다: [Gongshu v0.1.0 데모 동영상 다운로드](https://github.com/PowellWells/gongshu/releases/download/v0.1.0/gongshu-v0.1.0-demo.mp4).

## Quick Start — 5분 안에 Gongshu 실행

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

`pyproject.toml`이 의존성의 기준 문서입니다. 일반적인 환경 설치에는 `requirements.txt`도 사용할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

모델 가중치는 Git 소스 저장소에 포함되지 않습니다. FastSAM, Depth Anything V2, GR-ConvNet은 프로젝트의 기존 탐색 순서에 따라 로컬 Release Bundle, `artifacts/models/`, 사용자 캐시, 공식 배포처를 확인합니다. 출처와 라이선스 범위는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 확인하십시오.

### Launch

XUANSHU AI의 유일한 공식 실행 진입점:

```text
G:\Vision2Grasp\Start-Vision2Grasp.cmd
```

이 파일을 두 번 클릭해 XUANSHU AI Launcher로 들어간 뒤 Gongshu를 여십시오. Phone Camera, Local Image, MuJoCo, Experiment Lab과 Xiezhi 알고리즘·의사결정 기능은 Gongshu 내부에서 로드되며 사용자가 Xiezhi를 별도로 실행하지 않습니다. 하위 디렉터리, 개발 브랜치 또는 Git worktree에서 모듈을 따로 실행하지 마십시오. 휴대전화를 처음 연결할 때는 Gongshu에서 **Camera Setup**을 열고 로컬 CA와 Pairing QR 안내를 따르십시오.

<details>
<summary>저장소 구조</summary>

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

</details>

## Features

### Visual Perception

RGB / RGB-D 데이터를 입력받아 대상 영역, Mask, Bounding Box Overlay, 대상 잠금, 경량 추적을 제공합니다.

### Spatial Understanding

동일한 Scene Snapshot에서 깊이, 포인트 클라우드, 대상 XYZ 좌표, 카메라 내부 파라미터 상태를 표시합니다.

### Grasp Planning

GR-ConvNet 파지 맵, Top-K 파지 후보, 실행 가능성 검사, 후보 순위화를 제공합니다.

### Simulation Validation

MuJoCo / robosuite와 Franka Panda를 사용해 연속 동역학 시뮬레이션을 실행하고 세션 내 Recording과 Replay를 지원합니다.

### Experiment Workspace

4분할 워크스페이스에서 시각, 공간, 파지, 시뮬레이션 결과를 보여 주며 Normal, Blur, Low-Light 등의 실험 조건을 지원합니다.

### Modular Extension

모듈형 인터페이스를 통해 핵심 플랫폼의 경계를 유지하면서 향후 호환 데이터 소스, 연구 모듈, 파지 알고리즘을 확장할 수 있습니다.

### 현재 추가된 주요 기능

- **자연어 작업 워크벤치**: 하나의 화면에서 대상과 동작 의도를 입력하고 대상 잠금, 파지 실행 피드백, 후보 상태와 결과 표시를 연결합니다.
- **Xiezhi 의사결정 계층**: 내부 알고리즘 레지스트리, 의사결정·위험·실행 권한 계약, 알고리즘 전환과 행동 비교를 제공합니다. Xiezhi는 Gongshu가 생성한 후보를 평가하며 시각 인식이나 동작 실행을 대체하지 않습니다.
- **Yungang-chan 보조 기능**: 작업 이벤트에 따른 드래그 가능한 시각 피드백을 제공하며 공식 Gongshu Assistant / Xiezhi Decision 표현으로 전환할 수 있습니다. 캐릭터 표현은 플랫폼 흐름을 변경하지 않습니다.
- **Local Image 및 VLM grounding**: 로컬 이미지를 동일한 Scene Snapshot과 대상 참조 경계로 가져옵니다. 모델과 가중치는 선택적인 로컬 자산이며 소스 저장소에 공개하지 않습니다.
- **기하 인식 객체 재구성**: 방향성 바운딩 박스와 solidity 등의 형상 지표를 보존하여 회전된 상자형 객체를 원기둥으로 잘못 분류할 위험을 줄입니다.
- **실험 기록 및 비교**: Trial, Recording, Replay, Normal, Blur, Low-Light와 행동 비교를 지원하고 provenance 및 사용 가능 상태를 유지합니다.

## System Preview / Screenshots

![Gongshu 데스크톱 연구 워크스페이스](assets/overview.png)

위 이미지는 Gongshu 데스크톱 연구 워크스페이스의 시작 상태입니다. 카메라 연결 후 Live RGB에 영상, 대상 영역, 잠금 상태가 표시되며 다른 뷰는 동일한 대상 스냅샷을 기준으로 갱신됩니다.

## Roadmap

- [x] **v0.1 Open-source baseline**: Apache-2.0 라이선스, 오픈 소스 범위, 거버넌스 베이스라인, 현재 실험 워크스페이스 확립.
- [ ] **RGB-D 카메라 통합**: 향후 확장 방향이며 구체적인 장비와 일정은 아직 정해지지 않았습니다.
- [ ] **더 많은 파지 알고리즘 지원**: 재현성, 라이선스 호환성, 유지보수 역량을 기준으로 단계적으로 평가합니다.
- [ ] **실제 로봇 검증**: 향후 연구 방향이며 현재 실제 로봇 엔드투엔드 기능을 보유하고 있다는 의미가 아닙니다.

Roadmap은 유지보수 방향을 나타내며 특정 기능이나 릴리스 일정을 약속하지 않습니다.

## Contributing

재현 가능한 버그 보고, 문서 개선, 테스트, 프로젝트 경계에 부합하는 플랫폼 기여를 환영합니다. 참여하기 전에 [기여 가이드](CONTRIBUTING.md)와 [커뮤니티 행동 강령](CODE_OF_CONDUCT.md)을 확인해 주세요. 보안 문제는 [보안 정책](SECURITY.md)에 따라 비공개로 보고해 주세요.

Pull Request를 만들기 전에 변경 사항과 관련된 검사를 실행해 주세요. 현재 베이스라인 명령은 다음과 같습니다.

```powershell
.\.venv\Scripts\python.exe -m compileall -q .\src .\tests .\run_vision2grasp_app.py .\run_bottle_pipeline.py .\stage0_lift_smoke.py
.\.venv\Scripts\python.exe -m unittest discover -s .\tests -v
.\.venv\Scripts\python.exe -m pip check
node --check .\frontend\apps\gongshu\gongshu.js
node --check .\frontend\apps\gongshu\real-scene.js
node --check .\frontend\apps\gongshu\phone-camera\phone-camera.js
```

### Codex Cloud 개발

Codex Cloud는 소스 코드, 계약, 프론트엔드, 직렬화, 모델을 사용하지 않는
단위 테스트 작업에 적합합니다. [requirements-cloud.txt](requirements-cloud.txt)를
사용하는 Python 3.12 경량 환경과 [docs/CODEX_CLOUD.md](docs/CODEX_CLOUD.md)의
smoke check를 사용하십시오.

Windows 데스크톱 실행기, 휴대전화 카메라 LAN 페어링, 로컬 VLM, 모델 가중치,
CUDA, MuJoCo/robosuite 검증, 실제 로봇, 외부 Mayflower Xiezhi runtime은
계속 로컬에서 검증합니다.

## License

Gongshu가 소유한 소스 코드는 [Apache License 2.0](LICENSE)에 따라 제공됩니다. 서드파티 코드, 모델, 런타임에는 각각의 라이선스가 적용됩니다. AI 생성 프로젝트 시각 자료는 별도의 출처 기록으로 관리되며 Apache-2.0 소스 코드 허가에 자동으로 포함되지 않습니다. 사용하거나 재배포하기 전에 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [ASSET_PROVENANCE.md](ASSET_PROVENANCE.md), [GONGSHU_SCOPE.md](GONGSHU_SCOPE.md)를 확인하십시오.
