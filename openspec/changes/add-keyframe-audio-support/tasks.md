# 实施任务清单

## 1. 数据模型扩展

扩展数据库模型以支持关键帧、参考音频和旁白功能。

- [x] 1.1 扩展 Character 模型添加旁白标识
  - 文件: `backend/app/models/character.py`
  - 新增 `is_narrator` 布尔字段，默认 False

- [x] 1.2 扩展 Shot 模型添加关键帧和参考音频字段
  - 文件: `backend/app/models/shot.py`
  - 新增 `keyframes` JSON 字段
  - 新增 `reference_audio_url` String 字段

- [x] 1.3 更新 Shot Schema 支持新字段
  - 文件: `backend/app/schemas/shot.py`
  - 更新 `ShotCreate`、`ShotUpdate`、`ShotResponse` schema
  - 新增 `KeyframeBase`、`DialogueBase` 子 schema

- [x] 1.4 更新 Character Schema 支持旁白标识
  - 文件: `backend/app/schemas/character.py`
  - 更新 `CharacterCreate`、`CharacterResponse` schema

- [x] 1.5 创建数据库迁移脚本
  - 文件: `backend/app/migrations/versions/xxx_add_keyframe_narrator.py`
  - characters 表添加 `is_narrator` 列
  - shots 表添加 `keyframes` 和 `reference_audio_url` 列

## 2. 旁白角色支持

实现旁白角色的自动创建和音色配置功能。

- [x] 2.1 实现旁白角色自动创建逻辑
  - 文件: `backend/app/services/character_service.py`
  - 新增 `ensure_narrator_character` 方法
  - 在角色解析时自动调用创建旁白角色

- [x] 2.2 更新角色解析服务
  - 文件: `backend/app/services/character_parse_service.py`
  - 解析角色时自动创建旁白角色

- [x] 2.3 更新角色查询 API
  - 文件: `backend/app/api/characters.py`
  - 查询角色时包含旁白角色

- [x] 2.4 前端角色卡片支持旁白标识显示
  - 文件: `frontend/my-app/src/pages/Characters/components/CharacterCard.tsx`
  - 旁白角色显示特殊标识和样式

## 3. 台词类型和时序支持

扩展台词数据结构支持类型区分和时序控制。

- [x] 3.1 更新台词数据结构
  - 文件: `backend/app/schemas/shot.py`
  - Dialogue schema 新增 `type`（枚举：character/narration）字段
  - Dialogue schema 新增 `order`（非负整数）字段
  - Dialogue schema 新增 `audio_source` 字段

- [x] 3.2 更新音频生成服务支持旁白
  - 文件: `backend/app/services/shot_audio_service.py`
  - 新增 `narrator_audio` 任务类型处理
  - 旁白台词音频生成时使用旁白角色的参考音频
  - 错误提示优化：区分角色和旁白的参考音频缺失情况

- [x] 3.3 实现台词音频合并功能
  - 文件: `backend/app/services/audio_merge_service.py`（新建）
  - 按 `order` 字段排序台词
  - 使用 ffmpeg 合并音频文件
  - 生成合并音频缓存文件

- [x] 3.4 前端分镜编辑器支持旁白台词
  - 文件: `frontend/my-app/src/pages/ChapterGenerate/components/ShotForm.tsx`
  - 新增"添加旁白"按钮
  - 台词列表支持类型显示和切换
  - 台词拖拽排序更新 order 字段

## 4. 关键帧功能实现

实现关键帧管理、描述生成、图片生成/上传功能，支持参考图设置。

- [x] 4.1 创建关键帧服务
  - 文件: `backend/app/services/shot_keyframe_service.py`（新建）
  - 实现关键帧描述生成逻辑（调用 LLM）
  - 实现关键帧图片生成逻辑
  - 实现关键帧图片上传逻辑
  - 实现参考图自动选择逻辑（分镜图/上一关键帧）
  - 实现参考图上传和设置逻辑

- [x] 4.2 新增关键帧 API 接口
  - 文件: `backend/app/api/shots.py`
  - POST `/keyframes/generate-descriptions` - 生成关键帧描述
  - POST `/keyframes/{frame_index}/generate-image` - 生成关键帧图片
  - POST `/keyframes/{frame_index}/upload-image` - 上传关键帧图片
  - POST `/keyframes/{frame_index}/upload-reference-image` - 上传参考图
  - PUT `/keyframes/{frame_index}/reference-image` - 设置参考图（支持 auto_select 参数）

- [x] 4.3 前端关键帧管理组件
  - 文件: `frontend/my-app/src/components/KeyframesManager.tsx`（新建）
  - 关键帧列表展示（缩略图 + 描述）
  - 添加/编辑/删除关键帧
  - AI 生成描述按钮
  - 生成/上传图片按钮
  - 参考图设置（自动选择/上传/不使用三种选项）
  - 参考图预览展示
  - 图片生成状态轮询和显示

- [x] 4.4 前端关键帧 Store 扩展
  - 文件: `frontend/my-app/src/pages/ChapterGenerate/stores/`（修改）
  - 新增 keyframes 状态管理
  - 新增关键帧 CRUD 操作方法
  - 新增关键帧图片生成任务追踪
  - 新增参考图状态管理

- [x] 4.5 视频生成标签页集成关键帧组件
  - 文件: `frontend/my-app/src/pages/ChapterGenerate/components/VideoGenTab.tsx`
  - 集成 KeyframesManager 组件到右侧面板
  - 视频生成时传递关键帧数据
  - 更新页面布局适配新组件

- [x] 4.6 前端类型定义扩展
  - 文件: `frontend/my-app/src/types/index.ts`
  - 新增 KeyframeData 接口
  - 扩展 ShotData 接口（keyframes, reference_audio_url）

## 5. 音频参考功能实现

实现视频生成的音频参考输入功能。

- [x] 5.1 创建音频参考服务
  - 文件: `backend/app/services/audio_reference_service.py`（新建）
  - 实现合并台词音频逻辑
  - 实现参考音频上传逻辑
  - 实现角色音色引用逻辑

- [x] 5.2 新增音频参考 API 接口
  - 文件: `backend/app/api/shots.py`
  - POST `/upload-reference-audio` - 上传参考音频
  - POST `/merge-audio` - 合并台词音频
  - POST `/set-reference-audio` - 设置参考音频来源

- [x] 5.3 前端音频参考选择组件
  - 文件: `frontend/my-app/src/components/AudioReferenceSelector.tsx`（新建）
  - 音频来源单选按钮组（无/合并台词/上传/角色音色）
  - "无音频参考"选项：清除 reference_audio_url，不显示播放器
  - "合并台词音频"选项：
    - 检查分镜是否有台词音频
    - 无台词时显示提示"该分镜无台词音频"
    - 有台词时调用合并 API，显示加载状态
    - 合并完成后显示音频播放器
  - "上传音频文件"选项：
    - 显示文件上传按钮
    - 支持 MP3、WAV、FLAC 格式
    - 上传成功后显示音频播放器
  - "角色音色"选项：
    - 显示角色下拉选择器
    - 仅显示该分镜已选中的角色
    - 选择后使用角色的 referenceAudioUrl
  - 音频播放器组件：
    - 播放/暂停按钮
    - 进度条拖拽
    - 时长显示
  - 合并状态显示：
    - 合并中：加载动画 + "合并中..."提示
    - 轮询任务状态直到完成

- [x] 5.4 前端音频参考 Store 扩展
  - 文件: `frontend/my-app/src/pages/ChapterGenerate/stores/`（修改）
  - 参考音频状态初始化：从分镜数据解析 reference_audio_url
  - 音频来源类型推断方法：
    - URL 为空 → "无"
    - URL 包含 "merged_audio" → "合并台词"
    - URL 包含 "reference_audio" → "上传文件"
    - 其他 → 查询角色音色匹配
  - 更新参考音频方法：同步更新分镜数据和 parsedData
  - 合并音频任务追踪：记录任务 ID，轮询状态

- [x] 5.5 视频生成标签页集成音频参考组件
  - 文件: `frontend/my-app/src/pages/ChapterGenerate/components/VideoGenTab.tsx`
  - 集成 AudioReferenceSelector 组件到右侧面板
  - 位于关键帧设置区域下方
  - 视频生成时传递 reference_audio_url 参数
  - 与关键帧组件协调布局

- [x] 5.6 视频生成时注入参考音频
  - 文件: `backend/app/services/shot_video_service.py`
  - 检查分镜是否有参考音频
  - 将参考音频注入工作流对应节点

## 6. 工作流节点映射扩展

扩展工作流节点映射支持关键帧、参考图和参考音频。

- [x] 6.1 更新节点映射配置结构
  - 文件: `backend/app/services/comfyui/workflows.py`
  - 支持动态 `keyframe_node_N` 命名约定（视频生成工作流）
  - 支持 `keyframe_reference_node_N` 命名约定（关键帧图片生成参考图）
  - 新增 `reference_audio_node_id` 配置（视频生成参考音频）

- [x] 6.2 更新前端工作流配置界面
  - 文件: `frontend/my-app/src/pages/Settings/components/MappingModal.tsx`
  - 视频生成工作流新增关键帧节点配置入口
  - 关键帧图片生成工作流新增参考图节点配置
  - 新增参考音频节点配置

- [x] 6.3 更新默认节点映射常量
  - 文件: `backend/app/services/comfyui/workflows.py`
  - DEFAULT_WORKFLOW_NODE_MAPPINGS 新增 video 类型默认映射
  - DEFAULT_WORKFLOW_NODE_MAPPINGS 新增 keyframe_image 类型默认映射（含 reference_image_node_id）

## 7. 视频生成集成

将关键帧和参考音频集成到视频生成流程。

- [x] 7.1 更新视频生成服务处理关键帧
  - 文件: `backend/app/services/shot_video_service.py`
  - 解析 keyframes 数据
  - 根据节点映射上传关键帧图片
  - 动态注入关键帧节点

- [x] 7.2 更新视频生成服务处理参考音频
  - 文件: `backend/app/services/shot_video_service.py`
  - 检查 reference_audio_url
  - 根据 reference_audio_node_id 注入音频

- [x] 7.3 视频生成接口支持新参数
  - 文件: `backend/app/api/shots.py`
  - POST 生成视频接口新增 `use_keyframes` 和 `use_reference_audio` 参数

## 8. 测试与验证

- [x] 8.1 测试旁白角色自动创建
  - 验证解析角色时自动创建旁白角色
  - 验证旁白角色不重复创建

- [x] 8.2 测试台词类型和时序功能
  - 验证添加角色台词和旁白台词
  - 验证台词排序和音频合并顺序正确

- [x] 8.3 测试关键帧功能
  - 验证关键帧描述生成
  - 验证关键帧图片生成/上传
  - 验证视频生成时使用关键帧

- [x] 8.4 测试音频参考功能
  - 验证台词音频合并
  - 验证参考音频上传
  - 验证视频生成时使用参考音频

- [x] 8.5 测试工作流节点映射
  - 验证关键帧节点映射配置
  - 验证参考音频节点映射配置
  - 验证动态关键帧节点解析

## 9. 国际化翻译补充

补充视频生成页面的国际化翻译。

- [x] 9.1 添加音频参考相关翻译键
  - 文件: `frontend/my-app/src/i18n/locales/*/chapters.ts`
  - 新增翻译键:
    - `audioReference` - 音频参考
    - `audioRefNone` - 无
    - `audioRefMerged` - 合并台词
    - `audioRefUploaded` - 上传文件
    - `audioRefCharacter` - 角色音色
    - `mergingAudio` - 合并中...
    - `mergeDialogueAudio` - 合并台词音频
    - `regenerate` - 重新生成
    - `supportedAudioFormats` - 支持格式
    - `noCharacterWithAudio` - 无角色音色提示

## 任务依赖关系

```
1.x 数据模型扩展
    │
    ├──→ 2.x 旁白角色支持
    │        │
    │        └──→ 3.x 台词类型和时序支持
    │                  │
    │                  └──→ 5.x 音频参考功能（合并音频部分）
    │
    ├──→ 6.x 工作流节点映射扩展
    │        │
    │        └──→ 7.x 视频生成集成
    │
    └──→ 4.x 关键帧功能实现
             │
             └──→ 7.x 视频生成集成

8.x 测试与验证（依赖所有实现任务完成）
```

## 建议实施顺序

| 阶段 | 任务 | 说明 |
| --- | --- | --- |
| 阶段一 | 1.x | 数据模型扩展，为后续功能提供数据基础 |
| 阶段二 | 2.x, 3.x | 旁白支持和台词时序，基础功能实现 |
| 阶段三 | 4.x, 5.x | 关键帧和音频参考，核心功能实现 |
| 阶段四 | 6.x, 7.x | 工作流集成和视频生成，完整流程打通 |
| 阶段五 | 8.x | 测试验证，确保功能符合预期 |

## 文件结构总览

```
backend/app/
├── models/
│   ├── character.py          # 修改：新增 is_narrator 字段
│   └── shot.py               # 修改：新增 keyframes, reference_audio_url 字段
├── schemas/
│   ├── character.py          # 修改：更新 schema
│   └── shot.py               # 修改：新增 keyframe, dialogue 子 schema
├── services/
│   ├── character_service.py  # 修改：新增旁白角色逻辑
│   ├── character_parse_service.py  # 修改：解析时创建旁白
│   ├── shot_audio_service.py # 修改：支持旁白音频生成
│   ├── shot_keyframe_service.py    # 新建：关键帧服务
│   ├── shot_video_service.py       # 修改：集成关键帧和参考音频
│   ├── audio_merge_service.py      # 新建：音频合并服务
│   └── audio_reference_service.py  # 新建：音频参考服务
├── api/
│   ├── shots.py              # 修改：新增关键帧和音频参考接口
│   └── characters.py         # 修改：旁白角色查询支持
└── migrations/
    └── versions/xxx_add_keyframe_narrator.py  # 新建：数据库迁移

frontend/my-app/src/
├── components/
│   ├── KeyframesManager.tsx      # 新建：关键帧管理组件
│   └── AudioReferenceSelector.tsx # 新建：音频参考选择组件
├── types/
│   └── index.ts                  # 修改：新增 KeyframeData, DialogueData 类型扩展
└── pages/
    ├── Characters/
    │   └── components/
    │       └── CharacterCard.tsx # 修改：旁白角色标识显示
    ├── ChapterGenerate/
    │   ├── components/
    │   │   ├── ShotForm.tsx      # 修改：支持旁白台词编辑
    │   │   └── VideoGenTab.tsx   # 修改：集成关键帧和音频参考组件
    │   └── stores/
    │       └── index.ts          # 修改：新增关键帧和音频参考状态管理
    └── Settings/
        └── components/
            └── MappingModal.tsx  # 修改：关键帧和音频节点配置
```