## ADDED Requirements

### Requirement: 分镜台词音频上传 API

系统 SHALL 提供 API 端点允许用户为指定分镜的角色台词上传本地音频文件。

#### Scenario: 上传音频文件
- **WHEN** 用户通过 API 上传音频文件
- **THEN** 端点 SHALL 为 `POST /api/novels/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/dialogues/{character_name}/audio/upload`
- **AND** 请求 SHALL 使用 `multipart/form-data` 格式
- **AND** 文件字段名 SHALL 为 `file`

#### Scenario: 支持的音频格式
- **WHEN** 用户上传音频文件
- **THEN** 系统 SHALL 接受 mp3、wav、flac 格式
- **AND** 若格式不支持，系统 SHALL 返回 400 错误并提示支持的格式

#### Scenario: 文件大小限制
- **WHEN** 用户上传音频文件
- **THEN** 系统 SHALL 限制单文件最大 10MB
- **AND** 若超过限制，系统 SHALL 返回 400 错误

#### Scenario: 更新分镜台词音频
- **WHEN** 音频上传成功
- **THEN** 系统 SHALL 将音频保存到 `story_{novel_id}/shot_audio/shot_{shot_index}_{character_name}.{ext}`
- **AND** 分镜台词的 `audio_url` SHALL 更新为上传音频的访问 URL
- **AND** 分镜台词的 `audio_source` SHALL 设置为 `uploaded`
- **AND** 分镜台词的 `audio_task_id` SHALL 清空

#### Scenario: 验证分镜存在
- **WHEN** 上传请求中指定的分镜不存在
- **THEN** 系统 SHALL 返回 404 错误

#### Scenario: 验证角色台词存在
- **WHEN** 上传请求中指定的角色在分镜台词中不存在
- **THEN** 系统 SHALL 返回 404 错误

### Requirement: 前端台词音频上传入口

分镜编辑界面 SHALL 为每个角色台词提供音频上传功能。

#### Scenario: 显示上传按钮
- **WHEN** 分镜有台词数据
- **THEN** 每个台词行 SHALL 显示上传音频按钮（图标）

#### Scenario: 触发文件选择
- **WHEN** 用户点击上传按钮
- **THEN** 系统 SHALL 打开文件选择对话框
- **AND** 文件类型过滤器 SHALL 限制为音频文件（.mp3, .wav, .flac）

#### Scenario: 上传进度显示
- **WHEN** 文件正在上传
- **THEN** 上传按钮 SHALL 显示加载状态
- **AND** 用户 SHALL 无法重复点击上传

#### Scenario: 上传成功反馈
- **WHEN** 音频上传成功
- **THEN** 系统 SHALL 显示成功提示
- **AND** 台词行的音频播放器 SHALL 更新为上传的音频

#### Scenario: 上传失败处理
- **WHEN** 音频上传失败
- **THEN** 系统 SHALL 显示错误信息
- **AND** 用户 SHALL 可以重新上传

### Requirement: 音频来源标识

系统 SHALL 区分音频来源类型。

#### Scenario: 数据结构定义
- **WHEN** 存储或返回台词音频信息
- **THEN** `DialogueData` 类型 SHALL 包含 `audio_source` 字段
- **AND** `audio_source` 枚举值 SHALL 为 `ai_generated` 或 `uploaded`

#### Scenario: 默认值
- **WHEN** 台词没有音频
- **THEN** `audio_source` SHALL 为空或不存在

#### Scenario: AI 生成音频标识
- **WHEN** AI 音频生成完成
- **THEN** `audio_source` SHALL 设置为 `ai_generated`

#### Scenario: 上传音频标识
- **WHEN** 用户上传音频成功
- **THEN** `audio_source` SHALL 设置为 `uploaded`

### Requirement: 删除已上传音频

用户 SHALL 可以删除已上传的音频。

#### Scenario: 删除音频 API
- **WHEN** 用户请求删除台词音频
- **THEN** 端点 SHALL 为 `DELETE /api/novels/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/dialogues/{character_name}/audio`

#### Scenario: 删除成功响应
- **WHEN** 删除成功
- **THEN** 系统 SHALL 清除分镜台词的 `audio_url`
- **AND** 系统 SHALL 清除分镜台词的 `audio_source`
- **AND** 系统 SHALL 清除分镜台词的 `audio_task_id`

#### Scenario: 删除前端入口
- **WHEN** 台词有音频（上传或 AI 生成）
- **THEN** 系统 SHALL 显示删除按钮
- **AND** 删除前系统 SHALL 显示确认对话框