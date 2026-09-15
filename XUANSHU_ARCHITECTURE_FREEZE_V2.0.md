# XUANSHU AI Architecture Freeze v2.0

## Gongshu × Xiezhi Integration Freeze v2.0

- 状态：已确认，自 2026-09-16 起生效
- 适用范围：XUANSHU AI、Gongshu 与 Xiezhi 的产品定位、启动关系、前端表达、代码组织和后续开发
- 文档优先级：本文取代 `XUANSHU_ARCHITECTURE_FREEZE_V1.0.md`，成为当前权威架构记录
- 实施边界：本次冻结统一未来方向，不要求立即重构、移动或删除现有代码

## 1. 本次修订

v2.0 将 Gongshu 与 Xiezhi 的关系从容易被理解为“平台加可选产品扩展”，进一步收敛为“一个机器人智能平台及其内部智能能力”。

| 维度 | 废弃表述 | v2.0 冻结表述 |
| --- | --- | --- |
| 产品主体 | Gongshu 与 Xiezhi 可被分别理解或展示 | Gongshu 是唯一机器人产品主体 |
| Xiezhi 定位 | 可选扩展平台、独立实验入口 | Gongshu 内部智能决策与算法实验能力 |
| 用户动作 | 启动 Gongshu，或启动/进入 Xiezhi | 用户只进入 Gongshu |
| 启动关系 | Launcher 可分别调度两个产品 | Launcher 只打开 Gongshu，由 Gongshu 内部加载 Xiezhi 能力 |
| 前端表达 | “进入 Xiezhi 平台” | Gongshu 内部的智能决策、算法实验与实验分析 |
| 工程边界 | 产品边界可能随代码仓库或 Runtime 分开 | 产品融合，代码继续模块化维护 |

此前任何关于 Xiezhi 可独立启动、独立展示、独立成为 App 或产品入口的说明，自本文生效之日起全部废弃。

## 2. 产品架构冻结

唯一有效的产品关系为：

```text
XUANSHU AI Launcher
└── Gongshu · Robot Intelligence Platform
    ├── Perception
    ├── Spatial Understanding
    ├── Grasp Planning
    ├── MuJoCo Simulation
    ├── Experiment System
    └── Intelligence
        └── Xiezhi · Decision & Algorithm Experiment Capability
```

Gongshu 是主体，Xiezhi 是能力。二者不是两个产品，而是一个系统。

Gongshu 对用户提供完整的机器人智能平台体验，覆盖感知、空间理解、抓取规划、仿真验证、实验体系和智能决策。Xiezhi 是其中持续演进的智能核心，负责承载算法实验、决策模型、智能策略和实验分析能力。

## 3. 用户体验与启动流程

平台唯一官方启动入口保持不变：

```text
G:\Vision2Grasp\Start-XUANSHU-LAB.cmd
```

冻结后的启动流程：

```text
Start-XUANSHU-LAB.cmd
→ XUANSHU AI Launcher
→ Gongshu
→ Gongshu 内部加载 Xiezhi 智能能力
```

用户只需要知道“打开 Gongshu”，不需要知道“启动 Xiezhi”。因此：

1. 不创建 Xiezhi 独立 App、启动器、产品页或桌面入口。
2. 不在 XUANSHU AI Launcher 中提供与 Gongshu 平级的 Xiezhi 卡片。
3. 不要求用户配置或运行第二套 Xiezhi 启动流程。
4. 不为分支、工作树或内部模块建立新的官方入口。
5. Xiezhi Runtime 的装载、状态同步和故障降级均属于 Gongshu 内部启动生命周期。

工程上的模块缺失或 Runtime 不可用可以触发 Gongshu 的可观测降级，但不得被呈现为“请用户另行启动 Xiezhi”。

## 4. Gongshu 与 Xiezhi 新定位

### 4.1 Gongshu

Gongshu 是完整机器人智能平台，负责统一承载：

- 视觉输入与感知；
- 空间理解与场景状态；
- 抓取规划与执行准备；
- MuJoCo 仿真验证；
- 实验配置、运行、记录与分析；
- 智能决策能力及其结果展示。

### 4.2 Xiezhi

Xiezhi 是 Gongshu 内部智能决策与算法实验能力，不是独立平台。其职责包括：

- 算法实验与版本管理；
- 决策模型与策略选择；
- 智能行为分析与解释；
- 实验比较与评价；
- 利用 Gongshu 的观测、环境、状态和执行反馈持续演进。

“Xiezhi”可以继续作为内部模块名、Runtime 名和智能能力品牌使用，但不能形成第二个软件的产品认知。

## 5. 代码组织原则

产品融合不等于代码耦合。目标组织原则为：

```text
Gongshu
├── core
├── perception
├── spatial
├── planning
├── simulation
├── experiment
└── intelligence
    └── xiezhi
        ├── runtime
        ├── algorithms
        ├── decision
        └── evaluation
```

必须遵守：

1. Xiezhi 继续以清晰的内部模块边界维护。
2. 保留已有 Xiezhi Runtime、生命周期适配、状态反馈和实验能力。
3. 不因产品定位调整而大规模移动文件或重写 Runtime。
4. Gongshu 的感知、规划、仿真等基础能力不得依赖某个具体 Xiezhi 算法实现。
5. Xiezhi 通过稳定的内部契约使用 Gongshu 的观测、状态和反馈，避免隐式跨层耦合。
6. Runtime 可降级是系统可靠性设计，不代表 Xiezhi 是独立产品。

## 6. 前端定位冻结

前端只呈现一个 Gongshu 工作空间。Xiezhi 相关功能应作为 Gongshu 内部能力区出现，推荐使用以下用户语言：

- 智能决策；
- 算法实验；
- 实验分析；
- 策略与版本；
- 决策解释。

废弃“进入 Xiezhi 平台”“打开 Xiezhi App”等表达。Xiezhi 必须继承 Gongshu 的蓝白科研工程视觉、导航层级和状态体系，不能形成第二套品牌外壳或软件框架。

## 7. 后续开发归属规则

新增功能必须先按目的归类：

- 服务机器人整体工作流的能力，归属 Gongshu，例如输入源、感知、空间、规划、仿真、执行和通用实验基础设施。
- 服务算法实验、决策模型、智能策略、策略评价的能力，归属 Gongshu 内部 `intelligence/xiezhi` 模块。
- 同时涉及两侧时，由 Gongshu 定义稳定平台契约，Xiezhi 作为内部能力消费契约并返回决策或分析结果。

不得以代码仓库、进程、Runtime 或团队分工为理由，把 Xiezhi 重新包装为独立产品。

## 8. 当前代码处理与迁移方向

本轮不删除代码、不移动目录、不重写 Runtime、不修改实验结果。当前 `src/vision2grasp/extensions/xiezhi`、Xiezhi 生命周期 Runtime 和现有前端区域继续保留。

未来迁移按小步、可回退方式进行：

1. 先统一文档、界面文案和导航语义，消除独立产品表达。
2. 为 Gongshu 内部 intelligence 边界定义稳定契约，并复用现有 adapter 与 lifecycle 成果。
3. 仅在有明确收益和完整回归测试时，将现有 `extensions/xiezhi` 逐步收敛到等价的 `intelligence/xiezhi` 组织结构。
4. 保持历史 import 兼容层，避免一次性迁移破坏 Runtime 或实验记录。
5. 每个迁移阶段都验证统一启动、Gongshu 核心流程、Xiezhi 状态反馈和既有实验结果读取。

上述内容是迁移方向，不是本轮代码重构任务。

## 9. 不变量

后续任何设计和实现必须同时满足：

1. 用户只启动 XUANSHU AI Launcher，并只进入 Gongshu 使用机器人智能能力。
2. Xiezhi 不拥有独立 App、启动器、产品入口或与 Gongshu 平级的工作空间。
3. Gongshu 包含实验与智能决策能力，不把它们外包成第二个平台。
4. Xiezhi 作为内部智能核心持续模块化演进。
5. 不破坏已有 Runtime、实验能力、记录格式和结果可追溯性。
6. 架构调整优先通过兼容、小步迁移完成，不进行无收益的大规模重构。

## 10. 文档关系与变更控制

- 本文是当前 XUANSHU AI、Gongshu 与 Xiezhi 关系的唯一权威冻结记录。
- `XUANSHU_ARCHITECTURE_FREEZE_V1.0.md` 仅保留为历史记录，其冲突内容不再有效。
- `GONGSHU_SCOPE.md` 和 `GONGSHU_FREEZE_V0.1.md` 继续约束开源、分发和既有基线，但不得改变本文的产品关系。
- 如需再次改变 Gongshu 与 Xiezhi 的产品定位，必须由用户明确批准新的版本化架构冻结。

## 最终架构目标

```text
Gongshu = 完整机器人智能平台
Xiezhi  = Gongshu 内部持续进化的智能核心
```

二者不是两个产品，而是一个系统。
