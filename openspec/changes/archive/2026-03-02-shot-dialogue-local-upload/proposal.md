## Why

当前分镜台词音频仅支持通过 AI 生成，依赖角色的参考音频（音色）进行语音合成。但用户可能有预录制的台词音频（如专业配音），希望直接上传使用而非依赖 AI 生成。此需求为用户提供音频来源的灵活性，支持 AI 生成和本地文件上传两种方式。

## What Changes

- 新增分镜台词音频上传 API，支持用户上传本地音频文件
- 前端分镜编辑区新增音频上传入口，每个角色台词可单独上传音频
- 台词数据结构扩展，新增 `audio_source` 字段标识音频来源（`ai_generated` | `uploaded`）
- 上传音频支持预览、替换和删除操作
- AI 生成和上传音频可相互切换（上传音频后可重新 AI 生成覆盖）

## Capabilities

### New Capabilities

- `shot-dialogue-audio-upload`: 分镜台词音频上传能力，支持用户为每个角色台词上传本地音频文件

### Modified Capabilities

- `shot-audio-generation`: 扩展音频来源支持，区分 AI 生成和用户上传两种音频类型

## Impact

**后端**:
- 新增音频上传 API 端点
- `DialogueData` 数据结构扩展（新增 `audio_source` 字段）
- 文件存储服务扩展支持台词音频上传

**前端**:
- `JsonTableEditor` 组件扩展，每个台词行新增上传按钮
- `useAudioGeneration` hook 扩展上传相关逻辑
- 新增音频文件上传组件

**数据库**:
- 章节解析数据中的 `dialogues` 数组结构扩展