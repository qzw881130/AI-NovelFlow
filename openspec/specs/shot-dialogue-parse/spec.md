# shot-dialogue-parse Specification

## Purpose
定义分镜数据解析时提取角色台词、旁白台词和情感提示词的能力要求，支持在章节分镜生成页面展示和编辑。支持台词类型区分和时序控制。

## Requirements

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

### Requirement: 台词数据持久化

台词数据 SHALL 随章节数据一起保存，无需独立的持久化逻辑。

#### Scenario: 保存章节数据时包含台词
- **WHEN** 用户保存章节的解析数据
- **THEN** 台词数据 SHALL 随 `parsedData` 一起保存到数据库

#### Scenario: 加载章节数据时恢复台词
- **WHEN** 用户加载已保存的章节
- **THEN** 分镜的台词数据 SHALL 正确显示在编辑器中

### Requirement: 台词编辑输入缓存

系统 SHALL 提供本地编辑缓存机制，确保用户输入时的输入框状态稳定。

#### Scenario: 台词文本输入缓存
- **WHEN** 用户在台词文本输入框中输入内容
- **THEN** 系统 SHALL 使用本地编辑缓存显示输入内容
- **AND** 缓存 SHALL 在 JSON 更新时保持输入框状态稳定

#### Scenario: 情感提示词输入缓存
- **WHEN** 用户在情感提示词输入框中输入内容
- **THEN** 系统 SHALL 使用本地编辑缓存显示输入内容

### Requirement: 台词角色切换历史缓存

系统 SHALL 在切换台词角色时保存和恢复该角色的台词内容。

#### Scenario: 切换角色时保存旧角色台词
- **WHEN** 用户在台词条目中切换角色
- **THEN** 系统 SHALL 保存旧角色的台词文本和情感提示词到历史缓存
- **AND** 缓存 key SHALL 使用格式 `shotIndex_dialogueIndex_characterName`

#### Scenario: 切换回已编辑过的角色时恢复内容
- **WHEN** 用户切换到一个之前在该台词位置编辑过的角色
- **THEN** 系统 SHALL 从历史缓存中恢复该角色的台词文本和情感提示词
- **AND** 若无缓存，系统 SHALL 使用默认值（空文本，"自然"情感）

### Requirement: 单个台词生成音频

台词编辑区 SHALL 为每条台词提供单独的音频生成入口。

#### Scenario: 无音频时显示生成按钮
- **WHEN** 台词有角色名且无音频
- **THEN** 系统 SHALL 显示"生成音频"按钮
- **AND** 点击按钮 SHALL 为该台词创建音频生成任务

#### Scenario: 音频生成中状态显示
- **WHEN** 音频生成任务进行中
- **THEN** 系统 SHALL 显示加载动画和"音频生成中..."提示

#### Scenario: 音频生成失败状态
- **WHEN** 音频生成任务失败
- **THEN** 系统 SHALL 显示失败提示
- **AND** 系统 SHALL 显示"重新生成"按钮