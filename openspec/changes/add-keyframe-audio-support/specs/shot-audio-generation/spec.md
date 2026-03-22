# 功能规格说明

## ADDED Requirements

### Requirement: 旁白音频生成

系统 SHALL 支持为旁白台词生成音频。

#### Scenario: 检查旁白角色是否有参考音频
- **WHEN** 为旁白台词生成音频
- **THEN** 系统 SHALL 检查旁白角色（`is_narrator=true`）是否有 `reference_audio_url`
- **AND** 若无参考音频，系统 SHALL 返回错误提示

#### Scenario: 音频生成使用旁白参考音频
- **WHEN** 旁白台词音频生成任务执行时
- **THEN** 旁白角色的 `reference_audio_url` SHALL 作为工作流的参考音频输入
- **AND** 台词文本 SHALL 注入到 `text_node_id` 节点
- **AND** 情感提示词 SHALL 注入到 `emotion_prompt_node_id` 节点

#### Scenario: 旁白台词任务类型标识
- **WHEN** 创建旁白台词音频生成任务
- **THEN** 任务类型 SHALL 为 "narrator_audio"
- **AND** 任务 SHALL 关联 novel_id、chapter_id
- **AND** 任务 SHALL 关联旁白角色的 character_id

#### Scenario: 旁白台词任务名称格式
- **WHEN** 创建旁白台词音频生成任务
- **THEN** 任务名称 SHALL 使用格式：`生成旁白音频: 镜{shot_index}`

### Requirement: 台词音频按时序合并

系统 SHALL 支持按时序顺序合并分镜内所有台词音频。

#### Scenario: 按时序合并台词音频
- **WHEN** 用户请求合并台词音频用于视频生成
- **THEN** 系统 SHALL 按 `order` 字段升序排列所有台词
- **AND** 角色台词和旁白台词 SHALL 混合排序
- **AND** 系统 SHALL 按顺序拼接所有台词音频

#### Scenario: 合并音频缓存存储
- **WHEN** 台词音频合并完成
- **THEN** 合并音频文件名 SHALL 使用格式：`story_{novel_id}/merged_audio/shot_{shot_id}_merged.flac`

## MODIFIED Requirements

### Requirement: 单分镜音频生成 API

系统 SHALL 提供 API 端点为指定分镜的角色台词和旁白台词生成音频。

#### Scenario: 创建单分镜音频生成任务
- **WHEN** 用户请求为分镜生成音频
- **THEN** 系统 SHALL 为每条台词创建一个任务
- **AND** 角色台词任务类型 SHALL 为 "character_audio"
- **AND** 旁白台词任务类型 SHALL 为 "narrator_audio"
- **AND** 任务 SHALL 使用 audio 类型的 ComfyUI 工作流

#### Scenario: API 端点定义
- **WHEN** 调用单分镜音频生成 API
- **THEN** 端点 SHALL 为 `POST /api/novels/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/audio`
- **AND** 请求体 SHALL 包含 `dialogues` 数组

#### Scenario: 检查角色是否有参考音频
- **WHEN** 为角色台词生成音频
- **THEN** 系统 SHALL 检查角色是否有 `reference_audio_url`
- **AND** 若无参考音频，系统 SHALL 返回错误提示

#### Scenario: 音频生成使用角色参考音频
- **WHEN** 角色台词音频生成任务执行时
- **THEN** 角色的 `reference_audio_url` SHALL 作为工作流的参考音频输入
- **AND** 台词文本 SHALL 注入到 `text_node_id` 节点
- **AND** 情感提示词 SHALL 注入到 `emotion_prompt_node_id` 节点

#### Scenario: 音频生成完成后更新分镜数据
- **WHEN** 音频生成任务成功完成
- **THEN** 分镜台词的 `audio_url` SHALL 更新为生成的音频 URL
- **AND** 分镜台词的 `audio_source` SHALL 设置为 `ai_generated`
- **AND** 任务状态 SHALL 更新为 "completed"

#### Scenario: 音频生成覆盖上传音频
- **WHEN** 台词已有上传音频
- **THEN** AI 生成 SHALL 覆盖原有音频文件
- **AND** `audio_source` SHALL 更新为 `ai_generated`

#### Scenario: 工作流节点映射验证
- **WHEN** 创建音频生成任务前
- **THEN** 系统 SHALL 验证 audio 工作流的节点映射配置
- **AND** 若节点映射无效，系统 SHALL 返回 400 错误

### Requirement: 批量章节音频生成 API

系统 SHALL 提供 API 端点批量生成章节所有分镜的角色台词和旁白台词音频。

#### Scenario: 创建批量音频生成任务
- **WHEN** 用户请求批量生成章节音频
- **THEN** 系统 SHALL 遍历所有分镜的台词
- **AND** 为每条台词创建独立的音频生成任务
- **AND** 根据台词 `type` 字段决定任务类型

#### Scenario: 批量生成 API 端点定义
- **WHEN** 调用批量音频生成 API
- **THEN** 端点 SHALL 为 `POST /api/novels/{novel_id}/chapters/{chapter_id}/audio/generate-all`

#### Scenario: 批量生成跳过无台词分镜
- **WHEN** 分镜没有台词数据
- **THEN** 系统 SHALL 跳过该分镜，不创建任务

#### Scenario: 批量生成跳过无参考音频的角色
- **WHEN** 角色没有 `reference_audio_url`
- **THEN** 系统 SHALL 跳过该角色的台词，并在返回结果中记录警告

#### Scenario: 批量生成跳过无参考音频的旁白
- **WHEN** 旁白角色没有 `reference_audio_url`
- **THEN** 系统 SHALL 跳过旁白台词，并在返回结果中记录警告

#### Scenario: 批量生成返回任务列表
- **WHEN** 批量生成请求提交成功
- **THEN** 系统 SHALL 返回所有创建的任务 ID 列表
- **AND** 每个任务 SHALL 包含分镜索引、角色名称和台词类型
- **AND** 返回数据 SHALL 包含 `total_tasks` 和 `total_warnings` 计数

### Requirement: 音频生成任务类型

系统 SHALL 支持 `character_audio` 和 `narrator_audio` 任务类型用于分镜角色和旁白台词音频生成。

#### Scenario: 角色台词任务类型标识
- **WHEN** 创建角色台词音频生成任务
- **THEN** 任务类型 SHALL 为 "character_audio"
- **AND** 任务 SHALL 关联 novel_id、chapter_id、character_id

#### Scenario: 任务进度追踪
- **WHEN** 音频生成任务执行中
- **THEN** 任务进度 SHALL 可通过任务 API 查询

#### Scenario: 角色台词任务名称格式
- **WHEN** 创建角色台词音频生成任务
- **THEN** 任务名称 SHALL 使用格式：`生成台词音频: 镜{shot_index}-{character_name}`

#### Scenario: 检查已有进行中任务
- **WHEN** 创建音频生成任务前
- **THEN** 系统 SHALL 检查是否已有相同分镜角色的进行中任务
- **AND** 若有，系统 SHALL 返回已有任务信息而不创建新任务