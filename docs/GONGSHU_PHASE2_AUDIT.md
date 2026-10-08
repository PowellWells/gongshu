# Gongshu 第二阶段审查与路线图

本审查基于 `codex/bottle-end-to-end-loop` 的实际代码、接口和前端调用，不以 README 的能力描述作为实现证据。审查范围包括 `run_vision2grasp_app.py`、`src/vision2grasp`、`frontend/apps/gongshu` 以及现有契约测试。

## 真实调用链

正式工作台的主链路已经存在：

```text
工作台/云冈娘
  → /api/target-perception/analyze
  → FastSAM 实例候选
  → /api/vlm/ground（可选的自然语言目标绑定）
  → Frozen Scene Snapshot
  → /api/spatial-perception/analyze
  → /api/grasp-planning/plan（真实 Top-K 规划）
  → /api/intelligence/decide（獬豸或 Gongshu fallback）
  → /api/mujoco-validation/start
  → MuJoCo 状态机与 ValidationResult
  → Xiezhi lifecycle + chat feedback + Local Image 实验记录
```

边界约束在代码中有效：VLM 返回目标点、框和证据，`ground_target()` 重新绑定 FastSAM mask；执行入口要求 `AlgorithmDecision.authorizes_execution`，拒绝候选只进入 simulation-only diagnostic；终态聊天消息由 MuJoCo 结果、状态历史和 telemetry 生成。

## 五项最影响实际使用的问题

排序综合了用户价值、失败风险和云端实施成本。成本是相对估计，低/中/高分别代表一到三周以内的工程量级，而不是承诺工期。

| 排名 | 实际问题与代码证据 | 价值 | 风险 | 成本 |
| --- | --- | --- | --- | --- |
| 1 | 聊天只消费终态 `grasp_feedback` / `system_error`，此前 `ChatEventStore` 是进程内存、整表轮询、无顺序游标；目标锁定、獬豸理由、验证器阶段不会进入云冈娘时间线。刷新或后端重启也会丢失这段上下文。 | 很高：直接影响“自然交互”和可解释闭环 | 中 | 低 |
| 2 | 实验记录只在 Local Image 流程写入 `ExperimentTrialRecorder`；Phone Camera 仍主要是会话状态。决策和终态虽可写入本地图片记录，但跨来源没有统一的任务事件、输入快照和回放索引。 | 很高：影响复现实验和审计 | 中 | 中高 |
| 3 | 獬豸决策已经阻止未授权执行，但正式聊天界面没有显示 `reason`、`uncertainty`、fallback 和授权边界；用户通常要打开专家诊断才能理解为什么执行、重新观察或中止。 | 高：影响信任和错误恢复 | 中 | 低中 |
| 4 | 自然语言 grounding、扫描、空间分析和抓取启动仍由多个按钮/脚本分段编排。宠物模式在视觉输入不可用时的“抓左边/抓右边”快捷命令调用 `setMockTarget()`，只做 UI 目标动画，容易让用户把演示状态误认为真实目标锁定。 | 高：影响操作清晰度和约束合规 | 中高 | 中 |
| 5 | 能力边界对用户仍不连续：当前正式执行只接受规划器的可执行候选，UR5e 选择项明确禁用，外部 `xiezhi.runtime` 不可用时降级到 Gongshu baseline；这些状态分别散落在工作台、诊断和文档中。 | 中高：影响预期管理 | 中 | 中 |

## 第二阶段路线图

1. **可追踪任务时间线（本 PR）**：用有序、可游标读取的聊天事件流传递目标扫描、VLM mask 绑定、空间感知、抓取规划、獬豸决策、验证启动和验证器状态；终态成功/失败继续只由真实 ValidationResult 产生。这样云冈娘可以连续呈现发生了什么，且不会把 UI 动画当成执行证据。
2. **持久化实验事件与统一回放**：把同一事件契约写入 `ExperimentTrialRecorder`，为 Phone Camera 建立明确的实验 run 边界，保存输入帧、冻结 snapshot、决策证据、执行状态历史和产物哈希。聊天流可以在重启后从 run 记录恢复，但仍要标注历史事件。
3. **决策证据卡片**：在正式工作台直接呈现獬豸/降级 provider、候选 ID、理由、不确定性、启发式置信度标签和“是否授权执行”；把 `REOBSERVE`、`ABORT`、规划拒绝和执行失败映射为可执行的下一步。
4. **自然语言任务状态机**：将指令解析、目标确认、重新观察、规划和执行请求合并成一个带确认门的任务对象；删除或明确隔离无视觉输入时的 mock 目标快捷路径，保证演示状态不能触发真实流程。
5. **候选与回放扩展**：在本地模型和仿真验收通过后，再支持獬豸选择任意已校验 Top-K 候选、行为对比和真实机器人适配；继续保留 VLM 只能提供目标 grounding 的边界。

## 本次实施与未覆盖范围

本次实现了第 1 项的云端可验证部分：`ChatEventStore` 为每个事件分配单调 `sequence` 和 `stream_id`，`GET /api/chat/events?after_sequence=N` 支持增量读取；后端在实际阶段完成/启动时发布 `workflow_update`，工作台用时间线卡片呈现这些事件。事件仍是进程内存，持久化和 Phone Camera run 归属留在第 2 项，避免用云端伪造硬件证据。

云端检查只能证明契约、顺序和前端接线。FastSAM、Depth Anything、GR-ConvNet、llama.cpp/VLM、MuJoCo 正式仿真、GPU、手机摄像头、Panda/UR5e 和外部 `xiezhi.runtime` 需要在本地 Windows/模型环境验收。
