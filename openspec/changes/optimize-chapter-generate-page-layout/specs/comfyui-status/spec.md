# ComfyUI 状态集成规格说明

> **状态**: 已实现
> **最后更新**: 2026-03-08
> **注意**: 实际实现使用全局 `src/components/ComfyUIStatus` 组件，而非独立的 Store Slice。

## ADDED Requirements

### Requirement: ComfyUI 服务状态检测

系统应能检测 ComfyUI 服务的连接状态。

#### Scenario: 服务在线检测
- **WHEN** ComfyUI 服务正常运行且可访问
- **THEN** 系统应显示"已连接"状态，并显示延迟信息

#### Scenario: 服务离线检测
- **WHEN** ComfyUI 服务不可访问 (宕机/网络问题)
- **THEN** 系统应显示"未连接"状态，并提供重试选项

#### Scenario: 延迟分级显示
- **WHEN** 系统检测到不同延迟水平
- **THEN** 应分级显示：优 (<100ms)、良 (100-500ms)、差 (>500ms)

---

### Requirement: 任务进度实时展示

系统应实时展示 ComfyUI 任务的执行进度。

#### Scenario: 单任务进度显示
- **WHEN** 有单个任务正在执行
- **THEN** 应显示任务类型、进度条、百分比、预计剩余时间

#### Scenario: 多任务队列显示
- **WHEN** 有多个任务在队列中等待
- **THEN** 应显示队列列表，每个任务显示排队位置和类型

#### Scenario: 进度动画
- **WHEN** 任务进度更新时
- **THEN** 进度条应有平滑的动画过渡效果

#### Scenario: 任务完成通知
- **WHEN** 任务完成时
- **THEN** 应显示完成通知，并将任务移至已完成列表

---

### Requirement: 任务队列管理

系统应展示和管理 ComfyUI 任务队列。

#### Scenario: 队列自动更新
- **WHEN** 新任务提交到 ComfyUI
- **THEN** 任务队列应自动反映新任务，无需手动刷新

#### Scenario: 队列任务取消
- **WHEN** 用户取消排队中的任务
- **THEN** 该任务应从队列中移除，状态更新为"已取消"

#### Scenario: 历史任务记录
- **WHEN** 任务完成后
- **THEN** 任务应移至历史记录，显示完成时间和耗时

---

### Requirement: 状态面板 UI

ComfyUI 状态面板应整合在右侧边栏。

#### Scenario: 面板展开/收起
- **WHEN** 用户点击面板标题栏
- **THEN** 面板应展开显示详细内容或收起仅显示标题

#### Scenario: 连接状态可视化
- **WHEN** 面板渲染时
- **THEN** 应使用颜色编码显示状态：绿色 (已连接)、红色 (未连接)、黄色 (连接中)

#### Scenario: 手动刷新按钮
- **WHEN** 用户点击刷新按钮
- **THEN** 系统应立即重新检测 ComfyUI 状态

#### Scenario: 自动刷新指示器
- **WHEN** 自动刷新启用时
- **THEN** 应显示下次自动刷新的倒计时或动画指示器
