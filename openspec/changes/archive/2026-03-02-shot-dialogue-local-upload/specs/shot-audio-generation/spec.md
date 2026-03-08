## MODIFIED Requirements

### Requirement: 单分镜音频生成 API

系统 SHALL 提供 API 端点为指定分镜的角色台词生成音频。

#### Scenario: 创建单分镜音频生成任务
- **WHEN** 用户请求为分镜生成音频
- **THEN** 系统 SHALL 为每条台词创建一个 "character_audio" 类型的任务
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
- **WHEN** 音频生成任务执行时
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

### Requirement: 前端分镜音频生成入口

章节分镜生成页面 SHALL 提供音频生成功能入口。

#### Scenario: 单分镜生成音频按钮
- **WHEN** 分镜有台词数据
- **THEN** 分镜编辑区域 SHALL 显示"生成音频"按钮

#### Scenario: 批量生成音频按钮
- **WHEN** 章节有分镜数据
- **THEN** 页面工具栏 SHALL 显示"批量生成音频"按钮

#### Scenario: 生成中状态显示
- **WHEN** 音频生成任务进行中
- **THEN** 按钮 SHALL 显示加载状态
- **AND** 系统 SHALL 轮询追踪任务进度

#### Scenario: 生成失败提示
- **WHEN** 音频生成任务失败
- **THEN** 系统 SHALL 显示错误信息
- **AND** 用户 SHALL 可以重新生成

#### Scenario: 显示音频来源标签
- **WHEN** 台词有音频
- **THEN** 系统 SHALL 显示音频来源标签（"AI 生成" 或 "已上传"）

### Requirement: 前端音频生成 Hook

系统 SHALL 提供 `useAudioGeneration` hook 封装音频生成相关逻辑。

#### Scenario: 单分镜音频生成函数
- **WHEN** 调用 `generateShotAudio` 函数
- **THEN** 系统 SHALL 发送 API 请求并记录返回的任务

#### Scenario: 批量音频生成函数
- **WHEN** 调用 `generateAllAudio` 函数
- **THEN** 系统 SHALL 发送批量 API 请求并记录所有任务

#### Scenario: 音频任务状态查询
- **WHEN** 调用 `checkAudioTaskStatus` 函数
- **THEN** 系统 SHALL 查询任务 API 获取最新状态
- **AND** 若任务完成，系统 SHALL 更新 `audioUrls` 状态

#### Scenario: 任务轮询机制
- **WHEN** 调用 `startPolling` 函数
- **THEN** 系统 SHALL 每 3 秒检查一次任务状态
- **AND** 所有任务完成后系统 SHALL 停止轮询

#### Scenario: 上传音频函数
- **WHEN** 调用 `uploadDialogueAudio` 函数
- **THEN** 系统 SHALL 上传音频文件到对应台词
- **AND** 上传成功后系统 SHALL 更新本地状态

#### Scenario: 删除音频函数
- **WHEN** 调用 `deleteDialogueAudio` 函数
- **THEN** 系统 SHALL 发送删除请求
- **AND** 删除成功后系统 SHALL 清除本地状态

### Requirement: 分镜卡片显示音频列表

分镜图片/视频卡片 SHALL 显示该分镜生成的音频列表，支持播放。

#### Scenario: 有音频的分镜显示音频列表
- **WHEN** 分镜有已生成的音频
- **THEN** 分镜卡片 SHALL 显示音频播放器列表
- **AND** 每个播放器 SHALL 显示对应角色名称

#### Scenario: 音频播放功能
- **WHEN** 用户点击播放按钮
- **THEN** 对应音频 SHALL 通过浏览器播放
- **AND** 播放状态 SHALL 通过 `playingAudio` 状态管理

#### Scenario: 播放状态切换
- **WHEN** 用户再次点击正在播放的音频
- **THEN** 系统 SHALL 停止当前播放

#### Scenario: 重新生成音频
- **WHEN** 用户点击重新生成按钮
- **THEN** 系统 SHALL 删除旧音频并创建新的生成任务

#### Scenario: 音频操作菜单
- **WHEN** 音频播放器有音频
- **THEN** 系统 SHALL 显示操作菜单包含：播放、上传替换、AI 生成、删除