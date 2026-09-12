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
  <a href="#roadmap"><img alt="オープンソース・ベースライン" src="https://img.shields.io/badge/status-open--source%20baseline-0f766e?style=flat-square"></a>
  <a href="pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white"></a>
  <a href="#requirements"><img alt="Windows 11" src="https://img.shields.io/badge/platform-Windows%2011-0078D4?style=flat-square&amp;logo=windows11&amp;logoColor=white"></a>
  <a href="tests"><img alt="197 テスト合格" src="https://img.shields.io/badge/tests-197%20passed-brightgreen?style=flat-square"></a>
  <a href="https://github.com/PowellWells/gongshu/stargazers"><img alt="GitHub Stars" src="https://img.shields.io/github/stars/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="https://github.com/PowellWells/gongshu/issues"><img alt="GitHub Issues" src="https://img.shields.io/github/issues/PowellWells/gongshu?style=flat-square&amp;logo=github"></a>
  <a href="LICENSE"><img alt="Apache-2.0 ライセンス" src="https://img.shields.io/badge/license-Apache--2.0-2563eb?style=flat-square"></a>
</p>

Gongshu は、視覚入力、空間理解、把持計画、シミュレーション検証に取り組む、オープンソースのモジュール型ロボットビジョン・把持実験プラットフォームです。

![Gongshu コンセプトカバー](assets/demo-cover.png)

> プロジェクトのコンセプト画像です。v0.1.0 の実際の機能範囲は本書の記載を基準とします。

## Overview

Gongshu は、ロボットビジョンと把持の実験を一つのワークスペースで整理し、入力からシミュレーション検証までの中間結果を確認できるようにします。現在のオープンソース・ベースラインは、次の四つの機能領域に重点を置いています。

- **RGB / RGB-D 視覚入力**：スマートフォンカメラによる RGB 入力と、シミュレーションまたは互換データソース向けの RGB-D データインターフェース。
- **空間理解**：深度、点群、対象 XYZ 座標、カメラ内部パラメータなどの空間情報。
- **把持計画**：把持候補の生成、実行可能性検査、順位付けによる結果比較。
- **シミュレーション検証**：MuJoCo / robosuite と Franka Panda を使用した実験的な把持検証。

v0.1.0 は Gongshu のオープンソース・ベースラインです。実画像入力は現在、同一の信頼できる LAN 上のスマートフォンカメラから取得します。実 RGB-D カメラとの統合は今後の方向性です。本リリースには検証済みの実機ロボットによるエンドツーエンド把持は含まれず、単眼深度やシミュレーション結果を実機計測値として扱いません。

## Demo

### Gongshu v0.1.0 概要

<video src="https://github.com/user-attachments/assets/12a7abca-c202-45ff-b3dd-485dfb8e599a" controls width="100%">
</video>

デモでは、Gongshu v0.1.0 の視覚入力、対象認識、空間理解、把持計画、MuJoCo ベースのシミュレーション検証を紹介します。

動画は GitHub Release Assets からも取得できます：[Gongshu v0.1.0 デモ動画をダウンロード](https://github.com/PowellWells/gongshu/releases/download/v0.1.0/gongshu-v0.1.0-demo.mp4)。

## Quick Start — 5 分で Gongshu を起動

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

依存関係の正式な定義は `pyproject.toml` です。一般的な環境構築には `requirements.txt` も利用できます。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

モデル重みは Git ソースリポジトリには含まれません。FastSAM、Depth Anything V2、GR-ConvNet は既存の解決順序に従い、ローカル Release Bundle、`artifacts/models/`、ユーザーキャッシュ、公式配布元を参照します。出典とライセンス境界は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を確認してください。

### Launch

Gongshu を直接起動：

```text
Start-Vision2Grasp.cmd
```

PowerShell から起動：

```powershell
.\.venv\Scripts\python.exe .\run_vision2grasp_app.py
```

既定のワークスペース URL は `http://127.0.0.1:8765/apps/gongshu/index.html` です。スマートフォンを初めて接続する場合は、Gongshu の **Camera Setup** を開き、ローカル CA と Pairing QR の案内に従ってください。

既存の XUANSHU LAB ポータルから起動することもできます。

```text
Start-XUANSHU-LAB.cmd
```

<details>
<summary>リポジトリ構成</summary>

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

</details>

## Features

### Visual Perception

RGB / RGB-D データを受け取り、対象領域、Mask、Bounding Box Overlay、対象ロック、軽量追跡を提供します。

### Spatial Understanding

同一の Scene Snapshot 上で、深度、点群、対象 XYZ 座標、カメラ内部パラメータ状態を表示します。

### Grasp Planning

GR-ConvNet の把持マップ、Top-K 把持候補、実行可能性検査、候補順位付けを提供します。

### Simulation Validation

MuJoCo / robosuite と Franka Panda による連続動力学シミュレーションを実行し、セッション内 Recording と Replay に対応します。

### Experiment Workspace

四つのビューに視覚・空間・把持・シミュレーション結果を集約し、Normal、Blur、Low-Light などの実験条件に対応します。

### Modular Extension

モジュール型インターフェースにより、コアプラットフォームの境界を保ちながら、互換データソース、研究モジュール、把持アルゴリズムを将来拡張できます。

## System Preview / Screenshots

![Gongshu デスクトップ研究ワークスペース](assets/overview.png)

上図は Gongshu のデスクトップ研究ワークスペースの起動状態です。カメラ接続後、Live RGB に映像、対象領域、ロック状態が表示され、他のビューは同一の対象スナップショットから更新されます。

## Roadmap

- [x] **v0.1 Open-source baseline**：Apache-2.0 ライセンス、オープンソース範囲、ガバナンス・ベースライン、現在の実験ワークスペースを確立。
- [ ] **RGB-D カメラ統合**：今後の拡張方向。具体的な機器と時期は未定です。
- [ ] **把持アルゴリズムの追加対応**：再現性、ライセンス互換性、保守能力に基づいて段階的に評価します。
- [ ] **実機ロボット検証**：今後の研究方向であり、現在の実機エンドツーエンド能力を示すものではありません。

Roadmap は保守の方向性を示すものであり、特定機能やリリース時期を保証するものではありません。

## Contributing

再現可能なバグ報告、ドキュメント改善、テスト、プロジェクト境界に沿ったプラットフォームへの貢献を歓迎します。参加前に [コントリビューションガイド](CONTRIBUTING.md) と [コミュニティ行動規範](CODE_OF_CONDUCT.md) を確認してください。セキュリティ上の問題は [セキュリティポリシー](SECURITY.md) に従って非公開で報告してください。

Pull Request を作成する前に、変更に関連するチェックを実行してください。現在のベースラインコマンドは次のとおりです。

```powershell
.\.venv\Scripts\python.exe -m compileall -q .\src .\tests .\run_vision2grasp_app.py .\run_bottle_pipeline.py .\stage0_lift_smoke.py
.\.venv\Scripts\python.exe -m unittest discover -s .\tests -v
.\.venv\Scripts\python.exe -m pip check
node --check .\frontend\apps\gongshu\gongshu.js
node --check .\frontend\apps\gongshu\real-scene.js
node --check .\frontend\apps\gongshu\phone-camera\phone-camera.js
```

## License

Gongshu が保有するソースコードは [Apache License 2.0](LICENSE) の下で提供されます。第三者コード、モデル、素材、ランタイムにはそれぞれのライセンスが適用され、リポジトリの Apache-2.0 宣言の対象にはなりません。利用・再配布前に [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) と [GONGSHU_SCOPE.md](GONGSHU_SCOPE.md) を確認してください。
