# XUANSHU AI Architecture Freeze v3.0

## Gongshu Runtime × Intelligence × Experiment Lab

- 状态：已确认，自 2026-09-16 起生效
- 适用范围：XUANSHU AI、Gongshu、Xiezhi、Experiment Lab 的产品层级、资源所有权、运行关系、实验职责和前端表达
- 文档优先级：本文取代 `XUANSHU_ARCHITECTURE_FREEZE_V2.0.md`，成为当前权威架构记录
- 实施边界：本次冻结先统一职责和迁移方向，不要求立即移动、删除或重写现有实现

## 1. 唯一产品层级

```text
XUANSHU AI
└── Gongshu · Robot Intelligence Platform
    ├── Core Runtime
    ├── Simulation System
    │   ├── MuJoCo
    │   ├── Robot
    │   ├── Physics
    │   └── Scene
    ├── Perception System
    ├── Execution System
    ├── Intelligence Layer
    │   ├── Baseline Algorithms
    │   └── Xiezhi
    └── Experiment Lab
        ├── Experiment Definition
        ├── Experiment Runner
        ├── Trial Recorder
        ├── Evaluation
        └── Comparison
```

Gongshu 是唯一机器人平台和运行主体。Xiezhi 与 Experiment Lab 都是 Gongshu 内部能力，不是独立平台、独立 App 或与 Gongshu 平级的 Workspace。

## 2. 三个核心角色

### 2.1 Gongshu Runtime

Gongshu Runtime 是所有机器人实验的基础层，拥有并负责：

- 机器人模型；
- MuJoCo 仿真环境和 Physics；
- Scene 与物体资源；
- Camera、Sensor 与感知输入；
- 状态表示所需的平台事实；
- 运动控制、动作校验和执行过程；
- Runtime feedback；
- 原始仿真轨迹、接触、状态和回放资产。

任何机器人实验都必须使用 Gongshu Runtime。其他层只能引用 Gongshu 资源或消费 Gongshu 输出，不得复制出第二套机器人运行环境。

### 2.2 Xiezhi

Xiezhi 是 Gongshu Intelligence Layer 内部的智能算法提供者。它负责：

- 抓取策略；
- 候选方案生成、补充或排序；
- 风险评估；
- 不确定性建模；
- 决策选择；
- 根据反馈调整后续行为；
- 输出与决策直接相关的诊断和解释证据。

Xiezhi 不负责：

- 创建或管理 Robot、MuJoCo、Scene、Camera 或 Sensor；
- 持有 Simulation Runtime；
- 执行机器人动作；
- 管理 Experiment 或 Trial 生命周期；
- 保存通用实验记录；
- 生成跨算法比较和最终实验报告。

Xiezhi 可以维护算法自身的版本、参数和模型资产，但这些信息作为算法身份由 Experiment Lab 引用，不构成独立实验系统。

### 2.3 Experiment Lab

Experiment Lab 是 Gongshu 内部的科学实验组织与分析层，负责：

- 定义 Experiment；
- 引用 Gongshu 提供的 Scene、Robot 和 Runtime 配置；
- 从 Intelligence Layer 选择算法；
- 启动和管理 Trial；
- 记录实验条件、算法输出、执行反馈和结果引用；
- 评价单次与多次 Trial；
- 公平比较 Baseline 与 Xiezhi；
- 生成实验报告。

Experiment Lab 不拥有：

- Scene、Robot Model、Camera 或物体资源；
- Simulation Runtime 或 Physics；
- 具体算法实现；
- 机器人执行器。

选择资源不等于拥有资源，选择算法不等于实现算法，组织 Trial 不等于执行机器人动作。

## 3. Algorithm Interface 所有权

统一 Algorithm Interface 属于 Gongshu Intelligence Layer，不属于 Xiezhi，也不属于 Experiment Lab。

```text
Experiment Lab
    ↓ select algorithm_id
Gongshu Algorithm Registry
    ├── Baseline Provider
    └── Xiezhi Provider
```

必须遵守：

1. Baseline 不依赖 Xiezhi 才能注册或运行。
2. Xiezhi 只注册自身算法实现，不控制平台 Registry。
3. Experiment Lab 通过同一接口选择 Baseline 或 Xiezhi。
4. Algorithm 只接收不可执行的 State Representation，不接收 MuJoCo、Robot、Camera、Scene 或控制器对象。
5. Algorithm 输出是决策建议，不能直接执行动作。

统一输出概念冻结为：

```text
AlgorithmDecision
├── grasp_candidates
├── confidence
├── risk_estimation
└── selected_action
```

允许以加法方式附加算法版本和诊断信息，但不得改变上述核心语义。Gongshu 只接收经过平台验证的 `selected_action`，并负责 simulation、execution 和 feedback。

## 4. 数据流冻结

```text
Experiment Definition
    ↓ scene_ref / robot_ref / algorithm_id
Gongshu Scene + Simulation
    ↓
Perception
    ↓
State Representation
    ↓
Gongshu Intelligence Layer
    ├── Baseline
    └── Xiezhi
    ↓
AlgorithmDecision
    ↓
Gongshu Action Validation
    ↓
Gongshu Simulation / Execution
    ↓
Runtime Feedback
    ↓
Experiment Lab Trial Recorder
    ↓
Evaluation / Comparison / Report
```

禁止的反向关系包括：

- Xiezhi 创建或驱动 MuJoCo；
- Xiezhi 管理 Scene 或 Robot 生命周期；
- Experiment Lab 内嵌 Scene、Robot 或仿真实现；
- Algorithm 绕过 Gongshu Action Validation；
- Gongshu Baseline 依赖 Xiezhi Runtime；
- Xiezhi Runtime 成为 Gongshu 启动前置条件。

## 5. Recording 与实验记录边界

必须区分两类记录：

### Gongshu Runtime Recording

由 Gongshu 生成和拥有，包括物理状态、轨迹、接触、相机帧、执行状态、模型兼容信息和回放资产。它是 Runtime 事实，不是 Experiment Lab 对仿真资源的所有权。

### Experiment Trial Record

由 Experiment Lab 组织，包括实验定义、Trial ID、资源引用、算法身份、AlgorithmDecision、Runtime feedback、指标、结论以及 Gongshu Recording 的引用和校验信息。

Experiment Lab 可以要求保存过程数据并建立可追溯关联，但不得复制或重新实现 Gongshu 的物理记录逻辑。

## 6. 现有资产处理

本次冻结不删除已有功能：

- Gongshu 仿真、感知、执行、Recording 和 Playback 保持不变；
- Gongshu Baseline 抓取链保持可运行；
- Xiezhi v0.1、v0.2 Runtime 和 Algorithm Registry 作为兼容资产保留；
- Mayflower `EpisodeRunner`、`ExperimentRecorder`、benchmark 和历史结果继续作为 Mayflower 研究工具保留；
- 现有 Xiezhi lifecycle inbox 暂时作为状态兼容通道保留；
- 历史导入路径和记录格式不得在一次迁移中破坏。

保留现有代码不代表延续旧职责。Gongshu 集成路径不得把 Mayflower/Xiezhi 的独立 experiment runner 当作 Gongshu Experiment Lab，也不得让 lifecycle inbox 成为新的 Trial Recorder。

## 7. 最小迁移顺序

1. 先统一冻结文档、README 和界面职责语言。
2. 在 Gongshu Intelligence Layer 建立平台所有的 Algorithm Interface 和 Registry 边界。
3. 让现有 Baseline 以 Provider 身份接入，不改变其当前行为。
4. 让 Xiezhi 只通过同一接口返回 AlgorithmDecision。
5. 将 Experiment、Trial、Evaluation 和 Comparison 的组织职责收敛到 Experiment Lab。
6. 将 Runtime event 送入 Experiment Lab Trial Recorder；Xiezhi 只接收决策所需状态和反馈。
7. 在行为等价和回归通过后，再决定是否移动目录；不得为了视觉整齐提前大规模重构。

## 8. 前端关系

用户始终只进入 Gongshu。

Gongshu 页面中：

- Experiment Lab 展示实验定义、Trial、记录、评价、比较和报告；
- Xiezhi 展示算法身份、候选、风险、不确定性、选择和决策解释；
- Xiezhi 可以作为 Experiment Lab 的算法选项出现，但不能拥有 Experiment Lab；
- 不创建独立 Xiezhi App、Experiment Lab App、启动器或平级导航入口。

## 9. 验收不变量

后续每个迁移阶段都必须同时满足：

1. Gongshu 可以在 Xiezhi 缺失或关闭时独立启动和运行。
2. 不启用 Xiezhi 时，Baseline 抓取和 MuJoCo 验证仍可运行。
3. 启用 Xiezhi 时，只替换算法决策部分，不替换 Scene、Robot、Runtime 或执行器。
4. Experiment Lab 可在相同条件下调用 Baseline 与 Xiezhi 形成可比较 Trial。
5. Xiezhi 不导入或持有 Gongshu 具体 simulation、camera、control 或 robot 实现。
6. Experiment Lab 不保存仿真实现和资源副本，只保存引用、记录和分析结果。
7. Algorithm 不直接调用机器人执行或 MuJoCo step。
8. Xiezhi 故障只使对应算法不可用，不得中断 Gongshu Baseline。
9. 历史 Mayflower、Xiezhi 和 Gongshu 实验产物继续可读取。
10. 所有实验结果必须能追溯到 Gongshu Runtime 条件、算法身份和 Trial 记录。

## 10. 文档关系

- 本文是当前唯一权威架构冻结记录。
- `XUANSHU_ARCHITECTURE_FREEZE_V1.0.md` 与 `XUANSHU_ARCHITECTURE_FREEZE_V2.0.md` 仅保留为历史记录。
- `GONGSHU_SCOPE.md` 和 `GONGSHU_FREEZE_V0.1.md` 继续约束开源、分发和既有基线，但不得改变本文职责关系。
- Mayflower 的研究协议继续服务其研究问题；其独立 experiment harness 不自动成为 Gongshu Experiment Lab。
- 再次改变上述所有权必须由用户明确批准新的版本化冻结。

## 最终定义

```text
Gongshu        = Robot Body + Runtime
Xiezhi         = Robot Brain / Decision Provider
Experiment Lab = Scientific Experiment Framework
```

三者不是平行项目，而是 Gongshu 机器人平台内部的运行基础、智能算法和科学验证体系。
