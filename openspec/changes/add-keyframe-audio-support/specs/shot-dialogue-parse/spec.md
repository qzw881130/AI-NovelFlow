# 功能规格说明

## MODIFIED Requirements

### Requirement: 分镜数据存储台词列表

系统 SHALL 允许每个分镜存储可选的台词列表，包含角色名、台词文本、台词类型、时序序号和情感提示词。

#### Scenario: 分镜包含台词数据
- **WHEN** 分镜解析结果包含角色台词或旁白
- **THEN** 分镜数据 SHALL 包含 `dialogues` 数组字段
- **AND** 每个台词项 SHALL 包含 `character_name`、`text`、`type`、`order` 和可选的 `emotion_prompt`

#### Scenario: 台词数据可选
- **WHEN** 分镜没有角色台词和旁白
- **THEN** 分镜记录 SHALL 仍有效，`dialogues` 为空数组或不存在

### Requirement: 台词数据结构

每条台词数据 SHALL 包含角色名称、台词类型、时序序号、台词文本、可选的情感提示词和生成的音频信息。

#### Scenario: 完整台词数据结构
- **WHEN** 角色或旁白有台词
- **THEN** 台词数据 SHALL 包含以下字段：
  - `type`: 台词类型（必填，枚举值：`character`、`narration`）
  - `order`: 时序序号（必填，非负整数）
  - `character_name`: 角色名称（必填，旁白时为"旁白"）
  - `text`: 台词文本内容（必填）
  - `emotion_prompt`: 情感提示词（可选，默认"自然"）
  - `audio_url`: 生成的音频 URL（可选）
  - `audio_task_id`: 音频生成任务 ID（可选）
  - `audio_source`: 音频来源（可选，枚举值：`ai_generated`、`uploaded`）

### Requirement: 前端分镜编辑器支持台词编辑

章节分镜生成页面的表格编辑器 SHALL 支持为每个分镜添加、编辑和删除台词，支持角色台词和旁白台词。

#### Scenario: 显示台词编辑区域
- **WHEN** 用户在分镜编辑器中选中一个分镜
- **THEN** 系统 SHALL 在角色标签下方显示台词编辑区域

#### Scenario: 添加角色台词
- **WHEN** 用户点击"添加台词"按钮
- **THEN** 系统 SHALL 创建一条类型为 `character` 的空白台词记录
- **AND** 角色名下拉列表 SHALL 显示该分镜已选中的角色和"旁白"选项

#### Scenario: 添加旁白台词
- **WHEN** 用户点击"添加旁白"按钮或选择"旁白"作为角色
- **THEN** 系统 SHALL 创建一条类型为 `narration` 的台词记录
- **AND** `character_name` SHALL 自动设置为"旁白"

#### Scenario: 编辑台词内容
- **WHEN** 用户修改台词的文本内容或情感提示词
- **THEN** 分镜数据 SHALL 实时更新
- **AND** JSON 编辑器同步更新

#### Scenario: 删除台词
- **WHEN** 用户点击删除台词按钮
- **THEN** 该台词记录 SHALL 从列表中移除
- **AND** 剩余台词的 `order` SHALL 重新排序

#### Scenario: 台词时序调整
- **WHEN** 用户拖拽调整台词顺序
- **THEN** 台词的 `order` 字段 SHALL 更新为新顺序

### Requirement: 角色必须已在分镜角色列表中或为旁白

添加台词时，角色必须已在该分镜的角色列表中，或选择旁白类型。

#### Scenario: 添加台词时角色不在角色列表
- **WHEN** 分镜的角色列表为空或不包含所选角色
- **AND** 用户未选择"旁白"
- **THEN** 系统 SHALL 提示用户先添加角色
- **AND** 台词编辑区域的添加按钮 SHALL 显示禁用状态

#### Scenario: 添加旁白台词无需角色列表
- **WHEN** 用户添加旁白台词
- **THEN** 系统 SHALL 允许添加，无需检查分镜角色列表