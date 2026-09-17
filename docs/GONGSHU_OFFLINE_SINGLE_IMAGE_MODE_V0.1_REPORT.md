# Gongshu Offline Single Image Mode v0.1 Report

## 0. 启动入口

本模式已接入主仓库 Gongshu，不创建独立启动器。唯一官方启动方式为双击：

```text
G:\Vision2Grasp\Start-Vision2Grasp.cmd
```

进入 XUANSHU AI Launcher 后打开 Gongshu，并在 `Vision Source` 中选择 `Local Image`。

## 1. 新增文件

- `src/vision2grasp/sources/local_image.py`
  - 单张本地图片校验、解码、归档、预览与标准 Observation 适配。
  - 每次加载创建独立 `artifacts/offline_run/<run_id>/`，不覆盖旧记录。
- `tests/test_local_image_mode.py`
  - 覆盖单文件选择、图片读取、Observation、现有 Pipeline 调用与结果记录。

本报告为本项目唯一的 Offline Single Image v0.1 实现报告；未新增重复的项目记忆或版本记录文档。

## 2. Local Image Adapter

`LocalImageAdapter` 只承担输入边界职责：

1. 接收一张 JPG、JPEG、PNG、WEBP 或 BMP（最大 15 MB）；
2. 使用 OpenCV 解码为现有 `RGBFrame`；
3. 创建 `gongshu.local-image-observation/v0.1` Observation；
4. 将原图按原始字节归档并记录 SHA-256；
5. 向既有目标感知服务提供 RGB 帧。

Observation 的核心字段为：

```json
{
  "source": "local_image",
  "image_path": "artifacts/offline_run/<run_id>/input.jpg",
  "image_name": "example.jpg",
  "timestamp": "ISO-8601",
  "status": "ready"
}
```

没有创建 Local Image 专属感知、规划或仿真流程。

## 3. 前端变化

Gongshu 的 `Vision Source` 现在提供：

- `Phone Camera`
- `Local Image`

选择 `Local Image` 后，顶部显示 `Local Image Input`，包含单文件选择、文件名、加载按钮和状态。加载成功后，第一视觉区从 `Live RGB` 切换为 `Local RGB`，显示图片、文件名、分辨率、加载状态和既有目标候选叠加。界面继续使用 Gongshu 蓝白科研工作台视觉。

## 4. 单图运行流程

```text
选择一张本地图片
→ 加载并创建标准 Observation
→ 现有 Target Perception
→ 手动锁定目标
→ 现有 Spatial Perception
→ 现有 Grasp Planning
→ 现有 MuJoCo Validation
→ offline_run 结果记录
```

后端保留 `/api/target-perception/*`、`/api/spatial-perception/*`、`/api/grasp-planning/*` 和 `/api/mujoco-validation/*` 的既有接口。Local Image 仅替换第一帧输入来源。

## 5. 结果记录

每次加载生成新的：

```text
artifacts/offline_run/<run_id>/
├── input.<原扩展名>
└── run.json
```

`run.json` 包含 `image_name`、`image_path`、`image_sha256`、`timestamp`、`input_source`、`pipeline_status` 和 `mujoco_result`。MuJoCo 完成后由旁路观察线程更新记录，不修改 MuJoCo 实现。

## 6. 测试结果

- Local Image 专项：5/5 通过；
- Gongshu Workspace：12/12 通过；
- Xiezhi Runtime：7 通过、1 个既有环境条件测试跳过；
- 全量回归：共运行 215 项，214 项通过、1 个既有 Xiezhi 集成环境条件测试跳过；
- JavaScript 语法与 `git diff --check`：通过；
- 实际 UI 端到端验证：图片加载、Observation、12 个目标候选、空间感知、抓取规划、MuJoCo 均完成。

端到端验证使用 `bottle_cc0.jpg`。所选候选的抓取计划被既有规则拒绝，但仍按既有 Simulation Attempt 机制进入 MuJoCo，得到 `FAILED / CONTACT_LOSS`；这证明输入替换和结果记录链条均已贯通，并不表示对 MuJoCo 或抓取算法作了修改。

## 7. 后续 Dataset Mode 扩展位置

未来若明确批准 Dataset Mode，应在 `vision2grasp.sources` 输入边界旁新增数据集枚举/调度组件，并让它逐项调用当前 `LocalImageAdapter` 的单图入口。不要把数据集循环、算法比较或实验编排塞入 perception、grasp planning、MuJoCo 或 Xiezhi，也不要复制现有 Pipeline。

本轮未实现 Dataset Mode、批量实验、算法比较、新模型、新抓取算法或 Xiezhi 决策。
