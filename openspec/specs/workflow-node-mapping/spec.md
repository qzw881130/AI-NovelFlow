# workflow-node-mapping Specification

## Purpose
Defines the requirements for workflow node mapping configuration, particularly for voice design, audio generation, and video generation workflow types. Supports dynamic keyframe node mapping.

## Requirements
### Requirement: 工作流节点映射支持文本节点配置

节点映射配置 SHALL 支持独立的文本节点 ID 映射，用于 CR Prompt Text 类型的节点。

#### Scenario: 音色设计工作流节点映射
- **WHEN** 配置 voice_design 类型工作流的节点映射
- **THEN** 节点映射 SHALL 包含 `voice_prompt_node_id` 用于音色提示词文本节点
- **AND** 节点映射 SHALL 包含 `ref_text_node_id` 用于参考文本节点
- **AND** 节点映射 SHALL 包含 `save_audio_node_id` 用于音频保存节点

#### Scenario: 音频生成工作流节点映射
- **WHEN** 配置 audio 类型工作流的节点映射
- **THEN** 节点映射 SHALL 包含 `text_node_id` 用于生成文本节点
- **AND** 节点映射 SHALL 包含 `emotion_prompt_node_id` 用于情感提示词节点
- **AND** 节点映射 SHALL 包含 `reference_audio_node_id` 用于参考音频节点
- **AND** 节点映射 SHALL 包含 `save_audio_node_id` 用于音频保存节点

### Requirement: 视频生成工作流节点映射

视频生成工作流 SHALL 支持关键帧节点和参考音频节点的动态配置。

#### Scenario: 视频生成基础节点映射
- **WHEN** 配置 video 类型工作流的节点映射
- **THEN** 节点映射 SHALL 包含 `prompt_node_id` 用于视频描述提示词节点
- **AND** 节点映射 SHALL 包含 `seed_node_id` 用于随机种子节点

#### Scenario: 视频生成参考音频节点映射
- **WHEN** 配置 video 类型工作流的参考音频功能
- **THEN** 节点映射 SHALL 包含 `reference_audio_node_id` 用于参考音频输入节点

#### Scenario: 视频生成关键帧节点映射
- **WHEN** 配置 video 类型工作流的关键帧功能
- **THEN** 节点映射 SHALL 支持动态 `keyframe_node_N` 命名约定
- **AND** `keyframe_node_0` SHALL 对应第一个关键帧
- **AND** `keyframe_node_1` SHALL 对应第二个关键帧
- **AND** 依此类推支持任意数量的关键帧

### Requirement: 默认工作流节点映射配置

`DEFAULT_WORKFLOW_NODE_MAPPINGS` 常量 SHALL 为 voice_design、audio、video 和 keyframe_image 类型工作流提供默认节点映射。

#### Scenario: 获取默认音色设计节点映射
- **WHEN** 查询 voice_design 类型的默认节点映射
- **THEN** 系统 SHALL 返回包含 voice_prompt_node_id、ref_text_node_id、save_audio_node_id 的映射配置

#### Scenario: 获取默认音频生成节点映射
- **WHEN** 查询 audio 类型的默认节点映射
- **THEN** 系统 SHALL 返回包含 text_node_id、emotion_prompt_node_id、reference_audio_node_id、save_audio_node_id 的映射配置

#### Scenario: 获取默认视频生成节点映射
- **WHEN** 查询 video 类型的默认节点映射
- **THEN** 系统 SHALL 返回包含 prompt_node_id、seed_node_id、reference_audio_node_id 的映射配置

#### Scenario: 获取默认关键帧图片生成节点映射
- **WHEN** 查询 keyframe_image 类型的默认节点映射
- **THEN** 系统 SHALL 返回包含 prompt_node_id、reference_image_node_id 的映射配置

### Requirement: 关键帧图片生成工作流节点映射

关键帧图片生成工作流 SHALL 支持参考图节点配置。

#### Scenario: 关键帧图片生成参考图节点映射
- **WHEN** 配置 keyframe_image 类型工作流的节点映射
- **THEN** 节点映射 SHALL 包含 `prompt_node_id` 用于关键帧描述提示词节点
- **AND** 节点映射 SHALL 包含 `reference_image_node_id` 用于参考图输入节点

#### Scenario: 关键帧图片生成时注入参考图
- **WHEN** 关键帧图片生成任务执行
- **AND** 关键帧的 `reference_image_url` 不为 null
- **THEN** 系统 SHALL 将参考图上传到 ComfyUI 输入目录
- **AND** 系统 SHALL 将参考图注入到 `reference_image_node_id` 对应节点