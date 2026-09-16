# XUANSHU AI 项目架构冻结说明 v1.0

- 状态：历史版本；已于 2026-09-16 被 `XUANSHU_ARCHITECTURE_FREEZE_V2.0.md` 取代
- 当前权威文档：`XUANSHU_ARCHITECTURE_FREEZE_V3.0.md`
- 生效日期：2026-09-15（统一启动入口于 2026-09-16 补充冻结）
- 适用范围：XUANSHU AI、Gongshu 与 Xiezhi 的产品层级、代码依赖、前端关系和视觉关系
- 性质：架构约束，不代表新增功能、算法或接口已经实现

> 本文仅用于保留历史决策。后续设计与开发必须遵守 v3.0；如与 v3.0 冲突，以 v3.0 为准。

## 1. 总体项目层级

XUANSHU AI（玄枢智能平台）是最高层入口。Gongshu（公输）是机器人智能工作平台；Xiezhi（獬豸）是 Gongshu 内部的算法实验与决策扩展层。

```text
XUANSHU AI
└── Gongshu · Robot Platform
    └── Xiezhi · Algorithm Laboratory / Decision Extension
```

禁止将 Gongshu 与 Xiezhi 设计为两个平级项目、两个独立平台或两个需要分别打开的软件。

## 2. Gongshu 定位冻结

Gongshu 是完整、独立的机器人平台，必须能够单独启动、单独运行、单独展示并单独分享给其他用户。

Gongshu 的完整运行不得要求用户安装 Xiezhi、启动算法实验环境或配置额外模块。移除或禁用 Xiezhi 后，Gongshu 的核心机器人工作流仍必须正常运行。

Gongshu 负责机器人平台能力，包括：

- 视觉输入与感知；
- 空间理解；
- 仿真验证；
- 抓取规划；
- 执行与反馈；
- 机器人结果可视化。

## 3. Xiezhi 定位冻结

Xiezhi 不是新的机器人平台，也不替代 Gongshu。Xiezhi 是 Gongshu 内部可插拔的 Algorithm Laboratory / Decision Extension。

Xiezhi 面向未来的职责包括：

- 算法插入与选择；
- 算法实验；
- 决策输出与验证；
- 实验记录与比较；
- 智能行为分析。

Xiezhi 可以使用 Gongshu 提供的环境、数据、状态、执行反馈和可视化基础，但这种依赖必须保持单向：`Xiezhi → Gongshu`。

## 4. 代码结构与依赖原则

目标结构：

```text
Gongshu
├── core
├── perception
├── simulation
├── execution
├── visualization
└── extensions
    └── xiezhi
        ├── algorithms
        ├── decision
        └── evaluation
```

必须遵守以下不变量：

1. Gongshu 核心不得依赖 Xiezhi。
2. Xiezhi 只能作为 Gongshu 扩展模块存在。
3. 移除或禁用 Xiezhi 后，Gongshu 仍能正常运行。
4. 添加 Xiezhi 后，Gongshu 获得算法实验与智能决策扩展能力。
5. Xiezhi 不得反向成为 Gongshu 启动、运行或展示的前置条件。
6. 新功能必须先判断属于 Gongshu 的机器人平台能力，还是 Xiezhi 的算法实验能力，再确定代码归属。

## 5. 前端关系冻结

固定用户流程：

```text
XUANSHU AI Launcher
→ Gongshu
→ Robot Workspace
→ Xiezhi Algorithm Lab（Gongshu 页面内部）
```

Gongshu 页面可以展示 Xiezhi Algorithm Lab，但不得创建独立 Xiezhi App，不得要求用户打开第二个软件，也不得塑造独立产品入口。

正确体验是：用户进入完整 Gongshu 机器人平台后，自然发现其中包含 Xiezhi 算法实验能力。

## 6. 视觉关系冻结

Gongshu 是视觉主体，Xiezhi 是内部模块。Xiezhi 必须继承 Gongshu 的蓝白科研界面、工程软件风格、简洁克制的布局和机器人实验平台感。

禁止为 Xiezhi 创建独立深色主题、赛博朋克风格、新产品视觉语言或与 Gongshu 明显割裂的界面。

目标标准：`獬豸像长在公输里面`，而不是 `公输旁边多了一个新软件`。

## 7. 未来交互边界

Gongshu 负责机器人表现：视觉、仿真、抓取、执行和输出展示。

Xiezhi 负责智能决策实验：算法选择、决策输出、实验记录和算法比较。

概念关系：Gongshu 提供完整机器人平台和运行基础；Xiezhi 为其增加可选的算法实验能力。

## 8. 当前开发原则

当前阶段不提前实现复杂算法，不提前设计复杂通信。优先保证：

1. Gongshu 独立完整；
2. Xiezhi 能够自然嵌入；
3. 前端层级和视觉关系正确；
4. 后续算法具备清晰扩展空间。

截至本冻结记录，Xiezhi 仅完成 Gongshu 页面内部的前端结构、品牌融合与交互占位；未实现算法、后端、API、实验逻辑或模块数据通信。

## 9. 统一启动入口冻结

XUANSHU AI 平台唯一官方启动入口为：

```text
G:\Vision2Grasp\Start-XUANSHU-LAB.cmd
```

固定启动链路：

```text
Start-XUANSHU-LAB.cmd
→ XUANSHU AI Launcher
→ Gongshu
→ Gongshu 内部的 Offline Image、MuJoCo 与可选 Xiezhi 能力
```

必须遵守以下不变量：

1. 不为 Gongshu、Xiezhi、Offline Image Mode、MuJoCo Experiment 或后续模块新增独立的官方启动入口。
2. 不要求用户进入子项目、开发分支或 Git 工作树启动任何模块。
3. 不创建新的 `start_xxx.bat` 或 `start_xxx.cmd` 替代主入口。
4. 所有模块的打开与调度必须由 XUANSHU AI Launcher 完成。
5. 历史兼容启动文件若暂时保留，只能转发到 `Start-XUANSHU-LAB.cmd`，不得直接启动子服务。
6. Git 工作树只用于隔离开发；功能验收后应合入 `G:\Vision2Grasp`，不得形成第二套用户启动方式。
7. 用户文档、测试说明和交付说明只将 `Start-XUANSHU-LAB.cmd` 标记为官方入口。

该入口规范统一的是用户启动路径，不改变 Gongshu 可脱离 Xiezhi 正常运行的依赖原则。

## 10. 文档关系与变更控制

- 本文冻结产品架构和模块依赖关系。
- `GONGSHU_SCOPE.md` 继续冻结 Gongshu 的开源与分发边界；它不改变本文定义的产品层级。
- `GONGSHU_FREEZE_V0.1.md` 继续作为既有源码与治理基线记录。
- 后续代码、界面或文档若与本文冲突，应先修正设计，不得通过隐式实现改变上述层级。
- 如确需调整冻结关系，必须由用户明确提出并形成新的版本化架构冻结说明。

## 最终架构目标

```text
XUANSHU AI
    └── Gongshu · Robot Platform
            └── Xiezhi · Algorithm Laboratory
```

Gongshu 是平台。Xiezhi 是平台内部持续进化、可选装且不反向绑架核心的算法实验层。
