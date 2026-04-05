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

### Requirement: 前端音频参考选择组件详细设计

前端 SHALL 提供 AudioReferenceSelector 组件用于设置视频生成的参考音频。

#### Scenario: 组件位置
- **WHEN** 渲染视频生成标签页
- **THEN** AudioReferenceSelector 组件 SHALL 显示在右侧面板关键帧设置区域下方
- **AND** 组件 SHALL 接收当前分镜数据作为 props

#### Scenario: 音频来源选择 UI
- **WHEN** 渲染音频参考选择器
- **THEN** 系统 SHALL 以单选按钮组形式显示四个选项：
  - 无音频参考（默认选中）
  - 合并台词音频
  - 上传音频文件
  - 角色音色

#### Scenario: 选择无音频参考
- **WHEN** 用户选择"无音频参考"
- **THEN** 系统 SHALL 清除 `reference_audio_url`
- **AND** 系统 SHALL 不显示音频预览

#### Scenario: 选择合并台词音频
- **WHEN** 用户选择"合并台词音频"
- **THEN** 系统 SHALL 检查分镜是否有台词音频
- **AND** 若无台词音频，系统 SHALL 显示提示"该分镜无台词音频"
- **AND** 若有台词音频，系统 SHALL 调用合并 API
- **AND** 合并完成后 SHALL 显示音频播放器和时长

#### Scenario: 选择上传音频文件
- **WHEN** 用户选择"上传音频文件"
- **THEN** 系统 SHALL 显示文件上传按钮
- **AND** 上传成功后 SHALL 显示音频播放器

#### Scenario: 选择角色音色
- **WHEN** 用户选择"角色音色"
- **THEN** 系统 SHALL 显示角色下拉选择器
- **AND** 仅显示该分镜已选中的角色
- **AND** 选择角色后 SHALL 使用该角色的 `referenceAudioUrl`

#### Scenario: 音频预览播放
- **WHEN** 已设置参考音频
- **THEN** 组件 SHALL 显示音频播放器
- **AND** 播放器 SHALL 支持：播放/暂停、进度条、时长显示

#### Scenario: 合并音频状态显示
- **WHEN** 合并音频任务进行中
- **THEN** 组件 SHALL 显示加载动画和"合并中..."提示
- **AND** 系统 SHALL 轮询任务状态直到完成

### Requirement: 前端音频参考状态管理

前端 Store SHALL 支持参考音频的状态管理。

#### Scenario: 参考音频状态初始化
- **WHEN** 加载分镜数据
- **THEN** Store SHALL 从分镜数据中解析 `reference_audio_url` 字段
- **AND** Store SHALL 根据URL判断音频来源类型

#### Scenario: 更新参考音频
- **WHEN** 用户更改音频来源设置
- **THEN** Store SHALL 更新分镜的 `reference_audio_url`
- **AND** Store SHALL 同步更新 parsedData 状态

#### Scenario: 音频来源类型推断
- **WHEN** 需要显示当前音频来源类型
- **THEN** 系统 SHALL 根据以下规则推断：
  - URL 为空 → "无"
  - URL 包含 "merged_audio" → "合并台词"
  - URL 包含 "reference_audio" → "上传文件"
  - 其他 → 需要查询角色音色匹配