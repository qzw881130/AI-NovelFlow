## 1. 后端修复

- [x] 1.1 在 `backend/app/api/shots.py` 的 `generate_shot_video` 函数中，在创建任务后添加 Shot 状态更新调用
- [ ] 1.2 验证后端修改：启动服务后测试视频生成任务创建，确认 Shot 表的 `video_status` 和 `video_task_id` 正确更新

## 2. 前端修复

- [x] 2.1 在 `frontend/my-app/src/pages/ChapterGenerate/stores/slices/generationSlice.ts` 的 `checkVideoTaskStatus` 函数中，修正正则表达式为 `/镜\s*(\d+)/`
- [x] 2.2 在同一文件的 `checkShotTaskStatus` 函数中，将 `task.result_url` 改为 `task.resultUrl`

## 3. 验证测试

- [ ] 3.1 手动测试视频生成流程：创建视频任务 → 确认 Shot 状态更新为 generating → 任务完成后确认前端状态正确同步
- [ ] 3.2 验证工作流详情：在任务队列页面点击查看工作流，确认能正确显示 workflow JSON