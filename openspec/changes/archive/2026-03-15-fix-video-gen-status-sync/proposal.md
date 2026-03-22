## Why

视频生成功能存在三个 bug 导致用户体验问题：任务创建后 Shot 表状态未更新、前端任务轮询无法正确匹配任务名称、以及字段名不一致导致状态更新失败。这些问题使得视频生成成功后页面仍显示"生成中"状态，用户无法预览生成的视频。

## What Changes

### 后端修复
- **`backend/app/api/shots.py`**：`generate_shot_video` 接口在创建任务后，需要调用 `shot_repo.update_video_status()` 更新 Shot 表的 `video_status` 和 `video_task_id` 字段

### 前端修复
- **`frontend/my-app/src/pages/ChapterGenerate/stores/slices/generationSlice.ts`**：
  - `checkVideoTaskStatus`：修正正则表达式 `/镜 (\d+)/` 为 `/镜\s*(\d+)/`，兼容有无空格的情况
  - `checkShotTaskStatus`：修正字段名 `task.result_url` 为 `task.resultUrl`，与后端返回格式一致

## Capabilities

### New Capabilities

无。本次变更为纯 bug 修复，不引入新能力。

### Modified Capabilities

无。本次变更不改变现有规格要求，仅修复实现层面的缺陷。

## Impact

### 后端
- `backend/app/api/shots.py` - `generate_shot_video` 函数（约第 240-264 行）

### 前端
- `frontend/my-app/src/pages/ChapterGenerate/stores/slices/generationSlice.ts`
  - `checkVideoTaskStatus` 函数（约第 616-650 行）
  - `checkShotTaskStatus` 函数（约第 538-614 行）

### 影响范围
- 视频生成任务的状态同步
- 分镜视频生成页面的状态显示
- 任务队列页面的工作流详情显示（间接影响）