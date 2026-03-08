## ADDED Requirements

### Requirement: 标签页布局组织内容

系统 SHALL 将 ChapterGenerate 页面内容按工作流阶段组织为标签页。

#### Scenario: 四个标签页展示
- **WHEN** 用户访问 ChapterGenerate 页面
- **THEN** 页面 SHALL 显示四个标签页："内容准备"、"资源库"、"分镜制作"、"合成导出"
- **AND** 每个标签页包含对应工作流阶段的内容

#### Scenario: 标签页内容分组
- **WHEN** 用户切换标签页
- **THEN** "内容准备" 标签页 SHALL 包含章节内容、AI 解析、JSON 编辑步骤
- **AND** "资源库" 标签页 SHALL 包含角色、场景、道具资源管理
- **AND** "分镜制作" 标签页 SHALL 包含分镜图和视频生成
- **AND** "合成导出" 标签页 SHALL 包含转场和最终视频合成

### Requirement: 标签页状态保持

系统 SHALL 在标签页切换时保持各标签页的状态。

#### Scenario: 切换标签页状态保持
- **WHEN** 用户从"分镜制作"切换到"资源库"再切换回来
- **THEN** "分镜制作"标签页的滚动位置和选择状态 SHALL 保持
- **AND** 用户操作上下文 SHALL 不丢失

#### Scenario: Store 状态跨标签页共享
- **WHEN** 用户在"资源库"标签页更新角色图片
- **THEN** 更新 SHALL 自动反映到"分镜制作"标签页的角色引用
- **AND** 无需手动刷新或重新加载

### Requirement: 步骤指示器反映当前标签页

系统 SHALL 在标签页布局中保留步骤指示器功能。

#### Scenario: 步骤指示器高亮当前步骤
- **WHEN** 用户在"分镜制作"标签页操作分镜图生成
- **THEN** 步骤指示器 SHALL 高亮显示"分镜"步骤
- **AND** 用户可以快速了解当前工作流进度

#### Scenario: 步骤点击导航到对应标签页
- **WHEN** 用户点击步骤指示器中的"角色"步骤
- **THEN** 页面 SHALL 自动切换到"资源库"标签页
- **AND** 滚动到角色资源区域

### Requirement: 组件文件大小限制

系统 SHALL 确保重构后单个组件文件不超过 500 行。

#### Scenario: 主入口文件简化
- **WHEN** 重构 index.tsx
- **THEN** 文件 SHALL 只包含布局和标签页逻辑
- **AND** 文件行数 SHALL 不超过 500 行

#### Scenario: 子组件独立文件
- **WHEN** 功能模块超过 200 行
- **THEN** 该模块 SHALL 拆分为独立组件文件
- **AND** 通过 props 或 Store 共享数据