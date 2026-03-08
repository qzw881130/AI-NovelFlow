
## 1. 后端 API 实现

- [x] 1.1 新增音频上传 API 端点 `POST /shots/{shot_index}/dialogues/{character_name}/audio/upload`
- [x] 1.2 实现音频文件格式校验（mp3、wav、flac）和大小限制（10MB）
- [x] 1.3 实现音频删除 API 端点 `DELETE /shots/{shot_index}/dialogues/{character_name}/audio`
- [x] 1.4 更新 `ShotAudioService` 的 `_update_shot_dialogue_audio_url` 方法，新增 `audio_source` 参数
- [x] 1.5 AI 音频生成完成后设置 `audio_source` 为 `ai_generated`

## 2. 数据结构扩展

- [x] 2.1 更新 `DialogueData` 类型定义，新增 `audio_source` 字段
- [x] 2.2 更新前端 `types.ts` 中的 `DialogueData` 接口
- [x] 2.3 更新前端 `api/chapters.ts` 中的 `DialogueData` 类型

## 3. 前端 API 集成

- [x] 3.1 在 `chapterApi` 中新增 `uploadDialogueAudio` 方法
- [x] 3.2 在 `chapterApi` 中新增 `deleteDialogueAudio` 方法

## 4. 前端 Hook 扩展

- [x] 4.1 在 `useAudioGeneration` hook 中新增 `uploadDialogueAudio` 函数
- [x] 4.2 在 `useAudioGeneration` hook 中新增 `deleteDialogueAudio` 函数
- [x] 4.3 扩展 `JsonTableEditorProps` 接口，新增上传和删除相关回调

## 5. 前端 UI 组件

- [x] 5.1 在 `JsonTableEditor` 组件中为每个台词行添加上传按钮
- [x] 5.2 实现文件选择对话框和上传进度显示
- [x] 5.3 显示音频来源标签（"AI 生成" 或 "已上传"）
- [x] 5.4 添加删除音频按钮和确认对话框
- [x] 5.5 实现音频操作菜单（播放、上传替换、AI 生成、删除）

## 6. 国际化

- [x] 6.1 添加上传相关的中英文翻译 key
- [x] 6.2 添加音频来源标签的翻译
- [x] 6.3 添加删除确认对话框的翻译

## 7. 测试与验证

- [x] 7.1 测试音频上传 API（格式校验、大小限制）
- [x] 7.2 测试音频删除 API
- [x] 7.3 测试 AI 生成覆盖上传音频的场景
- [x] 7.4 测试前端上传交互流程
- [x] 7.5 测试音频来源标签显示