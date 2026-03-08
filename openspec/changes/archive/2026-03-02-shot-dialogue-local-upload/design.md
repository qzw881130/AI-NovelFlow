## Context

当前分镜台词音频生成功能仅支持 AI 生成，依赖角色的 `reference_audio_url`（音色）通过 ComfyUI 工作流进行语音合成。用户有预录制音频（如专业配音）的使用需求，需要提供音频上传能力。

**现有架构**：
- 后端：`ShotAudioService` 负责 AI 音频生成，`file_storage` 负责文件存储
- 前端：`useAudioGeneration` hook 管理音频生成状态，`JsonTableEditor` 组件展示台词编辑
- 数据结构：`DialogueData` 包含 `audio_url` 和 `audio_task_id` 字段

## Goals / Non-Goals

**Goals:**
- 为每个角色台词提供本地音频文件上传入口
- 支持 AI 生成和上传音频两种来源，可相互切换
- 上传的音频与 AI 生成的音频在 UI 上有一致的展示和播放体验

**Non-Goals:**
- 不涉及音频编辑功能
- 不支持批量上传音频文件
- 不改变现有 AI 音频生成流程

## Decisions

### 决策 1：API 端点设计

**选择**：新增 `POST /api/novels/{novel_id}/chapters/{chapter_id}/shots/{shot_index}/dialogues/{character_name}/audio/upload`

**原因**：
- 遵循 RESTful 风格，资源路径清晰
- 与现有音频生成 API 路径结构一致
- 通过 URL 参数定位具体台词，无需在请求体中传递位置信息

**备选方案**：使用通用文件上传 API 后在请求体中指定关联信息
- 放弃原因：需要两步操作，增加前端复杂度和出错可能

### 决策 2：音频来源标识

**选择**：在 `DialogueData` 中新增 `audio_source` 字段，枚举值为 `ai_generated` | `uploaded`

**原因**：
- 明确区分音频来源，便于 UI 展示不同操作选项
- 为后续可能的音频处理逻辑提供依据（如上传音频可能不需要重新生成）

### 决策 3：文件存储路径

**选择**：上传音频存储路径与 AI 生成音频一致：`story_{novel_id}/shot_audio/shot_{shot_index}_{character_name}.flac`

**原因**：
- 保持存储结构一致性
- 上传音频会覆盖同位置的 AI 生成音频，符合用户预期（替换而非并存）

### 决策 4：前端上传交互

**选择**：在每个台词行添加上传图标按钮，点击触发文件选择

**原因**：
- 与现有 UI 风格一致（参考道具库、角色图片上传）
- 最小化界面改动
- 上传成功后自动更新 UI，无需刷新页面

## Risks / Trade-offs

**风险 1：音频格式兼容性**
- 风险：用户可能上传各种格式（mp3、wav、m4a 等）
- 缓解：后端仅接受常见格式（mp3、wav、flac），前端进行格式提示

**风险 2：音频文件大小**
- 风险：大文件上传可能超时或占用过多存储
- 缓解：限制单文件最大 10MB，前端上传前校验

**风险 3：与 AI 生成冲突**
- 风险：用户上传音频后又触发 AI 生成
- 缓解：AI 生成覆盖上传音频，UI 提示用户确认

**权衡：存储空间**
- 上传音频与 AI 生成音频共用同一存储路径
- 每个台词仅保留最新音频，不保留历史版本
- 理由：简化存储管理，避免空间浪费