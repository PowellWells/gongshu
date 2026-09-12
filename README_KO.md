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
  <a href="#roadmap"><img alt="오픈 소스 베이스라인" src="https://img.shields.io/badge/status-open--source%20baseline-0f766e?style=flat-square"></a>
  <a href="pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white"></a>
  <a href="#requirements"><img alt="Windows 11" src="https://img.shields.io/badge/platform-Windows%2011-0078D4?style=flat-square&amp;logo=windows11&amp;logoColor=white"></a>
  <a href="tests"><img alt="테스트 197개 통과" src="https://img.shields.io/badge/tests-197%20passed-brightgreen?style=flat-square"></a>
  <a href="https://github.com/PowellWells/gongshu/stargazers"><img alt="GitHub Stars" src="https://img.shields.io/github/stars/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="https://github.com/PowellWells/gongshu/issues"><img alt="GitHub Issues" src="https://img.shields.io/github/issues/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="LICENSE"><img alt="Apache-2.0 라이선스" src="https://img.shields.io/badge/license-Apache--2.0-2563eb?style=flat-square"></a>
</p>

Gongshu는 시각 입력, 공간 이해, 파지 계획, 시뮬레이션 검증에 초점을 맞춘 오픈 소스 모듈형 로봇 비전 및 파지 실험 플랫폼입니다.

![Gongshu 콘셉트 커버](assets/demo-cover.png)

> 프로젝트 콘셉트 이미지입니다. v0.1.0의 실제 기능 범위는 이 문서의 설명을 기준으로 합니다.

## Overview

Gongshu는 연구자가 하나의 워크스페이스에서 로봇 비전 및 파지 실험을 구성하고 입력부터 시뮬레이션 검증까지의 중간 결과를 확인할 수 있도록 지원합니다. 현재 오픈 소스 베이스라인은 다음 네 가지 기능 영역에 초점을 맞춥니다.

- **RGB / RGB-D 시각 입력**: 휴대전화 카메라 RGB 입력과 시뮬레이션 또는 호환 데이터 소스를 위한 RGB-D 데이터 인터페이스.
- **공간 이해**: 깊이, 포인트 클라우드, 대상 XYZ 좌표, 카메라 내부 파라미터 등의 공간 정보.
- **파지 계획**: 결과 비교를 위한 파지 후보 생성, 실행 가능성 검사, 순위화.
- **시뮬레이션 검증**: MuJoCo / robosuite와 Franka Panda를 사용한 실험적 파지 검증.

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

Gongshu 직접 실행:

```text
Start-Vision2Grasp.cmd
```

또는 PowerShell에서 실행:

```powershell
.\.venv\Scripts\python.exe .\run_vision2grasp_app.py
```

기본 워크스페이스 URL은 `http://127.0.0.1:8765/apps/gongshu/index.html`입니다. 휴대전화를 처음 연결할 때는 Gongshu에서 **Camera Setup**을 열고 로컬 CA와 Pairing QR 안내를 따르십시오.

기존 XUANSHU LAB 포털에서도 실행할 수 있습니다.

```text
Start-XUANSHU-LAB.cmd
```

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

## License

Gongshu가 소유한 소스 코드는 [Apache License 2.0](LICENSE)에 따라 제공됩니다. 서드파티 코드, 모델, 자산, 런타임에는 각각의 라이선스가 적용되며 저장소의 Apache-2.0 선언 범위에 포함되지 않습니다. 사용하거나 재배포하기 전에 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)와 [GONGSHU_SCOPE.md](GONGSHU_SCOPE.md)를 확인하십시오.
