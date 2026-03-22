## Context

当前视频生成流程存在状态同步问题：

```
期望流程：
┌────────────────┐     ┌────────────────────┐     ┌──────────────────────┐
│ 创建任务       │────▶│ 更新 Shot 状态     │────▶│ 前端轮询更新 UI      │
│ video_status   │     │ video_status=      │     │ videoStatus=         │
│ = pending      │     │ "generating"       │     │ task.status          │
└────────────────┘     └────────────────────┘     └──────────────────────┘
        ✗ 当前缺失           ✗ 当前缺失              ✗ 正则匹配失败

问题链：
1. 后端未更新 Shot.video_status → Shot 表状态不同步
2. 前端正则 `/镜 (\d+)/` 要求空格，但后端任务名 `"生成视频: 镜1"` 无空格
3. 前端用 `task.result_url` 读取，但后端返回 `resultUrl`
```

## Goals / Non-Goals

**Goals:**
- 确保视频生成任务创建时，Shot 表的 `video_status` 和 `video_task_id` 正确更新
- 确保前端轮询能正确匹配任务名称（兼容有无空格）
- 确保前端使用正确的字段名读取后端返回的数据

**Non-Goals:**
- 不改变现有 API 结构或返回格式
- 不修改数据库模型
- 不涉及转场视频或音频生成的相关逻辑

## Decisions

### Decision 1: 后端 Shot 状态更新位置

**选择**：在 `generate_shot_video` API 中，创建任务后立即调用 `shot_repo.update_video_status()`

**理由**：
- 与图片生成逻辑保持一致（`generate_shot_image` 在第 120 行有类似调用）
- 确保状态更新在事务内完成
- 不需要修改后台任务逻辑

**实现**：
```python
# backend/app/api/shots.py (约第 240-249 行之后)
# 在 task_repo.create_shot_video_task() 之后添加：

shot_repo.update_video_status(shot, "generating", task_id=task.id)
```

### Decision 2: 前端正则表达式修正

**选择**：使用 `/镜\s*(\d+)/` 替代 `/镜 (\d+)/`

**理由**：
- `\s*` 匹配零个或多个空白字符
- 兼容后端可能的不同格式（"镜1"、"镜 1"、"镜  1"）
- 更健壮，避免因格式差异导致匹配失败

**实现**：
```typescript
// frontend/.../generationSlice.ts
// checkVideoTaskStatus 函数中
const match = task.name?.match(/镜\s*(\d+)/);
```

### Decision 3: 前端字段名修正

**选择**：统一使用 camelCase 字段名 `resultUrl`

**理由**：
- 后端 `TaskService.format_task_list` 返回的是 `resultUrl`（第 293 行）
- 保持前后端字段名一致
- 避免因字段名不匹配导致数据读取失败

**实现**：
```typescript
// frontend/.../generationSlice.ts
// checkShotTaskStatus 函数中
// 将 task.result_url 改为 task.resultUrl
```

## Risks / Trade-offs

### Risk 1: 已有任务数据不一致
- **风险**：已存在的失败任务可能没有正确的 `video_status`
- **缓解**：本次修复只影响新创建的任务，历史数据不受影响。用户重试失败任务时会创建新任务，新任务会正确更新状态。

### Risk 2: 正则表达式过于宽松
- **风险**：`\s*` 可能意外匹配其他内容
- **缓解**：`镜` 字符在任务名称中是唯一的标识符，误匹配风险极低。且正则限制了数字捕获，即使匹配到其他"镜"字，后续逻辑也会有容错处理。