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
  <a href="https://github.com/PowellWells/gongshu/tree/v0.1.0"><img alt="リリース v0.1.0" src="https://img.shields.io/badge/release-v0.1.0-2563eb?style=flat-square"></a>
  <a href="#current-status"><img alt="オープンソース・ベースライン" src="https://img.shields.io/badge/status-open--source%20baseline-0f766e?style=flat-square"></a>
  <a href="pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white"></a>
  <a href="#requirements"><img alt="Windows 11" src="https://img.shields.io/badge/platform-Windows%2011-0078D4?style=flat-square&amp;logo=windows11&amp;logoColor=white"></a>
  <a href="tests"><img alt="197 テスト合格" src="https://img.shields.io/badge/tests-197%20passed-brightgreen?style=flat-square"></a>
  <a href="https://github.com/PowellWells/gongshu/stargazers"><img alt="GitHub Stars" src="https://img.shields.io/github/stars/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="https://github.com/PowellWells/gongshu/issues"><img alt="GitHub Issues" src="https://img.shields.io/github/issues/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="LICENSE"><img alt="Apache-2.0 ライセンス" src="https://img.shields.io/badge/license-Apache--2.0-2563eb?style=flat-square"></a>
</p>

Gongshu は、視覚入力、空間理解、把持計画、シミュレーション検証を接続する、ロボットビジョンと把持研究向けのモジュール型実験プラットフォームです。

![Gongshu コンセプトカバー](assets/demo-cover.png)

> プロジェクトのコンセプト画像です。v0.1.0 の実際の機能範囲は Current Status と Features を基準とします。

## Overview

Gongshu は、視覚駆動ロボット操作実験のための追跡可能なワークフローを提供し、RGB 入力、互換性のある RGB-D データインターフェース、対象認識、深度・点群処理、空間理解、把持候補生成、MuJoCo / robosuite 検証を扱います。ワークスペースでは、中間結果の確認、処理条件の比較、再現可能な実行成果物の保存が可能です。

v0.1.0 の実画像入力は同一の信頼できる LAN 上のスマートフォンカメラから取得し、RGB-D データはシミュレーションまたは互換データソースのインターフェースから取得します。Franka Panda の把持は MuJoCo / robosuite で検証します。本リリースには検証済みの実機ロボットによるエンドツーエンド把持は含まれず、単眼深度やシミュレーション結果を実機計測値として扱いません。

## Pipeline

![Gongshu 研究パイプライン](assets/pipeline.png)

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

v0.1.0 では Phone Camera の RGB 入力を実装し、シミュレーションおよび互換データソース向けの RGB-D 処理インターフェースを提供しています。実 RGB-D Camera との統合は今後の拡張項目です。現在の単眼深度出力は研究・シミュレーション用であり、校正済み RGB-D センサーの実スケール計測と同等ではありません。

## Features

- **Desktop Research Workspace**：Live RGB、空間知覚、把持計画、MuJoCo 検証をまとめた 4 ビュー構成。
- **Phone Camera RGB Input**：信頼できるプライベート LAN 経由のスマートフォン映像と高解像度撮影入力。
- **Camera Setup / QR Pairing**：ローカル CA、短時間有効なペアリングトークン、QR ガイドによる接続。
- **Real-time Visual Perception**：FastSAM のインスタンス領域、Mask、Bounding Box Overlay、クリックによる対象ロック、軽量追跡。
- **Spatial Perception Interface**：同一 Scene Snapshot に対応する Depth、Point Cloud、対象 XYZ、カメラ内部パラメータ状態。
- **Grasp Planning Interface**：GR-ConvNet の把持マップ、Top-K 候補、実行可能性検査、候補順位付け。
- **MuJoCo / robosuite Validation Interface**：Franka Panda の動力学シミュレーション、結果状態、セッション内 Recording と Replay。
- **Multi-condition Testing Interface**：Normal、Blur、Low-Light、複合条件の説明可能な処理と Research Mode ストレステスト。

## Demo

### Gongshu v0.1.0 概要

<video src="GITHUB_USER_ATTACHMENT_VIDEO_URL" controls width="100%">
</video>

Gongshu v0.1.0 のデモは、視覚入力、対象認識、空間理解、把持計画、MuJoCo ベースの検証に至る実験ワークフローを示します。

動画ファイルは GitHub Release Assets にも保存されており、ダウンロードして確認できます：[Gongshu v0.1.0 デモ動画をダウンロード](https://github.com/PowellWells/gongshu/releases/download/v0.1.0/gongshu-v0.1.0-demo.mp4)。

### Project Screenshots

![Gongshu デスクトップ研究ワークスペース](assets/overview.png)

上図は Gongshu の実際の起動時ワークスペースです。カメラ接続後、Live RGB に映像、対象領域、ロック状態が表示され、他のビューは同一の対象スナップショットから更新されます。

## Quick Start

### Requirements

- Windows 11（現在の検証環境）
- Python 3.12.x（`>=3.12,<3.13`）
- Phone Camera 利用時は、スマートフォンと PC が同一の信頼できるプライベート LAN に接続されていること
- CUDA は任意。CPU fallback を利用可能

### Installation

```powershell
git clone https://github.com/PowellWells/gongshu.git
cd gongshu
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

依存関係の正式な定義は `pyproject.toml` です。一般的な環境構築向けに `requirements.txt` も用意しています。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

モデル重みは Git リポジトリには含まれません。FastSAM、Depth Anything V2、GR-ConvNet は既存の解決順序に従い、ローカル Release Bundle、`artifacts/models/`、ユーザーキャッシュ、公式配布元を参照します。出典とライセンス境界は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を確認してください。

### Launch

Gongshu を直接起動：

```text
Start-Vision2Grasp.cmd
```

XUANSHU LAB ポータルから起動：

```text
Start-XUANSHU-LAB.cmd
```

PowerShell から起動：

```powershell
.\.venv\Scripts\python.exe .\run_vision2grasp_app.py
```

既定のワークスペース URL は `http://127.0.0.1:8765/apps/gongshu/index.html` です。スマートフォンを初めて接続する場合は、Gongshu の **Camera Setup** を開き、ローカル CA と Pairing QR の案内に従ってください。

## Project Structure

```text
gongshu/
├── assets/                     GitHub README 用素材
├── configs/                    既定の実験設定
├── contracts/                  実行結果データ契約
├── frontend/                   Gongshu / XUANSHU LAB フロントエンド
├── scripts/                    起動・ベンチマーク・リリーススクリプト
├── src/vision2grasp/           知覚・空間・把持・制御・シミュレーション
├── src/xuanshu_lab/            デスクトップ研究基盤ランタイム
├── tests/                      単体・統合テスト
├── requirements.txt            環境依存関係
├── VERSION.md                  リリースバージョン情報
└── run_vision2grasp_app.py     Gongshu ローカルサービスの入口
```

実行時モデル、証明書、カメラセッション、ユーザーデータ、実験出力、ログは Git 管理外のローカルディレクトリに保存され、ソースリリースには含まれません。

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

**現バージョン：Open-Source Baseline v0.1.0**

v0.1.0 では Apache-2.0 プロジェクトライセンス、オープンソース範囲、ガバナンス凍結ベースラインを確立し、既存の視覚入力、空間理解、把持計画、シミュレーション検証機能を維持しています。実機ロボットへの展開は今後の課題であり、本リリースには検証済みの実機エンドツーエンド機能は含まれません。

## Future Extension

- RGB-D Camera
- Real Robot Integration
- 6D Grasp Research

## License and Third-Party Notice

Gongshu が保有するソースコードは [Apache License 2.0](LICENSE) の下で提供されます。第三者コード、モデル、素材、ランタイムにはそれぞれのライセンスが適用され、リポジトリの Apache-2.0 宣言の対象にはなりません。利用・再配布前に [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) と [GONGSHU_SCOPE.md](GONGSHU_SCOPE.md) を確認してください。
