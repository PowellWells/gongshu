# Gongshu Intelligence Layer Runtime v1.0 Report

## 1. 当前架构

本轮保持冻结关系不变：

```text
XUANSHU AI
└── Gongshu
    ├── Perception
    ├── Grasp Planning
    ├── Intelligence Layer
    │   ├── Algorithm Interface / Registry（Gongshu 所有）
    │   ├── Gongshu Baseline Provider
    │   └── Xiezhi Rule-Based Provider（可选）
    ├── MuJoCo Validation / Execution
    └── Experiment Lab
        └── Trial Recorder
```

- Gongshu 继续拥有 Observation、候选抓取、机器人执行、MuJoCo 和反馈。
- Xiezhi 只接收标准状态表示并产生 Decision Output；不接触 Robot、Scene、Camera 或 Simulation Runtime。
- Experiment Lab 只记录输入、算法、决策和结果；不拥有算法实现或运行资源。
- Xiezhi 不可用时，Gongshu Baseline 通过同一 Algorithm Interface 接管决策，Gongshu 仍可独立运行。

## 2. Xiezhi 接入流程

```text
GraspPlanningOutcome
        ↓
Gongshu AlgorithmObservation
        ↓
Algorithm Interface
   ├── Xiezhi / rule_based
   └── Gongshu / baseline_topk（关闭或故障回退）
        ↓
AlgorithmDecision
  - selected_action
  - selected_candidate_id
  - confidence
  - risk_estimation
  - status / reason
        ↓
Gongshu Runtime 校验并执行
```

Xiezhi 的有效 `REOBSERVE`、`CHANGE_VIEWPOINT`、`ABORT` 决策不会被 Baseline 覆盖。只有 Provider 加载或运行异常时才触发 Baseline 回退。

## 3. 实际运行流程

本地图像流程为：

```text
Local Image
→ Target Perception
→ 自动选择首个目标
→ Spatial Perception
→ Gongshu Top-K Grasp Planning
→ Xiezhi / Baseline Decision
→ 决策授权校验
→ MuJoCo Validation
→ Experiment Trial Record
```

MuJoCo 启动前会再次确保当前规划已有对应决策。对于可执行规划，仅 `EXECUTE_GRASP` 且候选与当前可执行 GraspPlan 一致时才能进入执行；因此 Xiezhi 不会直接控制机器人。

## 4. 前端变化

- 05 整块明确为“獬豸 Xiezhi”，定位为 Gongshu 页面内的智能决策子模块，不是独立软件入口。
- 头部使用正式獬豸 Logo，并保留“GONGSHU · INTERNAL SUBMODULE”所属关系。
- “Algorithm Provider / 算法提供者”在用户界面统一改名为“Decision Engine / 决策引擎”。
- 决策运行、决策引擎、决策证据、决策记录四个卡片均可展开查看真实运行数据。
- 决策引擎可在 Xiezhi `rule_based` 与 Gongshu `baseline_topk` 之间切换；切换只替换决策环节。
- Experiment Lab 不再出现在 05 内部；实验生命周期仍属于 Gongshu 的独立实验层。

## 5. 实验记录

本地图像每次运行生成 `experiment_record.json`，包含：

- 输入图片引用、尺寸与 SHA-256；
- 实际 Provider 与算法；
- 完整 Decision Output；
- MuJoCo 最终状态、原因与结果。

记录器只引用 Gongshu 已创建的输入与运行结果，不创建场景、机器人或算法。

## 6. 测试结果

- Xiezhi `rule_based` Provider 真实通过标准接口选择抓取候选：通过。
- Xiezhi 不可用时自动回退 `baseline_topk`：通过。
- Gongshu Execution 在 MuJoCo 前消费并校验 Decision：通过。
- Trial Record 同时保存输入、算法、决策与 MuJoCo 结果：通过。
- 前端单工作区、自动本地图像流程与 Intelligence Layer 边界检查：通过。
- 相关回归测试：40 passed，1 skipped。
- 主工作树全量测试：220 passed，1 skipped，8 subtests passed。
- 真实进程级 Local Image 冒烟：`CANDIDATES → READY → GRASP_READY → Xiezhi/rule_based → EXECUTE_GRASP → MuJoCo → Experiment Record COMPLETED`。该样例的 MuJoCo 结果为 `FAILED / CONTACT_LOSS`，证明结果失败也能被完整记录，而不是将进入仿真误报为抓取成功。

## 7. 已知限制

- v1.0 的 Gongshu 执行契约只执行规划器确认的 Best Executable Grasp；未来若允许算法从全部 Top-K 任意选择，需要扩展可执行 GraspPlan 契约。
- confidence 与 risk_estimation 均为未校准启发式证据，不代表真实成功概率。Xiezhi Rule-Based Provider 使用候选排名分数与规划可靠性证据的等权组合，以对齐既有策略阈值；两项原始证据和组合类型均写入 diagnostics。
- 自动本地图像流程默认选择感知列表中的首个目标；多目标任务的语义目标选择尚未进入算法层。
- Experiment Lab v1.0 的持久化 Trial Record 仅覆盖 Local Image 流程；Phone Camera 仍保留现有会话内结果。
- 当前可插拔选择覆盖 Xiezhi `rule_based` 与 Gongshu `baseline_topk` 两个决策引擎；更多算法版本与批量实验属于后续 Experiment Lab 阶段。
- 当前验证仍是规范化 MuJoCo 仿真，不声明真实相机到机器人坐标标定，也不连接真实机器人控制。
