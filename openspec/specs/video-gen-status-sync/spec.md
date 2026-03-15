# Video Generation Status Sync

## Purpose

Ensure consistent status synchronization between video generation tasks and the Shot table, with proper frontend handling of task data.

## Requirements

### Requirement: Shot 表状态同步更新

当创建视频生成任务时，系统 SHALL 同时更新 Shot 表的 `video_status` 和 `video_task_id` 字段。

#### Scenario: 创建视频生成任务时更新 Shot 状态
- **WHEN** 用户为分镜创建视频生成任务
- **THEN** Shot 表的 `video_status` 应更新为 "generating"
- **AND** Shot 表的 `video_task_id` 应更新为新创建的任务 ID

### Requirement: 前端任务名称匹配

前端轮询任务状态时 SHALL 正确匹配任务名称中的分镜编号，兼容任务名称中"镜"字后有无空格的情况。

#### Scenario: 匹配无空格的任务名称
- **WHEN** 后端返回任务名称为 "生成视频: 镜1"
- **THEN** 前端应正确提取分镜编号 1

#### Scenario: 匹配有空格的任务名称
- **WHEN** 后端返回任务名称为 "生成视频: 镜 1"
- **THEN** 前端应正确提取分镜编号 1

### Requirement: 前端字段名一致性

前端读取任务数据时 SHALL 使用与后端返回格式一致的字段名（camelCase）。

#### Scenario: 读取任务结果 URL
- **WHEN** 后端返回任务数据包含 `resultUrl` 字段
- **THEN** 前端应使用 `task.resultUrl` 读取该字段值
- **AND** 不应使用 `task.result_url` 读取