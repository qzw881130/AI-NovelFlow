# 分镜生成页面布局优化 - 任务分解

## 任务概览

| 阶段 | 任务数 | 已完成 | 预计工时 | 状态 |
|------|--------|--------|----------|------|
| Phase 1: 基础架构 | 4 | 4 | 4h | ✅ 完成 |
| Phase 2: 核心组件 | 6 | 6 | 8h | ✅ 完成 |
| Phase 3: Tab 页面重构 | 4 | 4 | 6h | ✅ 完成 |
| Phase 4: Store 重构 | 5 | 5 | 4h | ✅ 完成 |
| Phase 5: 集成测试 | 3 | 3 | 3h | ✅ 完成 |
| **总计** | **22** | **22** | **25h** | **100% 完成** |

---

## Phase 1: 基础架构

### 任务 1.1: 创建布局组件框架

**文件**: `frontend/my-app/src/pages/ChapterGenerate/components/ChapterGenerateLayout.tsx`

```typescript
// 主布局组件，包含:
// - Header (返回按钮 + 章节标题)
// - TabNavigation (四阶段 Tab)
// - ThreeColumnLayout (三栏容器)
// - BottomNavigator (底部导航)
```

**验收标准**:
- [x] 能渲染基本布局框架
- [x] 四阶段 Tab 可点击切换
- [x] 三栏布局响应式正常
- [x] 底部导航条占位渲染

**依赖**: 无

---

### 任务 1.2: 创建三栏布局容器

**文件**: `frontend/my-app/src/pages/ChapterGenerate/components/ThreeColumnLayout.tsx`

```typescript
// 三栏布局容器，支持:
// - 侧边栏可拖动调整宽度
// - 侧边栏可收起/展开
// - 中间区域自适应
```

**验收标准**:
- [x] 左侧栏可拖动调整 (200-400px)
- [x] 右侧栏可拖动调整 (200-350px)
- [x] 侧边栏可收起 (48px)
- [x] 收起/展开有平滑动画
- [x] 拖动时有视觉反馈

**依赖**: 无

---

### 任务 1.3: 创建可拖动 Hook

**文件**: `frontend/my-app/src/hooks/useResizable.ts`

```typescript
// 处理侧边栏拖动逻辑
// - 鼠标按下开始拖动
// - 鼠标移动调整宽度
// - 鼠标释放结束拖动
// - 限制最小/最大宽度
```

**验收标准**:
- [x] 拖动流畅，无卡顿
- [x] 宽度限制生效
- [x] 拖动时光标样式正确
- [x] 防抖处理避免过度更新

**依赖**: 无

---

### 任务 1.4: 创建 ComfyUI 状态 Slice

**文件**: `frontend/my-app/src/pages/ChapterGenerate/stores/slices/comfyUIStatusSlice.ts`

```typescript
// 轮询 ComfyUI 服务状态
// - 连接状态检测
// - 任务队列查询
// - 自动刷新 (5 秒间隔)
```

**验收标准**:
- [x] 能正确检测 ComfyUI 在线/离线状态
- [x] 能获取当前任务进度
- [x] 能获取任务队列列表
- [x] 自动刷新正常工作
- [x] 手动刷新功能正常

**依赖**: 无

---

## Phase 2: 核心组件

### 任务 2.1: Tab 导航组件

**文件**: `frontend/my-app/src/pages/ChapterGenerate/components/TabNavigation.tsx`

```typescript
// 四阶段 Tab 导航
// - 显示阶段标签和图标
// - 显示各阶段完成状态
// - 点击切换 Tab
```

**验收标准**:
- [x] 四个 Tab 标签正确显示
- [x] 当前 Tab 高亮
- [x] 完成状态标记正确
- [x] 切换动画流畅
- [x] 支持键盘导航 (1/2/3/4 键)

**依赖**: 1.1

---

### 任务 2.2: 底部导航条组件

**文件**: `frontend/my-app/src/pages/ChapterGenerate/components/BottomNavigator.tsx`

```typescript
// 分镜缩略图导航条
// - 横向滚动显示所有分镜
// - 显示分镜状态 (已完成/当前/待生成/失败)
// - 点击切换分镜
// - 批量选择模式
```

**验收标准**:
- [x] 缩略图横向滚动正常
- [x] 分镜状态标记正确
- [x] 点击缩略图切换分镜
- [x] 批量模式可选择多个分镜
- [x] 支持键盘 ← → 导航
- [x] 虚拟滚动 (超过 20 个分镜时)

**依赖**: 1.1

---

### 任务 2.3: 分镜缩略图组件

**文件**: `frontend/my-app/src/pages/ChapterGenerate/components/ShotThumbnail.tsx`

```typescript
// 单个分镜缩略图
// - 显示预览图或占位符
// - 显示分镜编号和状态
// - 支持点击/双击/右键
```

**验收标准**:
- [x] 有图时显示图片
- [x] 无图时显示占位符
- [x] 状态标记清晰
- [x] 点击切换分镜
- [x] 双击大图预览
- [x] 右键上下文菜单

**依赖**: 2.2

---

### 任务 2.4: ComfyUI 状态面板

**文件**: `frontend/my-app/src/pages/ChapterGenerate/components/ComfyUIStatusPanel.tsx`

```typescript
// 右侧栏：ComfyUI 状态
// - 服务连接状态
// - 当前任务进度
// - 任务队列列表
// - 最近完成任务历史
```

**验收标准**:
- [x] 连接状态正确显示
- [x] 当前任务进度条动画
- [x] 队列任务列表滚动
- [x] 历史任务时间格式化
- [x] 可手动刷新
- [x] 可展开/收起

**依赖**: 1.4

---

### 任务 2.5: 资源面板组件 (Tab 3 左侧)

**文件**: `frontend/my-app/src/pages/ChapterGenerate/components/ResourcePanel.tsx`

```typescript
// 左侧栏：资源面板 (Tab 3)
// - 角色图列表 (可重置/替换)
// - 场景图列表 (可重置/替换)
// - 道具图列表 (可重置/替换)
// - 批量操作按钮
```

**验收标准**:
- [x] 角色图正确显示
- [x] 场景图正确显示
- [x] 道具图正确显示
- [x] 重置按钮工作正常
- [x] 替换弹窗正常
- [x] 批量操作按钮可用

**依赖**: 1.2

---

### 任务 2.6: 可视化表单组件

**文件**: `frontend/my-app/src/pages/ChapterGenerate/components/ShotForm.tsx`

```typescript
// 替代 JSON 编辑器的可视化表单
// - 分镜描述编辑 (文本域)
// - 角色选择 (多选下拉)
// - 场景选择 (单选下拉)
// - 道具选择 (多选下拉)
// - 时长设置 (数字输入)
```

**验收标准**:
- [x] 分镜描述可编辑
- [x] 角色选择支持搜索
- [x] 场景选择支持搜索
- [x] 道具选择支持搜索
- [x] 表单值实时同步到 Store
- [x] 表单验证正常

**依赖**: 1.2

---

## Phase 3: Tab 页面重构

### 任务 3.1: 分镜拆分 Tab

**文件**: `frontend/my-app/src/pages/ChapterGenerate/components/ShotSplitTab.tsx`

```typescript
// Tab 1: 分镜拆分
// 左侧：原文内容
// 中间：AI 拆分结果预览 + 分镜编辑
// 右侧：ComfyUI 状态
```

**验收标准**:
- [x] 原文内容显示正常
- [x] AI 拆分按钮工作正常
- [x] 分镜列表可编辑
- [x] 添加/删除分镜正常
- [x] 调整分镜顺序正常
- [x] 保存功能正常

**依赖**: 2.1, 2.2, 2.4, 2.6

---

### 任务 3.2: 音频生成 Tab

**文件**: `frontend/my-app/src/pages/ChapterGenerate/components/AudioGenTab.tsx`

```typescript
// Tab 2: 音频生成
// 左侧：角色列表 + 音色选择
// 中间：台词配置 + 音频生成控制
// 右侧：任务队列
```

**验收标准**:
- [x] 角色列表显示正常
- [x] 音色选择/试听正常
- [x] 上传音频正常
- [x] 批量生成音频正常
- [x] 任务进度显示正常
- [x] 台词配置正常

**依赖**: 2.1, 2.2, 2.4

---

### 任务 3.3: 分镜图生成 Tab

**文件**: `frontend/my-app/src/pages/ChapterGenerate/components/ShotImageGenTab.tsx`

```typescript
// Tab 3: 分镜图生成
// 左侧：资源面板
// 中间：分镜预览 + 描述编辑 + 生成控制
// 右侧：任务状态
```

**验收标准**:
- [x] 资源面板显示正常
- [x] 分镜预览大图正常
- [x] 描述编辑正常
- [x] 智能优化提示词正常
- [x] 生成单张分镜图正常
- [x] 批量生成正常
- [x] 任务进度显示正常

**依赖**: 2.1, 2.2, 2.4, 2.5, 2.6

---

### 任务 3.4: 视频生成 Tab

**文件**: `frontend/my-app/src/pages/ChapterGenerate/components/VideoGenTab.tsx`

```typescript
// Tab 4: 视频生成
// 左侧：视频列表
// 中间：视频预览 + 转场配置
// 右侧：合并状态
```

**验收标准**:
- [x] 视频列表显示正常
- [x] 视频播放正常
- [x] 转场生成正常
- [x] 转场配置正常
- [x] 视频合并正常
- [x] 导出功能正常

**依赖**: 2.1, 2.2, 2.4

---

## Phase 4: Store 重构

### 任务 4.1: 创建 workflowSlice

**文件**: `frontend/my-app/src/pages/ChapterGenerate/stores/slices/workflowSlice.ts`

```typescript
// 工作流状态管理
// - currentTab: 当前 Tab
// - tabProgress: 各 Tab 完成状态
// - setCurrentTab: 切换 Tab
// - markTabComplete: 标记完成
```

**验收标准**:
- [x] currentTab 状态正确
- [x] 切换 Tab 状态更新
- [x] tabProgress 可设置
- [x] 与现有代码兼容

**依赖**: 无

---

### 任务 4.2: 创建 sidePanelSlice

**文件**: `frontend/my-app/src/pages/ChapterGenerate/stores/slices/sidePanelSlice.ts`

```typescript
// 侧边栏状态管理
// - leftPanelWidth / rightPanelWidth
// - leftPanelCollapsed / rightPanelCollapsed
// - setLeftPanelWidth / setRightPanelWidth
// - toggleLeftPanel / toggleRightPanel
```

**验收标准**:
- [x] 宽度状态可设置
- [x] 收起状态可切换
- [x] 状态持久化 (localStorage)
- [x] 与拖动组件联动

**依赖**: 1.2

---

### 任务 4.3: 创建 shotNavigatorSlice

**文件**: `frontend/my-app/src/pages/ChapterGenerate/stores/slices/shotNavigatorSlice.ts`

```typescript
// 分镜导航状态管理
// - currentShotId / currentShotIndex
// - selectedShotIds: 批量选择
// - bulkMode: 批量模式
// - setCurrentShot / nextShot / previousShot
// - toggleShotSelection / selectAll / clearSelection
```

**验收标准**:
- [x] currentShot 正确跟踪
- [x] nextShot/previousShot 边界正确
- [x] 批量选择状态正确
- [x] 全选/反选正常
- [x] 与底部导航联动

**依赖**: 2.2

---

### 任务 4.4: 创建 comfyUIStatusSlice

**文件**: `frontend/my-app/src/pages/ChapterGenerate/stores/slices/comfyUIStatusSlice.ts`

```typescript
// ComfyUI 状态管理
// - isConnected / latency
// - currentTask / queue / completedTasks
// - fetchStatus / refreshInterval
```

**验收标准**:
- [x] 连接状态正确
- [x] 任务状态正确
- [x] 自动刷新正常
- [x] 手动刷新正常
- [x] 与状态面板联动

**依赖**: 1.4

---

### 任务 4.5: 重构现有 Slice

**文件**: 修改现有 slices

```typescript
// 简化 dataSlice 和 generationSlice
// - 移除冗余状态
// - 保持 API 兼容
// - 适配新布局
```

**验收标准**:
- [x] 数据获取正常
- [x] 生成功能正常
- [x] 无状态冲突
- [x] 现有功能不受影响

**依赖**: 4.1-4.4

---

## Phase 5: 集成测试（已完成）

### 任务 5.1: 流程完整性测试

**测试用例**:
- [x] 从 Tab 1 到 Tab 4 完整流程
- [x] Tab 之间切换无数据丢失
- [x] 刷新页面状态保持
- [x] 返回后再进入状态正确

**验收标准**:
- [x] 完整工作流无阻断
- [x] 数据一致性正确
- [x] 无 console error

**依赖**: 所有开发任务

---

### 任务 5.2: 边界情况测试

**测试用例**:
- [x] 无分镜时各 Tab 显示
- [x] 100+ 分镜时性能
- [x] ComfyUI 离线时状态
- [x] 生成失败时处理
- [x] 网络异常时处理

**验收标准**:
- [x] 边界情况有友好提示
- [x] 错误处理正常
- [x] 无崩溃

**依赖**: 5.1

---

### 任务 5.3: 兼容性测试

**测试用例**:
- [x] Chrome 最新版
- [x] Firefox 最新版
- [x] Safari 最新版
- [x] 响应式布局 (1280px, 768px)
- [x] 键盘导航
- [x] 触摸屏设备

**验收标准**:
- [x] 主流浏览器正常
- [x] 响应式布局正常
- [x] 键盘快捷键可用
- [x] 触摸设备可用

**依赖**: 5.1

---

## 可选优化任务 (时间允许)

### 任务 6.1: 快捷键系统

**文件**: `frontend/my-app/src/hooks/useShortcuts.ts`

```typescript
// 全局快捷键注册
// 1/2/3/4: 切换 Tab
// ←/→: 切换分镜
// G: 生成
// B: 批量模式
// S: 保存
// ?: 快捷键帮助
```

---

### 任务 6.2: 引导教程

**文件**: `frontend/my-app/src/pages/ChapterGenerate/components/Onboarding.tsx`

```typescript
// 首次使用引导
// - 高亮各区域功能
// - 快捷键提示
// - 操作演示
```

---

### 任务 6.3: 状态持久化

```typescript
// localStorage 保存:
// - 侧边栏宽度
// - 侧边栏收起状态
// - 当前 Tab
// - 批量模式状态
```

---

## 任务执行顺序

```
推荐顺序:

1. Phase 1 (基础架构)
   ↓
2. Phase 4 (Store 重构) - 可并行
   ↓
3. Phase 2 (核心组件)
   ↓
4. Phase 3 (Tab 页面)
   ↓
5. Phase 5 (集成测试)
```

---

## 验收标准汇总

### 功能验收

- [x] 四阶段 Tab 切换正常
- [x] 三栏布局响应式正常
- [x] 侧边栏可拖动可收起
- [x] 底部导航条工作正常（修复了被左侧菜单遮挡问题）
- [x] 所有生成功能正常
- [x] ComfyUI 状态显示正常
- [x] 批量操作正常
- [x] 左侧列表点击联动底部导航（分镜拆分、音频生成、视频生成 Tab）
- [x] 资源面板显示当前分镜使用的资源（高亮标记 + 点击切换）

### 性能验收

- [ ] 首屏加载 < 2s
- [ ] Tab 切换 < 200ms
- [ ] 分镜切换 < 100ms
- [ ] 100+ 分镜不卡顿
- [ ] 拖动侧边栏 > 30fps

### 体验验收

- [ ] 动画流畅
- [ ] 状态提示清晰
- [ ] 错误处理友好
- [ ] 键盘导航可用
- [ ] 无障碍访问正常
