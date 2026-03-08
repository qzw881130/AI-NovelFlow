## MODIFIED Requirements

### Requirement: 分镜数据独立存储在 shots 表

系统 SHALL 将分镜数据从 `parsed_data` JSON 字段迁移到独立的 `shots` 表，每个分镜作为独立记录存储。

#### Scenario: 分镜数据存储在独立表中
- **WHEN** 章节进行分镜拆分
- **THEN** 每个分镜 SHALL 创建独立的 Shot 记录
- **AND** Shot 记录包含 description、characters、scene、props、duration 等字段
- **AND** Shot 记录通过 `chapter_id` 外键关联到章节

#### Scenario: 分镜图片资源存储在 Shot 记录中
- **WHEN** 分镜图片生成完成
- **THEN** 图片 URL SHALL 存储到 Shot 记录的 `image_url` 字段
- **AND** 图片状态 SHALL 更新到 `image_status` 字段
- **AND** 任务 ID SHALL 存储到 `image_task_id` 字段

#### Scenario: 分镜视频资源存储在 Shot 记录中
- **WHEN** 分镜视频生成完成
- **THEN** 视频 URL SHALL 存储到 Shot 记录的 `video_url` 字段
- **AND** 视频状态 SHALL 更新到 `video_status` 字段

#### Scenario: 并发生成不同分镜资源
- **WHEN** 同时生成分镜 A 的图片和分镜 B 的视频
- **THEN** 两个更新操作 SHALL 互不影响
- **AND** 数据 SHALL 正确保存，无 Lost Update 问题

### Requirement: Shot 表结构与索引

系统 SHALL 创建包含以下字段的 Shot 表：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | String | PK | UUID 主键 |
| chapter_id | String | FK, Index | 关联章节 |
| index | Integer | Index | 分镜序号（1-based） |
| description | Text | | 分镜描述 |
| characters | Text | | JSON 角色列表 |
| scene | String | | 场景名称 |
| props | Text | | JSON 道具列表 |
| duration | Integer | | 时长（秒） |
| image_url | String | | 图片 URL |
| image_path | String | | 图片本地路径 |
| image_status | String | Index | 图片状态 |
| image_task_id | String | | 图片任务 ID |
| video_url | String | | 视频 URL |
| video_status | String | Index | 视频状态 |
| video_task_id | String | | 视频任务 ID |
| merged_character_image | String | | 合并角色图 URL |
| dialogues | Text | | JSON 台词数据 |

#### Scenario: 复合索引支持高效查询
- **WHEN** 查询指定章节的分镜列表
- **THEN** 系统 SHALL 使用 `(chapter_id, index)` 复合索引
- **AND** 查询 SHALL 高效返回按序排列的分镜列表

#### Scenario: 状态索引支持过滤查询
- **WHEN** 查询指定状态的分镜（如未生成图片的分镜）
- **THEN** 系统 SHALL 使用 `image_status` 或 `video_status` 索引
- **AND** 查询 SHALL 高效过滤结果

### Requirement: Chapter 冗余字段移除

系统 SHALL 移除 Chapter 模型中的以下冗余字段：
- `shot_images`
- `shot_videos`
- `character_images`

#### Scenario: parsed_data 简化
- **WHEN** 分镜数据迁移完成
- **THEN** `parsed_data` SHALL 只保留 `characters`、`scenes`、`props`、`transition_videos` 字段
- **AND** `shots` 数组 SHALL 从 `parsed_data` 中移除

#### Scenario: 转场视频保留在 parsed_data
- **WHEN** 转场视频生成完成
- **THEN** 视频 URL SHALL 存储在 `parsed_data.transition_videos` 中
- **AND** 格式为 `{"1-2": "/api/files/...", "2-3": "/api/files/..."}`

### Requirement: API 响应向后兼容

系统 SHALL 在 API 响应中保持原有字段格式，确保前端兼容性。

#### Scenario: 章节详情响应包含 shots 数组
- **WHEN** 请求章节详情 API
- **THEN** 响应 SHALL 包含从 Shot 表聚合生成的 `shots` 数组
- **AND** 每个 shot 对象 SHALL 包含 id、description、image_url、video_url 等字段

#### Scenario: 分镜列表 API
- **WHEN** 请求 `GET /api/novels/{novel_id}/chapters/{chapter_id}/shots`
- **THEN** 响应 SHALL 返回该章节的所有分镜列表
- **AND** 分镜 SHALL 按 index 升序排列

### Requirement: 数据库迁移无损

系统 SHALL 提供数据迁移脚本，确保现有数据无损迁移到新结构。

#### Scenario: 迁移脚本将 shots 数组迁移到独立表
- **WHEN** 执行数据库迁移脚本
- **THEN** 脚本 SHALL 从 `parsed_data.shots` 创建 Shot 记录
- **AND** 每个 Shot 记录 SHALL 正确关联到对应章节
- **AND** 迁移后原 `parsed_data` 中的 shots 数组 SHALL 被移除

#### Scenario: 迁移可回滚
- **WHEN** 需要回滚迁移
- **THEN** 系统 SHALL 能从 Shot 表重建 `parsed_data.shots` 数组
- **AND** 数据 SHALL 完整恢复