# Gongshu / 公输

<p align="center">
  <strong>視覚ベース・ロボットマニピュレーション研究プラットフォーム</strong>
</p>

<p align="center">
  <a href="README.md">简体中文</a> ·
  <a href="README_EN.md">English</a> ·
  <a href="README_JA.md">日本語</a> ·
  <a href="README_KO.md">한국어</a>
</p>

<p align="center">
  <a href="https://github.com/PowellWells/gongshu/tree/v0.1.0"><img alt="リリース v0.1.0" src="https://img.shields.io/badge/release-v0.1.0-2563eb?style=flat-square"></a>
  <a href="#current-status"><img alt="研究プラットフォーム・プロトタイプ" src="https://img.shields.io/badge/status-research%20prototype-0f766e?style=flat-square"></a>
  <a href="pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white"></a>
  <a href="#requirements"><img alt="Windows 11" src="https://img.shields.io/badge/platform-Windows%2011-0078D4?style=flat-square&amp;logo=windows11&amp;logoColor=white"></a>
  <a href="tests"><img alt="197 テスト合格" src="https://img.shields.io/badge/tests-197%20passed-brightgreen?style=flat-square"></a>
  <a href="https://github.com/PowellWells/gongshu/stargazers"><img alt="GitHub Stars" src="https://img.shields.io/github/stars/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="https://github.com/PowellWells/gongshu/issues"><img alt="GitHub Issues" src="https://img.shields.io/github/issues/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="#license-and-third-party-notice"><img alt="プロジェクトライセンス未宣言" src="https://img.shields.io/badge/license-not%20declared-lightgrey?style=flat-square"></a>
</p>

Gongshu は、実世界の視覚入力、空間理解、把持計画、シミュレーション検証を接続するデスクトップ研究プラットフォームです。

![Gongshu コンセプトカバー](assets/demo-cover.png)

> プロジェクトのコンセプト画像です。v0.1.0 の実際の機能範囲は Current Status と Features を基準とします。

## Overview

Gongshu は、カメラ入力から MuJoCo 検証まで、視覚駆動ロボットマニピュレーション研究のための統合ワークスペースを提供します。対象認識、深度・点群処理、把持候補、物理シミュレーションを追跡可能なフローとして整理し、中間結果の確認、視覚条件の比較、実験の再現を支援します。

現バージョンはソフトウェア基盤とシミュレーション研究に重点を置いています。同一の信頼できる LAN 上のスマートフォンから実 RGB 入力を取得し、Franka Panda の把持動作を MuJoCo で検証します。シミュレーション結果を実機実験の結果として扱うことはありません。

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

v0.1.0 では Phone Camera の RGB 入力を実装済みです。RGB-D Camera は今後の拡張項目です。現在の単眼深度出力は研究・シミュレーション用であり、校正済み RGB-D センサーの実スケール計測と同等ではありません。

## Features

- **Desktop Research Workspace**：Live RGB、空間知覚、把持計画、MuJoCo 検証をまとめた 4 ビュー構成。
- **Phone Camera RGB Input**：信頼できるプライベート LAN 経由のスマートフォン映像と高解像度撮影入力。
- **Camera Setup / QR Pairing**：ローカル CA、短時間有効なペアリングトークン、QR ガイドによる接続。
- **Real-time Visual Perception**：FastSAM のインスタンス領域、Mask、Bounding Box Overlay、クリックによる対象ロック、軽量追跡。
- **Spatial Perception Interface**：同一 Scene Snapshot に対応する Depth、Point Cloud、対象 XYZ、カメラ内部パラメータ状態。
- **Grasp Planning Interface**：GR-ConvNet の把持マップ、Top-K 候補、実行可能性検査、候補順位付け。
- **MuJoCo Validation Interface**：Franka Panda の動力学シミュレーション、結果状態、セッション内 Recording と Replay。
- **Multi-condition Testing Interface**：Normal、Blur、Low-Light、複合条件の説明可能な処理と Research Mode ストレステスト。

## Demo

### Demo Video

v0.1.0 のデモ動画は、収録完了後に追加予定です。

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

**現バージョン：Research Platform Prototype v0.1.0**

ソフトウェア研究プラットフォーム、実 RGB 入力経路、シミュレーション検証フローは実装済みです。実機ロボットへの展開は、実験設備と条件が整い次第実施します。本リリースには実機ロボットのエンドツーエンド展開は含まれず、単眼深度や MuJoCo の出力を実機計測値として扱いません。

## Future Extension

- RGB-D Camera
- Real Robot Integration
- 6D Grasp Research

## License and Third-Party Notice

本リポジトリは現時点でプロジェクトレベルのオープンソースライセンスを宣言していません。第三者コード、モデル、ランタイムには各ライセンスが適用されます。利用・再配布前に [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を確認してください。
