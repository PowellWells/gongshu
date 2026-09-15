# Gongshu × Xiezhi Adapter v0.1

Gongshu 是机器人平台，Xiezhi 是 Gongshu 内部的可选算法决策层。本适配器由 Gongshu 拥有；它不修改 Gongshu Core 或 Xiezhi Core，也不建立独立 Xiezhi 应用。

## 数据流

```text
GongshuObservation
    -> GongshuXiezhiAdapter
    -> installed Xiezhi AlgorithmRegistry / RuleBasedPolicy
    -> GongshuDecision
    -> Gongshu execution callback
    -> IntegrationResult
```

`GongshuObservation` 只包含决策所需的候选、观测质量、不确定性、任务状态和预算，不包含仿真隐藏真值或驱动对象。适配器把 Gongshu grasp pose 转换为 Xiezhi `Pose6D`，由 Xiezhi Runtime 注册的现有策略产生决策，再将通用决策交回 Gongshu 执行侧。

## 开关和兼容性

默认配置：

```toml
[gongshu_xiezhi]
enabled = false
algorithm = "rule_based"
```

- `enabled = false`：只调用调用方提供的 Gongshu legacy flow；不会导入 Xiezhi，也不会调用 Xiezhi execution。
- `enabled = true`：加载可选 Xiezhi Runtime，执行 Observation → Decision → Gongshu execution。
- 显式启用但 Xiezhi 不可导入、算法未注册时明确失败，不静默改变算法或回退。

配置由 Gongshu 应用组装层读取后传入 `XiezhiAdapterConfig`。本轮不修改 `Vision2GraspPipeline`，也不把 Xiezhi 变成 Gongshu 的安装或启动前置条件。

## 当前能力

- 默认算法：Xiezhi Runtime 已注册的 `rule_based`；
- 执行方式：调用方注入 Gongshu execution callback；
- 环境：模块级测试夹具，不连接真实机器人；
- 前端：继续位于 Gongshu 工作台内部，仅显示 adapter ready 和默认关闭状态。

Uncertainty Policy、Prior Policy、Custom Algorithm、真实机器人、后台 HTTP API 和前端实时状态绑定均不属于 v0.1。
