# Gongshu × Xiezhi Lifecycle Adapter v0.1

Gongshu 是机器人平台，Xiezhi 是 Gongshu Intelligence Layer 内部的可选算法提供者。
本适配器由 Gongshu 拥有，连接双方运行生命周期；它不修改 Gongshu Core、Xiezhi
Core、MuJoCo 控制或动画，也不创建独立 Xiezhi 应用。

## 状态流

```text
MuJoCo public snapshot / state_history
    -> GongshuXiezhiLifecycleAdapter
    -> XiezhiLifecycleRuntime
    -> session-local event record
    -> XiezhiLifecycleStatus
    -> GET /api/xiezhi/status
    -> existing Gongshu + Xiezhi page
```

Gongshu 发送的上下文至少包含 `source`、`robot`、`simulation`、`scene`、
`task` 和 `status`。Xiezhi 只临时保存事件类型、时间戳与该上下文，并返回模块状态、
连接状态和最近事件，不返回算法动作。该记录是 v0.1 状态兼容通道，不是
Experiment Lab Trial Record，也不赋予 Xiezhi 实验生命周期所有权。

## 生命周期事件

- `simulation_start`
- `episode_start`
- `step_update`
- `execution_finish`
- `episode_end`

## 可选性

默认配置启用 lifecycle channel：

```toml
[gongshu_xiezhi]
enabled = true
```

Xiezhi Runtime 不可导入时，adapter 状态为 `unavailable`、`connected = false`，
Gongshu 仍正常启动和运行。配置为 `enabled = false` 时状态为 `disabled`。

## 明确边界

当前连接不调用 Algorithm Registry、Rule Policy、Decision Engine、Action Planner 或
机器人控制。已有 decision adapter 仅作为未来资产保留，没有接入本轮启动、MuJoCo
监听或前端状态链。未来算法输出应在独立边界进入 Gongshu Action Planner，经明确
验证后才能影响 MuJoCo。

按 Architecture Freeze v3.0，后续 Runtime event 应由 Experiment Lab Trial Recorder
组织记录；Xiezhi 只接收决策所需的 State Representation 和 Runtime feedback。
