# 需求说明书

## 背景概述

当前系统的视频生成功能仅支持单张分镜图片作为首帧输入,用户无法精确控制视频中的关键动作节点。同时,视频生成时不支持音频参考输入,无法实现口型同步等高级功能。此外,分镜台词仅支持角色台词,不支持旁白台词。

在实际的 AI 视频创作场景中,用户往往需要:
1. 精确控制视频中的多个关键帧(如首帧、尾帧或中间关键动作帧),以确保生成内容符合预期
2. 为视频添加音频参考,实现口型同步或节奏匹配
3. 在分镜中添加旁白台词,并为其生成音频

## 变更目标

- 支持多关键帧控制视频生成,每帧可单独编辑描述和生成/上传图片
- 支持音频作为视频生成的参考输入,用于口型同步
- 支持旁白台词解析和音频生成
- 工作流节点映射配置支持动态扩展关键帧节点

## 功能范围

### 新增功能

| 功能标识 | 功能描述 |
| --- | --- |
| `keyframe-control` | 多关键帧控制功能:支持创建、编辑、AI生成或上传多个关键帧,每帧包含独立的描述和图片 |
| `audio-reference` | 音频参考功能:支持将台词音频、上传音频或角色音色作为视频生成的参考输入 |
| `narrator-support` | 旁白支持功能:解析角色时自动创建旁白角色,支持旁白台词解析和音频生成 |

### 修改功能

| 功能标识 | 变更说明 |
| --- | --- |
| `workflow-node-mapping` | 扩展节点映射配置,支持 `keyframe_node_N` 动态命名约定和 `reference_audio_node_id` 音频节点 |
| `video-gen-status-sync` | 视频生成任务创建时,需处理关键帧图片上传和参考音频上传逻辑 |
| `shot-dialogue-parse` | 扩展台词数据结构,支持 `type` 字段区分角色台词和旁白,支持 `order` 字段控制时序 |
| `shot-audio-generation` | 扩展音频生成逻辑,支持旁白角色的音频生成,按 `order` 字段合并台词音频 |
| `character-management` | 扩展角色模型,新增 `is_narrator` 标识字段,解析时自动创建旁白角色 |

## 影响范围

- **代码模块**:
  - 后端: `models/shot.py`(新增字段)、`models/character.py`(新增字段)、`schemas/shot.py`、`api/shots.py`、`services/shot_video_service.py`、`services/shot_keyframe_service.py`(新建)、`services/shot_audio_service.py`、`services/comfyui/workflows.py`、`services/comfyui/service.py`
  - 前端: `components/KeyframesManager.tsx`(新建)、`components/AudioReferenceSelector.tsx`(新建)、`pages/ChapterGenerate/components/VideoGenTab.tsx`、`pages/ChapterGenerate/components/ShotForm.tsx`

- **API接口**:
  - 新增: 关键帧描述生成、关键帧图片生成/上传、参考音频设置/上传接口
  - 扩展: 视频生成接口支持 `use_keyframes` 和 `use_reference_audio` 参数
  - 扩展: 台词数据结构支持 `type` 和 `order` 字段

- **依赖组件**: ComfyUI 工作流节点支持(用户自行配置对应工作流)

- **关联系统**: 无

## 验收标准

- [ ] 用户可为分镜设置关键帧数量,并独立编辑每帧的描述(支持AI生成描述)
- [ ] 用户可为每个关键帧单独生成图片或上传图片
- [ ] 用户可选择音频参考来源(台词音频合并/上传文件/角色音色/无)
- [ ] 视频生成时正确使用关键帧图片和参考音频
- [ ] 工作流节点映射支持 `keyframe_node_N` 和 `reference_audio_node_id` 配置
- [ ] 前端关键帧管理组件可以正确的展示和管理关键帧状态
- [ ] 解析角色时自动创建"旁白"角色,用户可为其配置音色
- [ ] 分镜编辑支持添加旁白台词,支持区分角色台词和旁白
- [ ] 音频生成支持旁白台词,生成时按 `order` 字段正确合并音频