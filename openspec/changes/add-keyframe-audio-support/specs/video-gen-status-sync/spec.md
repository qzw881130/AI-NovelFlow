# 功能规格说明

## MODIFIED Requirements

### Requirement: Shot 表状态同步更新

当创建视频生成任务时，系统 SHALL 同时更新 Shot 表的 `video_status`、`video_task_id` 字段，并处理关键帧图片和参考音频的上传。

#### Scenario: 创建视频生成任务时更新 Shot 状态
- **WHEN** 用户为分镜创建视频生成任务
- **THEN** Shot 表的 `video_status` 应更新为 "generating"
- **AND** Shot 表的 `video_task_id` 应更新为新创建的任务 ID

#### Scenario: 视频生成任务处理关键帧图片
- **WHEN** 分镜有关键帧数据
- **THEN** 系统 SHALL 将关键帧图片上传到 ComfyUI 输入目录
- **AND** 根据工作流节点映射配置注入对应节点

#### Scenario: 视频生成任务处理参考音频
- **WHEN** 分镜有参考音频配置
- **THEN** 系统 SHALL 将参考音频上传到 ComfyUI 输入目录
- **AND** 根据工作流 `reference_audio_node_id` 配置注入对应节点