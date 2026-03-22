# keyframe-control Specification

## Purpose

定义多关键帧控制视频生成的能力要求，支持用户为分镜设置多个关键帧，每个关键帧包含独立的描述和图片。

## Requirements

### Requirement: 分镜存储关键帧数据

系统 SHALL 允许每个分镜存储可选的关键帧列表，包含描述、图片URL和来源类型。

#### Scenario: 分镜包含关键帧数据
- **WHEN** 分镜配置了关键帧控制
- **THEN** 分镜数据 SHALL 包含 `keyframes` 数组字段
- **AND** 每个关键帧项 SHALL 包含 `description`、`image_url`、`image_source` 和 `frame_index` 字段

#### Scenario: 关键帧数据可选
- **WHEN** 分镜未配置关键帧
- **THEN** 分镜记录 SHALL 仍有效，`keyframes` 为空数组或不存在

### Requirement: 关键帧数据结构

每个关键帧数据 SHALL 包含帧序号、描述、图片信息和生成状态。

#### Scenario: 完整关键帧数据结构
- **WHEN** 分镜有关键帧
- **THEN** 关键帧数据 SHALL 包含以下字段：
  - `frame_index`: 帧序号（必填，从 0 开始）
  - `description`: 关键帧描述文本（必填）
  - `image_url`: 图片 URL（可选）
  - `image_source`: 图片来源（可选，枚举值：`ai_generated`、`uploaded`）
  - `image_task_id`: 图片生成任务 ID（可选）

### Requirement: 前端关键帧管理组件

章节分镜生成页面 SHALL 提供关键帧管理组件，支持添加、编辑、删除关键帧。

#### Scenario: 显示关键帧管理入口
- **WHEN** 用户在视频生成标签页
- **THEN** 系统 SHALL 显示"关键帧设置"区域
- **AND** 显示已有关键帧的缩略图列表

#### Scenario: 添加关键帧
- **WHEN** 用户点击"添加关键帧"按钮
- **THEN** 系统 SHALL 创建一条新的关键帧记录
- **AND** 新关键帧的 `frame_index` SHALL 为当前最大序号 + 1

#### Scenario: 编辑关键帧描述
- **WHEN** 用户编辑关键帧的描述文本
- **THEN** 分镜数据 SHALL 实时更新

#### Scenario: 删除关键帧
- **WHEN** 用户点击删除关键帧按钮
- **THEN** 该关键帧记录 SHALL 从列表中移除
- **AND** 剩余关键帧的 `frame_index` SHALL 重新排序

### Requirement: AI 生成关键帧描述

系统 SHALL 支持基于分镜描述和剧情生成关键帧描述。

#### Scenario: 生成关键帧描述
- **WHEN** 用户点击"AI生成描述"按钮
- **THEN** 系统 SHALL 调用 LLM 生成分镜中每个关键帧的描述
- **AND** 描述 SHALL 基于分镜的剧情描述和角色动作

#### Scenario: 关键帧描述生成 API
- **WHEN** 调用关键帧描述生成 API
- **THEN** 端点 SHALL 为 `POST /api/novels/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/keyframes/generate-descriptions`

### Requirement: AI 生成关键帧图片

系统 SHALL 支持为每个关键帧单独生成图片。

#### Scenario: 生成单个关键帧图片
- **WHEN** 用户为关键帧点击"生成图片"按钮
- **THEN** 系统 SHALL 创建图片生成任务
- **AND** 任务 SHALL 使用关键帧的描述作为生成提示词

#### Scenario: 批量生成关键帧图片
- **WHEN** 用户点击"批量生成图片"按钮
- **THEN** 系统 SHALL 为所有缺少图片的关键帧创建生成任务

#### Scenario: 关键帧图片生成 API
- **WHEN** 调用关键帧图片生成 API
- **THEN** 端点 SHALL 为 `POST /api/novels/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/keyframes/{frame_index}/generate-image`

### Requirement: 上传关键帧图片

系统 SHALL 支持用户上传关键帧图片。

#### Scenario: 上传关键帧图片
- **WHEN** 用户为关键帧上传图片文件
- **THEN** 系统 SHALL 保存图片并更新关键帧的 `image_url`
- **AND** 关键帧的 `image_source` SHALL 设置为 `uploaded`

#### Scenario: 关键帧图片上传 API
- **WHEN** 调用关键帧图片上传 API
- **THEN** 端点 SHALL 为 `POST /api/novels/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/keyframes/{frame_index}/upload-image`

### Requirement: 关键帧文件存储路径

生成的关键帧图片文件 SHALL 按规范路径存储。

#### Scenario: 关键帧图片命名规范
- **WHEN** 关键帧图片生成或上传成功
- **THEN** 文件名 SHALL 使用格式：`story_{novel_id}/keyframes/shot_{shot_id}_frame_{frame_index}.png`

### Requirement: 工作流节点映射约定

关键帧节点映射 SHALL 遵循动态命名约定。

#### Scenario: 关键帧节点映射命名
- **WHEN** 配置视频生成工作流的关键帧节点映射
- **THEN** 节点 ID SHALL 使用格式：`keyframe_node_N`（N 从 0 开始）
- **AND** N SHALL 对应关键帧的 `frame_index`

#### Scenario: 获取关键帧节点映射
- **WHEN** 视频生成工作流需要关键帧输入
- **THEN** 系统 SHALL 根据节点映射 `keyframe_node_0`、`keyframe_node_1` 等注入对应关键帧图片