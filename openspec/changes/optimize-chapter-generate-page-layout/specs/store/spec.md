# 状态管理规格说明

> **状态**: 已实现
> **最后更新**: 2026-03-08

## ADDED Requirements

### Requirement: Workflow Slice (工作流状态)

系统应管理工作流相关的状态。

#### Scenario: 当前 Tab 状态
- **WHEN** 用户切换 Tab
- **THEN** currentTab 状态应更新为当前选中的 Tab 索引 (0-3)
- **NOTE**: 实际使用数字索引 (0-3) 而非字符串类型

#### Scenario: Tab 完成进度
- **WHEN** 用户完成某个阶段的任务
- **THEN** tabProgress 状态应记录各 Tab 的完成状态
- **NOTE**: 实际使用 Record<number, boolean> 类型

#### Scenario: Tab 切换 API
- **WHEN** 组件调用 setCurrentTab(index)
- **THEN** currentTab 状态应更新为传入的 index 值

#### Scenario: 标记完成 API
- **WHEN** 组件调用 markTabComplete(tabIndex)
- **THEN** tabProgress[tabIndex] 应设置为 true

#### Scenario: 状态持久化
- **WHEN** 工作流状态发生变化
- **THEN** 状态应保存到 localStorage (key: 'chapterGenerate_workflow')

---

### Requirement: SidePanel Slice (侧边栏状态)

系统应管理侧边栏的宽度和收起状态。

#### Scenario: 左侧栏宽度设置
- **WHEN** 用户拖动左侧栏或调用 setLeftPanelWidth(width)
- **THEN** leftPanelWidth 状态应更新为新宽度值 (限制在 200-400px)
- **NOTE**: 实际默认宽度为 200px

#### Scenario: 右侧栏宽度设置
- **WHEN** 用户拖动右侧栏或调用 setRightPanelWidth(width)
- **THEN** rightPanelWidth 状态应更新为新宽度值 (限制在 200-450px)
- **NOTE**: 实际默认宽度为 200px，最大宽度为 450px

#### Scenario: 左侧栏收起切换
- **WHEN** 用户点击左侧栏收起按钮或调用 toggleLeftPanel()
- **THEN** leftPanelCollapsed 状态应切换为相反值

#### Scenario: 右侧栏收起切换
- **WHEN** 用户点击右侧栏收起按钮或调用 toggleRightPanel()
- **THEN** rightPanelCollapsed 状态应切换为相反值

#### Scenario: 状态持久化
- **WHEN** 侧边栏状态发生变化
- **THEN** 新状态应保存到 localStorage，页面刷新后恢复

---

### Requirement: ShotNavigator Slice (分镜导航状态)

系统应管理分镜导航相关的状态。

#### Scenario: 当前分镜设置
- **WHEN** 用户点击分镜缩略图或调用 setCurrentShot(shotId, index)
- **THEN** currentShotId 和 currentShotIndex 应更新为对应的分镜
- **NOTE**: 实际实现需要同时传入 shotId 和 index

#### Scenario: 上一分镜/下一分镜
- **WHEN** 用户调用 previousShot(totalShots) 或 nextShot(totalShots)
- **THEN** currentShotId 应切换到相邻分镜，边界时保持不变
- **NOTE**: 实际实现需要传入总分镜数参数

#### Scenario: 批量选择分镜
- **WHEN** 用户在批量模式下点击分镜缩略图
- **THEN** 该分镜 ID 应添加或移除出 selectedShotIds 数组

#### Scenario: 全选/清空选择
- **WHEN** 用户调用 selectAll() 或 clearSelection()
- **THEN** 所有分镜 ID 应加入 selectedShotIds 或数组应清空

#### Scenario: 批量模式切换
- **WHEN** 用户切换批量模式开关
- **THEN** bulkMode 状态应切换，UI 应相应显示批量操作按钮

---

### Requirement: ComfyUI 状态管理

> **注意**: ComfyUIStatusSlice 未实现为独立的 Store Slice。
> 实际使用全局组件 `src/components/ComfyUIStatus` 来管理 ComfyUI 状态。

系统应显示 ComfyUI 服务的连接和任务状态。

#### Scenario: 连接状态检测
- **WHEN** ComfyUIStatus 组件轮询 ComfyUI 服务
- **THEN** 应显示 ComfyUI 服务的在线/离线状态

#### Scenario: 当前任务状态
- **WHEN** 有任务正在执行
- **THEN** 应显示任务进度信息

#### Scenario: 任务队列状态
- **WHEN** 有多个任务排队
- **THEN** 应显示所有等待中的任务信息

---

### Requirement: 现有 Slice 兼容

系统应保持与现有 dataSlice 和 generationSlice 的 API 兼容。

#### Scenario: 数据获取 API 兼容
- **WHEN** 现有组件调用 dataSlice 的获取方法
- **THEN** 数据获取功能应正常工作，返回预期数据结构

#### Scenario: 生成功能 API 兼容
- **WHEN** 现有组件调用 generationSlice 的生成方法
- **THEN** 生成功能应正常工作，状态更新符合预期

#### Scenario: 无状态冲突
- **WHEN** 新旧 Slice 同时工作
- **THEN** 不应出现状态不一致或冲突
