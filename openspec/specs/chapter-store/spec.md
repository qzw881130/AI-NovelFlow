## ADDED Requirements

### Requirement: Zustand Store Slice 模式架构

系统 SHALL 使用 Zustand Slice 模式管理 ChapterGenerate 页面的所有状态，确保单个文件不超过 500 行。

#### Scenario: Store 按 Slice 拆分
- **WHEN** 创建 Store 文件
- **THEN** Store SHALL 按 Slice 模式拆分为多个模块
- **AND** 每个 Slice 文件 SHALL 不超过 500 行
- **AND** 所有 Slices SHALL 组合为统一的 `useChapterGenerateStore`

#### Scenario: Slice 文件结构
- **WHEN** 组织 Store 代码
- **THEN** 文件结构 SHALL 如下：
```
stores/
├── index.ts              # 组合所有 slices，导出统一 Store
├── slices/
│   ├── dataSlice.ts      # 数据状态：chapter, novel, shots, characters 等
│   ├── generationSlice.ts # 生成逻辑：图片/视频生成、任务轮询
│   ├── uiSlice.ts        # UI 状态：activeTab, selectedShot 等
│   └── types.ts          # 类型定义
```

#### Scenario: Slice 组合
- **WHEN** 组件导入 Store
- **THEN** 组件 SHALL 使用 `useChapterGenerateStore()` 访问所有状态
- **AND** 组件 SHALL NOT 需要了解 Slice 的内部拆分

### Requirement: Store 管理章节数据（dataSlice）

dataSlice SHALL 管理所有数据相关的状态和操作。

#### Scenario: Store 管理章节数据
- **WHEN** 组件需要访问章节数据
- **THEN** 组件 SHALL 通过 `useChapterGenerateStore()` 访问 `chapter`、`novel`、`parsedData` 状态
- **AND** 组件 SHALL 通过 Store actions 更新数据

#### Scenario: Store 管理分镜数据
- **WHEN** 组件需要访问分镜数据
- **THEN** 组件 SHALL 通过 Store 访问 `shots` 数组（从独立 Shot API 获取）
- **AND** 每个 Shot 对象 SHALL 包含 id、description、image_url、video_url 等字段

#### Scenario: Store 管理资源数据
- **WHEN** 组件需要访问角色/场景/道具数据
- **THEN** 组件 SHALL 通过 Store 访问 `characters`、`scenes`、`props` 数组
- **AND** Store SHALL 提供 `getCharacterImage`、`getSceneImage`、`getPropImage` 辅助方法

### Requirement: Store 管理生成状态（generationSlice）

generationSlice SHALL 管理所有生成相关的状态和异步操作。

#### Scenario: Store 管理生成状态
- **WHEN** 用户触发生成操作
- **THEN** 生成状态 SHALL 通过 Store 的 `generatingShots`、`pendingTasks` 等状态管理
- **AND** 状态变更 SHALL 自动触发相关组件重渲染

#### Scenario: 异步获取章节数据
- **WHEN** 调用 Store 的 `fetchChapterData` action
- **THEN** action SHALL 异步获取章节数据并更新 Store 状态
- **AND** loading 状态 SHALL 在请求期间正确设置

#### Scenario: 异步获取分镜列表
- **WHEN** 调用 Store 的 `fetchShots` action
- **THEN** action SHALL 调用 Shot API 获取分镜列表
- **AND** 分镜数据 SHALL 按 index 排序存储

#### Scenario: 异步生成操作
- **WHEN** 调用 Store 的 `generateShotImage` 或 `generateShotVideo` action
- **THEN** action SHALL 异步触发生成并轮询任务状态
- **AND** 生成状态 SHALL 实时更新到 Store

#### Scenario: 更新单个分镜
- **WHEN** 调用 Store 的 `updateShot` action
- **THEN** action SHALL 更新指定分镜的数据
- **AND** 其他分镜状态 SHALL 保持不变

### Requirement: Store 管理 UI 状态（uiSlice）

uiSlice SHALL 管理所有 UI 相关的状态。

#### Scenario: Store 管理 UI 状态
- **WHEN** 用户切换标签页或导航分镜
- **THEN** UI 状态 SHALL 通过 Store 的 `activeTab`、`selectedShotIndex` 等状态管理
- **AND** 状态在组件间自动同步

#### Scenario: 弹窗状态管理
- **WHEN** 组件需要显示/隐藏弹窗
- **THEN** 弹窗状态 SHALL 通过 Store 的 `showFullTextModal`、`showImagePreview` 等状态管理
- **AND** 弹窗状态 SHALL 在组件间共享

### Requirement: 组件独立订阅状态切片

系统 SHALL 允许组件只订阅需要的状态切片，避免不必要的重渲染。

#### Scenario: 组件选择性订阅
- **WHEN** 组件只需要 `activeTab` 状态
- **THEN** 组件 SHALL 使用 selector 只订阅 `activeTab`
- **AND** 其他状态变更 SHALL NOT 触发该组件重渲染

#### Scenario: 状态变更精确更新
- **WHEN** Store 中只有 `selectedShotIndex` 状态变更
- **THEN** 只有订阅了 `selectedShotIndex` 的组件 SHALL 重渲染
- **AND** 其他组件 SHALL NOT 重渲染

#### Scenario: 分镜状态独立更新
- **WHEN** 分镜 A 的图片生成完成
- **THEN** 只有订阅了分镜 A 状态的组件 SHALL 重渲染
- **AND** 其他分镜相关组件 SHALL NOT 重渲染

### Requirement: Store 类型定义

系统 SHALL 定义完整的 TypeScript 类型，类型定义集中在 `slices/types.ts`。

```typescript
// slices/types.ts

// 基础类型
interface Dialogue {
  characterName: string;
  text: string;
  audioUrl: string | null;
  audioSource: 'generated' | 'uploaded' | null;
  audioTaskId: string | null;
}

interface Shot {
  id: string;
  chapterId: string;
  index: number;
  description: string;
  characters: string[];
  scene: string;
  props: string[];
  duration: number;
  imageUrl: string | null;
  imagePath: string | null;
  imageStatus: 'pending' | 'generating' | 'completed' | 'failed';
  imageTaskId: string | null;
  videoUrl: string | null;
  videoStatus: 'pending' | 'generating' | 'completed' | 'failed';
  videoTaskId: string | null;
  mergedCharacterImage: string | null;
  dialogues: Dialogue[];
}

type TabType = 'prepare' | 'resources' | 'shots' | 'compose';

interface TaskStatus {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  result?: any;
}

// Slice State Types
interface DataSliceState {
  chapter: Chapter | null;
  novel: Novel | null;
  parsedData: ParsedData | null;
  shots: Shot[];
  characters: Character[];
  scenes: Scene[];
  props: Prop[];
  editableJson: string;
  loading: boolean;
}

interface GenerationSliceState {
  generatingShots: Set<string>;
  generatingVideos: Set<string>;
  pendingTasks: Map<string, TaskStatus>;
  isSplitting: boolean;
  isSavingJson: boolean;
}

interface UiSliceState {
  activeTab: TabType;
  selectedShotIndex: number;
  currentVideo: number;
  jsonEditMode: 'text' | 'table';
  editorKey: number;
  showFullTextModal: boolean;
  showMergedImageModal: boolean;
  showImagePreview: boolean;
  previewImageUrl: string | null;
  previewImageIndex: number;
  mergedImage: string | null;
  isMerging: boolean;
  splitConfirmDialog: { isOpen: boolean; hasResources: boolean };
  showTransitionConfig: boolean;
}

// 完整 Store 类型（组合所有 Slices）
interface ChapterGenerateStore extends DataSliceState, GenerationSliceState, UiSliceState {
  // DataSlice Actions
  fetchChapterData: (novelId: string, chapterId: string) => Promise<void>;
  fetchShots: (chapterId: string) => Promise<void>;
  fetchCharacters: (novelId: string) => Promise<void>;
  fetchScenes: (novelId: string) => Promise<void>;
  fetchProps: (novelId: string) => Promise<void>;
  getCharacterImage: (name: string) => string | undefined;
  getSceneImage: (name: string) => string | null;
  getPropImage: (name: string) => string | null;
  setParsedData: (data: ParsedData | null) => void;
  setEditableJson: (json: string) => void;
  updateShot: (shotId: string, data: Partial<Shot>) => void;

  // GenerationSlice Actions
  generateShotImage: (shotId: string) => Promise<void>;
  generateShotVideo: (shotId: string) => Promise<void>;
  generateAllImages: () => Promise<void>;
  generateAllVideos: () => Promise<void>;
  pollTaskStatus: (taskId: string, type: 'image' | 'video', shotId: string) => Promise<void>;

  // UiSlice Actions
  setActiveTab: (tab: TabType) => void;
  setSelectedShotIndex: (index: number) => void;
  setCurrentVideo: (index: number) => void;
  setJsonEditMode: (mode: 'text' | 'table') => void;
  resetEditorKey: () => void;
  setShowFullTextModal: (show: boolean) => void;
  setShowMergedImageModal: (show: boolean) => void;
  setShowImagePreview: (show: boolean, url?: string | null, index?: number) => void;
  setMergedImage: (image: string | null) => void;
  setIsMerging: (merging: boolean) => void;
  setSplitConfirmDialog: (dialog: { isOpen: boolean; hasResources: boolean }) => void;
  setShowTransitionConfig: (show: boolean) => void;
}
```

### Requirement: Slice 组合实现

系统 SHALL 在 `stores/index.ts` 中组合所有 Slices。

```typescript
// stores/index.ts
import { create } from 'zustand';
import { createDataSlice } from './slices/dataSlice';
import { createGenerationSlice } from './slices/generationSlice';
import { createUiSlice } from './slices/uiSlice';
import type { ChapterGenerateStore } from './slices/types';

export const useChapterGenerateStore = create<ChapterGenerateStore>((...a) => ({
  ...createDataSlice(...a),
  ...createGenerationSlice(...a),
  ...createUiSlice(...a),
}));
```

### Requirement: 各 Slice 文件大小限制

系统 SHALL 确保每个 Slice 文件符合项目规范。

| 文件 | 预计行数 | 职责 |
|------|----------|------|
| types.ts | ~100 行 | 类型定义 |
| dataSlice.ts | ~300 行 | 数据状态与获取 |
| generationSlice.ts | ~400 行 | 生成逻辑与任务轮询 |
| uiSlice.ts | ~150 行 | UI 状态管理 |
| index.ts | ~20 行 | Store 组合导出 |
| **总计** | **~970 行** | 符合规范（单文件 ≤1000 行） |