# narrator-support Specification

## Purpose

定义旁白角色和旁白台词支持的能力要求，支持在分镜中添加旁白台词并生成音频。

## Requirements

### Requirement: 自动创建旁白角色

解析角色时系统 SHALL 自动创建一个"旁白"角色。

#### Scenario: 解析时创建旁白角色
- **WHEN** 系统解析小说角色
- **THEN** 系统 SHALL 自动创建一个名为"旁白"的角色
- **AND** 该角色的 `is_narrator` 字段 SHALL 为 `true`

#### Scenario: 旁白角色唯一性
- **WHEN** 角色列表中已存在"旁白"角色
- **THEN** 系统 SHALL 不重复创建旁白角色

#### Scenario: 旁白角色音色配置
- **WHEN** 用户为旁白角色配置音色
- **THEN** 旁白角色的 `voice_prompt` 和 `reference_audio_url` SHALL 用于旁白音频生成

### Requirement: 角色模型扩展

Character 模型 SHALL 支持标识旁白角色。

#### Scenario: 角色模型新增字段
- **WHEN** 数据库迁移执行
- **THEN** Character 模型 SHALL 新增 `is_narrator` 布尔字段
- **AND** 该字段默认值 SHALL 为 `false`

### Requirement: 台词类型区分

台词数据 SHALL 支持区分角色台词和旁白台词。

#### Scenario: 台词数据包含类型字段
- **WHEN** 台词数据存在
- **THEN** 台词数据 SHALL 包含 `type` 字段
- **AND** `type` 枚举值 SHALL 为 `character` 或 `narration`

#### Scenario: 角色台词类型
- **WHEN** 台词 `type` 为 `character`
- **THEN** 台词的 `character_name` SHALL 对应角色表中的角色

#### Scenario: 旁白台词类型
- **WHEN** 台词 `type` 为 `narration`
- **THEN** 台词的 `character_name` SHALL 为"旁白"

### Requirement: 台词时序控制

台词数据 SHALL 支持时序控制，用于音频合并。

#### Scenario: 台词数据包含时序字段
- **WHEN** 台词数据存在
- **THEN** 台词数据 SHALL 包含 `order` 字段
- **AND** `order` SHALL 为非负整数

#### Scenario: 台词排序
- **WHEN** 合并台词音频
- **THEN** 系统 SHALL 按 `order` 字段升序排列所有台词
- **AND** 角色台词和旁白台词 SHALL 混合排序

### Requirement: 前端分镜编辑支持旁白

章节分镜生成页面的编辑器 SHALL 支持添加和编辑旁白台词。

#### Scenario: 添加旁白台词
- **WHEN** 用户点击"添加旁白"按钮
- **THEN** 系统 SHALL 创建一条类型为 `narration` 的新台词
- **AND** `character_name` SHALL 自动设置为"旁白"

#### Scenario: 编辑旁白台词内容
- **WHEN** 用户编辑旁白台词的文本内容
- **THEN** 分镜数据 SHALL 实时更新
- **AND** 台词 `type` SHALL 保持为 `narration`

#### Scenario: 旁白台词角色切换
- **WHEN** 用户将旁白台词切换为角色台词
- **THEN** 台词 `type` SHALL 更新为 `character`
- **AND** 用户需选择具体角色

### Requirement: 旁白音频生成

系统 SHALL 支持为旁白台词生成音频。

#### Scenario: 生成旁白音频
- **WHEN** 用户为旁白台词生成音频
- **THEN** 系统 SHALL 使用旁白角色的 `reference_audio_url` 作为参考音频
- **AND** 若旁白角色无参考音频，系统 SHALL 返回错误提示

#### Scenario: 旁白音频生成任务
- **WHEN** 创建旁白音频生成任务
- **THEN** 任务类型 SHALL 为 `narrator_audio`
- **AND** 任务名称 SHALL 使用格式：`生成旁白音频: 镜{shot_index}`

### Requirement: 前端角色管理显示旁白

角色管理页面 SHALL 正确显示旁白角色。

#### Scenario: 角色列表显示旁白
- **WHEN** 角色列表加载完成
- **THEN** 旁白角色 SHALL 显示在列表中
- **AND** 旁白角色卡片 SHALL 显示"旁白"标识

#### Scenario: 旁白角色特殊样式
- **WHEN** 显示旁白角色卡片
- **THEN** 卡片 SHALL 使用特殊样式区分于普通角色
- **AND** 可显示"旁白"标签或图标

### Requirement: 完整台词数据结构

更新后的台词数据结构 SHALL 包含类型和时序字段。

#### Scenario: 完整台词数据结构
- **WHEN** 角色有台词
- **THEN** 台词数据 SHALL 包含以下字段：
  - `type`: 台词类型（必填，枚举值：`character`、`narration`）
  - `order`: 时序序号（必填，非负整数）
  - `character_name`: 角色名称（必填）
  - `text`: 台词文本内容（必填）
  - `emotion_prompt`: 情感提示词（可选，默认"自然"）
  - `audio_url`: 生成的音频 URL（可选）
  - `audio_task_id`: 音频生成任务 ID（可选）
  - `audio_source`: 音频来源（可选，枚举值：`ai_generated`、`uploaded`）