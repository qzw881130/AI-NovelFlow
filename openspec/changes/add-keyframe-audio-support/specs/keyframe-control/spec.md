# 功能规格说明

## ADDED Requirements

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

每个关键帧数据 SHALL 包含帧序号、描述、图片信息、参考图和生成状态。

#### Scenario: 完整关键帧数据结构
- **WHEN** 分镜有关键帧
- **THEN** 关键帧数据 SHALL 包含以下字段：
  - `frame_index`: 帧序号（必填，从 0 开始）
  - `description`: 关键帧描述文本（必填）
  - `image_url`: 图片 URL（可选）
  - `image_task_id`: 图片生成任务 ID（可选）
  - `reference_image_url`: 参考图片 URL（可选，null 表示不使用参考图）

#### Scenario: 参考图字段说明
- **WHEN** 关键帧生成图片
- **THEN** `reference_image_url` 字段：
  - 若为 `null`，系统 SHALL 不使用参考图，采用纯文本生成
  - 若有具体 URL，系统 SHALL 使用该图片作为参考图生成

#### Scenario: 参考图默认选择逻辑
- **WHEN** 用户选择"自动选择"参考图
- **AND** `frame_index` 为 0
- **THEN** 系统 SHALL 自动填入分镜图 URL 作为 `reference_image_url`
- **WHEN** 用户选择"自动选择"参考图
- **AND** `frame_index` 大于 0
- **THEN** 系统 SHALL 自动填入 `keyframes[frame_index - 1].image_url` 作为 `reference_image_url`

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

#### Scenario: 设置关键帧参考图
- **WHEN** 用户在关键帧卡片中选择参考图来源
- **THEN** 系统 SHALL 显示三个选项：自动选择、上传图片、不使用
- **AND** 选择"自动选择"时 SHALL 显示将要使用的参考图预览

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

系统 SHALL 支持为每个关键帧单独生成图片，支持可选参考图输入。

#### Scenario: 生成单个关键帧图片
- **WHEN** 用户为关键帧点击"生成图片"按钮
- **THEN** 系统 SHALL 创建图片生成任务
- **AND** 任务 SHALL 使用关键帧的描述作为生成提示词

#### Scenario: 使用参考图生成关键帧图片
- **WHEN** 关键帧的 `reference_image_url` 不为 null
- **THEN** 系统 SHALL 将参考图上传到 ComfyUI
- **AND** 系统 SHALL 将参考图注入到工作流对应节点

#### Scenario: 不使用参考图生成关键帧图片
- **WHEN** 关键帧的 `reference_image_url` 为 null
- **THEN** 系统 SHALL 使用纯文本提示词生成图片

#### Scenario: 批量生成关键帧图片
- **WHEN** 用户点击"批量生成图片"按钮
- **THEN** 系统 SHALL 为所有缺少图片的关键帧创建生成任务
- **AND** 每个关键帧 SHALL 根据各自的 `reference_image_url` 决定是否使用参考图

#### Scenario: 关键帧图片生成 API
- **WHEN** 调用关键帧图片生成 API
- **THEN** 端点 SHALL 为 `POST /api/novels/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/keyframes/{frame_index}/generate-image`

### Requirement: 上传关键帧图片

系统 SHALL 支持用户上传关键帧图片。

#### Scenario: 上传关键帧图片
- **WHEN** 用户为关键帧上传图片文件
- **THEN** 系统 SHALL 保存图片并更新关键帧的 `image_url`

#### Scenario: 关键帧图片上传 API
- **WHEN** 调用关键帧图片上传 API
- **THEN** 端点 SHALL 为 `POST /api/novels/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/keyframes/{frame_index}/upload-image`

### Requirement: 设置关键帧参考图

系统 SHALL 支持为关键帧设置参考图，用于图片生成时的图生图。

#### Scenario: 自动选择参考图
- **WHEN** 用户选择"自动选择"参考图
- **THEN** 若 `frame_index` 为 0，系统 SHALL 设置 `reference_image_url` 为分镜图 URL
- **AND** 若 `frame_index` 大于 0，系统 SHALL 设置 `reference_image_url` 为上一关键帧的 `image_url`

#### Scenario: 上传参考图
- **WHEN** 用户选择上传参考图并上传文件
- **THEN** 系统 SHALL 保存图片并设置 `reference_image_url` 为上传后的 URL

#### Scenario: 清除参考图
- **WHEN** 用户选择"不使用参考图"
- **THEN** 系统 SHALL 将 `reference_image_url` 设置为 null

#### Scenario: 上传关键帧参考图 API
- **WHEN** 调用关键帧参考图上传 API
- **THEN** 端点 SHALL 为 `POST /api/novels/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/keyframes/{frame_index}/upload-reference-image`

#### Scenario: 设置关键帧参考图 API
- **WHEN** 调用关键帧参考图设置 API
- **THEN** 端点 SHALL 为 `PUT /api/novels/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/keyframes/{frame_index}/reference-image`
- **AND** 请求体 SHALL 包含 `reference_image_url` 字段（可为 null）

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

### Requirement: 前端关键帧管理组件详细设计

前端 SHALL 提供 KeyframesManager 组件用于管理关键帧。

#### Scenario: 组件位置
- **WHEN** 渲染视频生成标签页
- **THEN** KeyframesManager 组件 SHALL 显示在右侧面板顶部
- **AND** 组件 SHALL 接收当前分镜数据作为 props

#### Scenario: 关键帧列表展示
- **WHEN** 分镜有关键帧数据
- **THEN** 组件 SHALL 以卡片形式展示每个关键帧
- **AND** 每个卡片 SHALL 显示：帧序号、描述文本、图片缩略图、参考图状态

#### Scenario: 关键帧卡片操作按钮
- **WHEN** 用户悬停在关键帧卡片上
- **THEN** 系统 SHALL 显示操作按钮：生成图片、上传图片、删除

#### Scenario: 参考图选择器交互
- **WHEN** 用户在关键帧卡片中设置参考图
- **THEN** 系统 SHALL 显示三个单选项：
  - 自动选择（默认）：显示参考来源预览（分镜图或上一关键帧图）
  - 上传图片：弹出文件选择器
  - 不使用：清除参考图设置

#### Scenario: 参考图预览
- **WHEN** 关键帧设置了参考图
- **THEN** 卡片 SHALL 显示参考图缩略图
- **AND** 悬停缩略图 SHALL 显示放大预览

#### Scenario: 图片生成状态显示
- **WHEN** 关键帧图片正在生成
- **THEN** 卡片 SHALL 显示加载动画和"生成中..."提示
- **AND** 系统 SHALL 轮询任务状态直到完成

### Requirement: 前端关键帧类型定义

前端 SHALL 定义 TypeScript 类型用于关键帧数据。

#### Scenario: KeyframeData 类型定义
- **WHEN** 定义关键帧数据类型
- **THEN** 类型 SHALL 包含以下字段：
  ```typescript
  interface KeyframeData {
    frame_index: number;
    description: string;
    image_url?: string;
    image_task_id?: string;
    reference_image_url?: string | null;
  }
  ```

#### Scenario: ShotData 类型扩展
- **WHEN** 扩展 ShotData 类型
- **THEN** 类型 SHALL 新增 `keyframes?: KeyframeData[]` 字段
- **AND** 类型 SHALL 新增 `reference_audio_url?: string` 字段

### Requirement: 关键帧状态管理

前端 Store SHALL 支持关键帧数据的状态管理。

#### Scenario: 关键帧状态初始化
- **WHEN** 加载分镜数据
- **THEN** Store SHALL 从分镜数据中解析 `keyframes` 字段
- **AND** 若 `keyframes` 不存在，Store SHALL 初始化为空数组

#### Scenario: 更新关键帧数据
- **WHEN** 用户修改关键帧信息
- **THEN** Store SHALL 更新对应分镜的 `keyframes` 数组
- **AND** Store SHALL 同步更新 parsedData 状态

#### Scenario: 关键帧图片生成任务追踪
- **WHEN** 创建关键帧图片生成任务
- **THEN** Store SHALL 记录 `image_task_id`
- **AND** Store SHALL 轮询任务状态并更新 `image_url`