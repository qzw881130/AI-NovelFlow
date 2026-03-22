# audio-reference Specification

## Purpose

定义视频生成时音频参考输入的能力要求，支持口型同步等高级视频生成功能。

## Requirements

### Requirement: 分镜存储参考音频

系统 SHALL 允许分镜存储可选的参考音频 URL，用于视频生成时的口型同步。

#### Scenario: 分镜包含参考音频
- **WHEN** 分镜配置了音频参考
- **THEN** 分镜数据 SHALL 包含 `reference_audio_url` 字段

#### Scenario: 参考音频可选
- **WHEN** 分镜未配置音频参考
- **THEN** 分镜记录 SHALL 仍有效，视频生成时不使用音频参考

### Requirement: 音频参考来源选择

前端 SHALL 提供多种音频参考来源选项供用户选择。

#### Scenario: 音频参考来源选项
- **WHEN** 用户配置视频生成的音频参考
- **THEN** 系统 SHALL 提供以下选项：
  - 无音频参考（默认）
  - 合并台词音频
  - 上传音频文件
  - 角色音色

#### Scenario: 选择合并台词音频
- **WHEN** 用户选择"合并台词音频"选项
- **THEN** 系统 SHALL 按台词时序合并该分镜所有台词音频
- **AND** 合并后的音频 SHALL 作为 `reference_audio_url`

#### Scenario: 选择上传音频文件
- **WHEN** 用户选择"上传音频文件"选项并上传文件
- **THEN** 系统 SHALL 保存音频文件并更新 `reference_audio_url`
- **AND** 文件格式 SHALL 支持 MP3、WAV、FLAC

#### Scenario: 选择角色音色
- **WHEN** 用户选择"角色音色"选项
- **THEN** 系统 SHALL 使用角色的 `reference_audio_url` 作为视频参考音频

### Requirement: 上传参考音频

系统 SHALL 支持用户上传参考音频文件。

#### Scenario: 上传参考音频文件
- **WHEN** 用户上传音频文件作为参考音频
- **THEN** 系统 SHALL 保存音频并更新分镜的 `reference_audio_url`

#### Scenario: 参考音频上传 API
- **WHEN** 调用参考音频上传 API
- **THEN** 端点 SHALL 为 `POST /api/novels/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/upload-reference-audio`

### Requirement: 合并台词音频

系统 SHALL 支持按台词时序合并多个音频文件。

#### Scenario: 合并分镜台词音频
- **WHEN** 用户选择合并台词音频
- **THEN** 系统 SHALL 按 `order` 字段排序所有台词
- **AND** 系统 SHALL 按顺序拼接所有台词的 `audio_url`
- **AND** 系统 SHALL 处理角色台词和旁白台词的时序

#### Scenario: 合并音频缓存
- **WHEN** 台词音频已合并
- **THEN** 系统 SHALL 缓存合并后的音频文件
- **AND** 文件名 SHALL 使用格式：`story_{novel_id}/merged_audio/shot_{shot_id}_merged.flac`

### Requirement: 参考音频文件存储

上传的参考音频文件 SHALL 按规范路径存储。

#### Scenario: 参考音频命名规范
- **WHEN** 参考音频上传成功
- **THEN** 文件名 SHALL 使用格式：`story_{novel_id}/reference_audio/shot_{shot_id}.flac`

### Requirement: 工作流节点映射

参考音频节点映射 SHALL 支持在工作流配置中指定。

#### Scenario: 参考音频节点映射
- **WHEN** 配置视频生成工作流的参考音频节点
- **THEN** 节点映射 SHALL 包含 `reference_audio_node_id` 字段
- **AND** 该节点 SHALL 接收分镜的 `reference_audio_url` 作为输入

#### Scenario: 视频生成时注入参考音频
- **WHEN** 视频生成任务执行
- **THEN** 若分镜有 `reference_audio_url`
- **AND** 工作流配置了 `reference_audio_node_id`
- **THEN** 系统 SHALL 将音频 URL 注入到对应节点