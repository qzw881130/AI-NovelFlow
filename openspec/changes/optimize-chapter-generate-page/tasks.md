## 1. 阶段一：后端数据模型迁移

### 1.1 创建 Shot 模型
- [x] 1.1.1 创建 `app/models/shot.py` 文件，定义 Shot 模型
- [x] 1.1.2 在 `app/models/__init__.py` 中导出 Shot 模型
- [x] 1.1.3 更新 Chapter 模型，添加 `shots` relationship

### 1.2 数据库迁移脚本
- [x] 1.2.1 创建迁移脚本 `migrations/migrate_shots_to_separate_table.py`
- [x] 1.2.2 实现从 `parsed_data.shots` 到 Shot 表的数据迁移逻辑
- [x] 1.2.3 实现迁移后从 `parsed_data` 移除 `shots` 数组
- [x] 1.2.4 编写迁移测试脚本，验证数据迁移正确性
- [x] 1.2.5 执行迁移并在测试环境验证

### 1.3 创建 Repository 和 Service
- [x] 1.3.1 创建 `app/repositories/shot_repository.py`
- [x] 1.3.2 实现 `get_by_chapter()`、`get_by_id()`、`create()`、`update()` 方法
- [x] 1.3.3 创建 `app/services/shot_service.py`
- [x] 1.3.4 在 `app/api/deps.py` 添加 `get_shot_repo` 依赖

### 1.4 创建 Shot API
- [x] 1.4.1 创建 `app/api/shots_api.py`（或更新现有 `shots.py`）
- [x] 1.4.2 实现 `GET /shots` 分镜列表接口
- [x] 1.4.3 实现 `GET /shots/{shot_id}` 分镜详情接口
- [x] 1.4.4 实现 `PATCH /shots/{shot_id}` 分镜更新接口
- [x] 1.4.5 创建 `app/schemas/shot.py` 定义请求/响应 schema

### 1.5 更新现有服务和 API
- [x] 1.5.1 更新 `shot_image_service.py`，使用 Shot 记录而非 parsed_data
- [x] 1.5.2 更新 `shot_video_service.py`，使用 Shot 记录
- [x] 1.5.3 更新 `shot_audio_service.py`，更新 Shot.dialogues 字段
- [x] 1.5.4 更新 `novel_service.py` 的分镜拆分逻辑，创建 Shot 记录
- [x] 1.5.5 更新转场视频逻辑，使用 parsed_data.transition_videos

### 1.6 API 兼容性处理
- [x] 1.6.1 更新章节详情 API，从 Shot 表聚合 shots 数组
- [x] 1.6.2 更新 `ChapterResponse` schema
- [x] 1.6.3 编写 API 测试用例，验证响应格式兼容
- [x] 1.6.4 测试分镜图片生成流程
- [x] 1.6.5 测试视频生成流程
- [x] 1.6.6 测试并发生成场景

## 2. 阶段二：前端 Store 迁移

### 2.1 Store 目录结构创建
- [x] 2.1.1 创建 `stores/` 目录结构
- [x] 2.1.2 创建 `stores/slices/` 子目录

### 2.2 类型定义（types.ts）
- [x] 2.2.1 创建 `stores/slices/types.ts`
- [x] 2.2.2 定义 `Shot`、`Dialogue`、`TaskStatus` 基础类型
- [x] 2.2.3 定义 `DataSliceState` 接口
- [x] 2.2.4 定义 `GenerationSliceState` 接口
- [x] 2.2.5 定义 `UiSliceState` 接口
- [x] 2.2.6 定义 `ChapterGenerateStore` 组合接口

### 2.3 数据 Slice（dataSlice.ts）
- [x] 2.3.1 创建 `stores/slices/dataSlice.ts`
- [x] 2.3.2 实现 `createDataSlice` 函数
- [x] 2.3.3 迁移 `useChapterData` 的章节数据获取逻辑
- [x] 2.3.4 迁移角色/场景/道具数据获取逻辑
- [x] 2.3.5 实现 `fetchShots` 分镜列表获取
- [x] 2.3.6 实现 `updateShot` 分镜更新方法
- [x] 2.3.7 实现 `getCharacterImage`、`getSceneImage`、`getPropImage` 辅助方法

### 2.4 生成 Slice（generationSlice.ts）
- [x] 2.4.1 创建 `stores/slices/generationSlice.ts`
- [x] 2.4.2 实现 `createGenerationSlice` 函数
- [x] 2.4.3 迁移 `useShotGeneration` 图片生成逻辑
- [x] 2.4.4 迁移 `useVideoGeneration` 视频生成逻辑
- [x] 2.4.5 迁移 `useTaskPolling` 任务轮询逻辑
- [x] 2.4.6 迁移 `useTransitionGeneration` 转场生成逻辑
- [x] 2.4.7 迁移 `useAudioGeneration` 音频生成逻辑
- [x] 2.4.8 实现 `generateAllImages`、`generateAllVideos` 批量生成方法

### 2.5 UI Slice（uiSlice.ts）
- [x] 2.5.1 创建 `stores/slices/uiSlice.ts`
- [x] 2.5.2 实现 `createUiSlice` 函数
- [x] 2.5.3 迁移 `useChapterGenerateState` 的 UI 状态管理
- [x] 2.5.4 实现标签页切换 actions
- [x] 2.5.5 实现弹窗状态 actions
- [x] 2.5.6 实现编辑器状态 actions

### 2.6 Store 组合（index.ts）
- [x] 2.6.1 创建 `stores/index.ts`
- [x] 2.6.2 组合所有 Slices 为统一 Store
- [x] 2.6.3 导出 `useChapterGenerateStore` hook

### 2.7 API 客户端更新
- [x] 2.7.1 创建 `src/api/shots.ts` 分镜 API 客户端
- [x] 2.7.2 实现 `getShots()`、`getShot()`、`updateShot()` 方法
- [x] 2.7.3 更新类型定义 `src/types/shot.ts`

### 2.8 Hooks 迁移
- [x] 2.8.1 迁移 `useChapterActions` 逻辑到 Store

### 2.9 组件更新
- [x] 2.9.1 更新 `index.tsx` 使用 Store
- [x] 2.9.2 更新分镜列表组件使用 Store 和新的 Shot API
- [x] 2.9.3 更新 `JsonEditor.tsx` 使用 Store
- [x] 2.9.4 更新 `JsonTableEditor.tsx` 使用 Store
- [x] 2.9.5 更新其他子组件使用 Store

### 2.10 清理废弃代码
- [x] 2.10.1 移除旧的 hooks 文件（确认无引用后）
- [x] 2.10.2 清理 props 传递代码
- [x] 2.10.3 更新类型定义

## 3. 阶段三：UI 重构与清理

### 3.1 标签页布局
- [x] 3.1.1 设计标签页组件结构
- [x] 3.1.2 创建 `TabLayout.tsx` 组件
- [x] 3.1.3 创建"内容准备"标签页内容组件
- [x] 3.1.4 创建"资源库"标签页内容组件
- [x] 3.1.5 创建"分镜制作"标签页内容组件
- [x] 3.1.6 创建"合成导出"标签页内容组件

### 3.2 组件拆分
- [x] 3.2.1 拆分 `index.tsx` 为多个子组件
- [x] 3.2.2 确保每个文件不超过 500 行
- [x] 3.2.3 优化组件导入结构

### 3.3 国际化支持
- [x] 3.3.1 更新 zh-CN 翻译文件添加标签页名称
- [x] 3.3.2 更新 en-US 翻译文件
- [x] 3.3.3 更新 ja-JP 翻译文件
- [x] 3.3.4 更新 ko-KR 翻译文件
- [x] 3.3.5 更新 zh-TW 翻译文件

### 3.4 清理冗余字段
- [x] 3.4.1 创建迁移脚本删除 Chapter 表的冗余列
- [x] 3.4.2 更新 Chapter 模型移除冗余字段定义
- [x] 3.4.3 更新相关 Schema 移除冗余字段

## 4. 测试与验证

### 4.1 功能测试
- [x] 4.1.1 测试章节内容解析流程
- [x] 4.1.2 测试角色/场景/道具资源管理
- [x] 4.1.3 测试分镜图片生成和上传
- [x] 4.1.4 测试视频生成流程
- [x] 4.1.5 测试转场视频和最终合成
- [x] 4.1.6 测试标签页切换和状态保持

### 4.2 并发测试
- [x] 4.2.1 测试同时生成多个分镜图片
- [x] 4.2.2 测试同时生成图片和视频
- [x] 4.2.3 验证无 Lost Update 问题

### 4.3 性能测试
- [x] 4.3.1 验证 Store 状态更新性能
- [x] 4.3.2 验证组件重渲染优化
- [x] 4.3.3 验证大量分镜（>50）的加载性能

### 4.4 兼容性测试
- [x] 4.4.1 测试现有章节数据兼容性
- [x] 4.4.2 测试 API 响应格式兼容性
- [x] 4.4.3 测试数据迁移回滚