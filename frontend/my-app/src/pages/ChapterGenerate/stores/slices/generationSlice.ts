/**
 * 生成功能 Slice - 管理图片生成、视频生成、转场生成、音频生成
 */
import type { StateCreator } from 'zustand';
import type {
  GenerationSliceState,
  ChapterGenerateStore,
  Shot,
  AudioTask,
  AudioWarning,
  DialogueData,
} from './types';
import { shotsApi } from '../../../../api/shots';
import { chapterApi } from '../../../../api/chapters';

export interface GenerationSlice extends GenerationSliceState {
  // ========== 图片生成 ==========
  generateShotImage: (novelId: string, chapterId: string, shotIndex: number) => Promise<void>;
  generateAllImages: (novelId: string, chapterId: string) => Promise<void>;
  uploadShotImage: (novelId: string, chapterId: string, shotIndex: number, file: File) => Promise<void>;
  setShotImages: (images: Record<number, string> | ((prev: Record<number, string>) => Record<number, string>)) => void;

  // ========== 视频生成 ==========
  generateShotVideo: (novelId: string, chapterId: string, shotIndex: number) => Promise<void>;
  generateAllVideos: (novelId: string, chapterId: string) => Promise<void>;
  setShotVideos: (videos: Record<number, string> | ((prev: Record<number, string>) => Record<number, string>)) => void;

  // ========== 转场生成 ==========
  generateTransition: (novelId: string, chapterId: string, fromIndex: number, toIndex: number, useCustomConfig?: boolean) => Promise<void>;
  generateAllTransitions: (novelId: string, chapterId: string) => Promise<void>;
  fetchTransitionWorkflows: () => Promise<void>;
  setSelectedTransitionWorkflow: (workflowId: string) => void;
  setTransitionDuration: (duration: number) => void;

  // ========== 音频生成 ==========
  generateShotAudio: (novelId: string, chapterId: string, shotIndex: number, dialogues: DialogueData[]) => Promise<void>;
  generateAllAudio: (novelId: string, chapterId: string) => Promise<void>;
  regenerateAudio: (novelId: string, chapterId: string, shotIndex: number, characterName: string, dialogue: DialogueData) => Promise<void>;
  uploadDialogueAudio: (novelId: string, chapterId: string, shotIndex: number, characterName: string, file: File) => Promise<void>;
  deleteDialogueAudio: (novelId: string, chapterId: string, shotIndex: number, characterName: string) => Promise<void>;
  getAudioUrl: (shotIndex: number, characterName: string) => string | undefined;
  getAudioSource: (shotIndex: number, characterName: string) => string | undefined;
  isShotAudioGenerating: (shotIndex: number) => boolean;
  isAudioUploading: (shotIndex: number, characterName: string) => boolean;
  getShotAudioTasks: (shotIndex: number) => AudioTask[];
  initAudioFromShots: (shots: Shot[]) => void;

  // ========== 任务轮询 ==========
  checkShotTaskStatus: (chapterId: string) => Promise<void>;
  checkVideoTaskStatus: (chapterId: string) => Promise<void>;
  checkTransitionTaskStatus: (chapterId: string) => Promise<void>;
  checkAudioTaskStatus: (chapterId: string) => Promise<void>;
  fetchActiveTasks: (chapterId: string) => Promise<void>;
}

export const createGenerationSlice: StateCreator<
  ChapterGenerateStore,
  [],
  [],
  GenerationSlice
> = (set, get) => ({
  // ========== 初始状态 ==========
  // 图片生成
  generatingShots: new Set(),
  pendingShots: new Set(),
  shotImages: {},
  isGeneratingAll: false,
  uploadingShotIndex: null,

  // 视频生成
  generatingVideos: new Set(),
  pendingVideos: new Set(),
  shotVideos: {},

  // 转场生成
  transitionVideos: {},
  generatingTransitions: new Set(),
  currentTransition: '',
  transitionWorkflows: [],
  selectedTransitionWorkflow: '',
  transitionDuration: 2,

  // 分镜工作流
  shotWorkflows: [],
  activeShotWorkflow: null,

  // 音频生成
  generatingAudios: new Set(),
  audioWarnings: [],
  audioTasks: [],
  audioUrls: {},
  audioSources: {},
  uploadingAudios: new Set(),

  // ========== 图片生成方法 ==========

  generateShotImage: async (novelId: string, chapterId: string, shotIndex: number) => {
    const shot = get().shots.find(s => s.index === shotIndex);
    if (!shot) return;

    // 添加到生成中集合
    set(state => ({
      generatingShots: new Set([...state.generatingShots, shotIndex])
    }));

    try {
      const result = await shotsApi.generateImage(novelId, chapterId, shotIndex);

      if (result.success) {
        // 更新 shot 的 imageStatus
        const updatedShots = get().shots.map(s =>
          s.index === shotIndex
            ? { ...s, imageStatus: 'generating' as const, imageTaskId: result.data?.taskId || null }
            : s
        );
        set({ shots: updatedShots });
      } else {
        throw new Error(result.message || '生成失败');
      }
    } catch (error) {
      console.error('生成分镜图片失败:', error);
      // 从生成中集合移除
      set(state => {
        const newSet = new Set(state.generatingShots);
        newSet.delete(shotIndex);
        return { generatingShots: newSet };
      });
    }
  },

  generateAllImages: async (novelId: string, chapterId: string) => {
    const { shots } = get();
    const pendingShots = shots.filter(s => s.imageStatus === 'pending');

    if (pendingShots.length === 0) return;

    set({ isGeneratingAll: true });

    // 将所有待处理的分镜添加到 pendingShots 集合
    set(state => ({
      pendingShots: new Set([
        ...state.pendingShots,
        ...pendingShots.map(s => s.index)
      ])
    }));

    // 顺序执行生成
    for (const shot of pendingShots) {
      await get().generateShotImage(novelId, chapterId, shot.index);
    }

    set({ isGeneratingAll: false });
  },

  uploadShotImage: async (novelId: string, chapterId: string, shotIndex: number, file: File) => {
    set({ uploadingShotIndex: shotIndex });

    try {
      const result = await shotsApi.uploadImage(novelId, chapterId, shotIndex, file);

      if (result.success && result.data) {
        // 更新 shotImages
        set(state => ({
          shotImages: { ...state.shotImages, [shotIndex]: result.data?.imageUrl || '' }
        }));

        // 更新 shot 的 imageUrl
        const updatedShots = get().shots.map(s =>
          s.index === shotIndex
            ? { ...s, imageUrl: result.data?.imageUrl || '', imageStatus: 'completed' as const }
            : s
        );
        set({ shots: updatedShots });
      } else {
        throw new Error(result.message || '上传失败');
      }
    } catch (error) {
      console.error('上传分镜图片失败:', error);
      throw error;
    } finally {
      set({ uploadingShotIndex: null });
    }
  },

  setShotImages: (images) => {
    if (typeof images === 'function') {
      set(state => ({ shotImages: images(state.shotImages) }));
    } else {
      set({ shotImages: images });
    }
  },

  // ========== 视频生成方法 ==========

  generateShotVideo: async (novelId: string, chapterId: string, shotIndex: number) => {
    const shot = get().shots.find(s => s.index === shotIndex);
    if (!shot) return;

    set(state => ({
      generatingVideos: new Set([...state.generatingVideos, shotIndex])
    }));

    try {
      const result = await shotsApi.generateVideo(novelId, chapterId, shotIndex);

      if (result.success) {
        const updatedShots = get().shots.map(s =>
          s.index === shotIndex
            ? { ...s, videoStatus: 'generating' as const, videoTaskId: result.data?.taskId || null }
            : s
        );
        set({ shots: updatedShots });
      } else {
        throw new Error(result.message || '生成失败');
      }
    } catch (error) {
      console.error('生成分镜视频失败:', error);
      set(state => {
        const newSet = new Set(state.generatingVideos);
        newSet.delete(shotIndex);
        return { generatingVideos: newSet };
      });
    }
  },

  generateAllVideos: async (novelId: string, chapterId: string) => {
    const { shots } = get();
    const pendingVideos = shots.filter(s => s.videoStatus === 'pending');

    if (pendingVideos.length === 0) return;

    set(state => ({
      pendingVideos: new Set([
        ...state.pendingVideos,
        ...pendingVideos.map(s => s.index)
      ])
    }));

    for (const shot of pendingVideos) {
      await get().generateShotVideo(novelId, chapterId, shot.index);
    }
  },

  setShotVideos: (videos) => {
    if (typeof videos === 'function') {
      set(state => ({ shotVideos: videos(state.shotVideos) }));
    } else {
      set({ shotVideos: videos });
    }
  },

  // ========== 转场生成方法 ==========

  generateTransition: async (novelId, chapterId, fromIndex, toIndex, useCustomConfig = false) => {
    const transitionKey = `${fromIndex}-${toIndex}`;

    set(state => ({
      generatingTransitions: new Set([...state.generatingTransitions, transitionKey])
    }));

    try {
      const { selectedTransitionWorkflow, transitionDuration } = get();

      // 计算 frame_count: 每秒约8帧 + 1（transitionDuration是秒数）
      const frameCount = Math.round(transitionDuration * 8) + 1;

      const response = await fetch(
        `/api/novels/${novelId}/chapters/${chapterId}/transitions`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            from_index: fromIndex,
            to_index: toIndex,
            frame_count: frameCount,
            workflow_id: selectedTransitionWorkflow || undefined,
          }),
        }
      );

      const result = await response.json();

      if (response.ok && result.success) {
        // 任务已启动，状态将通过轮询更新
      } else {
        // 处理 HTTP 错误或业务错误
        const errorMsg = result.detail || result.message || '生成失败';
        throw new Error(errorMsg);
      }
    } catch (error) {
      console.error('生成转场失败:', error);
      set(state => {
        const newSet = new Set(state.generatingTransitions);
        newSet.delete(transitionKey);
        return { generatingTransitions: newSet };
      });
    }
  },

  generateAllTransitions: async (novelId, chapterId) => {
    const { shots } = get();
    if (shots.length < 2) return;

    for (let i = 0; i < shots.length - 1; i++) {
      await get().generateTransition(novelId, chapterId, shots[i].index, shots[i + 1].index);
    }
  },

  fetchTransitionWorkflows: async () => {
    try {
      const response = await fetch('/api/workflows?type=transition');
      const result = await response.json();

      if (result.success) {
        set({
          transitionWorkflows: result.data.map((w: any) => ({
            id: w.id,
            name: w.name,
            isActive: w.is_active,
          })),
        });
      }
    } catch (error) {
      console.error('获取转场工作流失败:', error);
    }
  },

  setSelectedTransitionWorkflow: (workflowId) => {
    set({ selectedTransitionWorkflow: workflowId });
  },

  setTransitionDuration: (duration) => {
    set({ transitionDuration: duration });
  },

  // ========== 音频生成方法 ==========

  generateShotAudio: async (novelId, chapterId, shotIndex, dialogues) => {
    const generatingKey = `${shotIndex}`;
    set(state => ({
      generatingAudios: new Set([...state.generatingAudios, generatingKey])
    }));

    try {
      const result = await chapterApi.generateShotAudio(novelId, chapterId, shotIndex, dialogues);

      if (result.success && result.data) {
        // 更新音频任务
        const newTasks: AudioTask[] = result.data.tasks.map(t => ({
          shotIndex,
          characterName: t.character_name,
          taskId: t.task_id,
          status: t.status as AudioTask['status'],
        }));

        set(state => ({
          audioTasks: [...state.audioTasks, ...newTasks],
          audioWarnings: [...state.audioWarnings, ...(result.data?.warnings || [])]
        }));
      } else {
        throw new Error(result.message || '生成失败');
      }
    } catch (error) {
      console.error('生成音频失败:', error);
    } finally {
      set(state => {
        const newSet = new Set(state.generatingAudios);
        newSet.delete(generatingKey);
        return { generatingAudios: newSet };
      });
    }
  },

  generateAllAudio: async (novelId, chapterId) => {
    try {
      const result = await chapterApi.generateAllAudio(novelId, chapterId);

      if (result.success && result.data) {
        interface TaskResult {
          character_name: string;
          task_id: string;
          status: string;
          shot_index?: number;
        }

        const newTasks: AudioTask[] = (result.data.tasks as TaskResult[]).map(t => ({
          shotIndex: t.shot_index ?? 0,
          characterName: t.character_name,
          taskId: t.task_id,
          status: t.status as AudioTask['status'],
        }));

        set({
          audioTasks: newTasks,
          audioWarnings: result.data.warnings || []
        });
      }
    } catch (error) {
      console.error('批量生成音频失败:', error);
    }
  },

  regenerateAudio: async (novelId, chapterId, shotIndex, characterName, dialogue) => {
    // 删除旧音频并重新生成
    await get().deleteDialogueAudio(novelId, chapterId, shotIndex, characterName);
    await get().generateShotAudio(novelId, chapterId, shotIndex, [dialogue]);
  },

  uploadDialogueAudio: async (novelId, chapterId, shotIndex, characterName, file) => {
    const uploadKey = `${shotIndex}-${characterName}`;
    set(state => ({
      uploadingAudios: new Set([...state.uploadingAudios, uploadKey])
    }));

    try {
      const result = await chapterApi.uploadDialogueAudio(novelId, chapterId, shotIndex, characterName, file);

      if (result.success) {
        // 更新音频 URL
        set(state => ({
          audioUrls: {
            ...state.audioUrls,
            [uploadKey]: result.data?.audio_url || ''
          },
          audioSources: {
            ...state.audioSources,
            [uploadKey]: (result.data?.audio_source as 'ai_generated' | 'uploaded') || 'uploaded'
          }
        }));

        // 更新 shot 的 dialogues
        const updatedShots = get().shots.map(shot => {
          if (shot.index === shotIndex) {
            const updatedDialogues = shot.dialogues.map(d =>
              d.character_name === characterName
                ? { ...d, audio_url: result.data?.audio_url || '', audio_source: (result.data?.audio_source as 'ai_generated' | 'uploaded') || 'uploaded' }
                : d
            );
            return { ...shot, dialogues: updatedDialogues };
          }
          return shot;
        });
        set({ shots: updatedShots });
      } else {
        throw new Error(result.message || '上传失败');
      }
    } catch (error) {
      console.error('上传音频失败:', error);
      throw error;
    } finally {
      set(state => {
        const newSet = new Set(state.uploadingAudios);
        newSet.delete(uploadKey);
        return { uploadingAudios: newSet };
      });
    }
  },

  deleteDialogueAudio: async (novelId, chapterId, shotIndex, characterName) => {
    try {
      const result = await chapterApi.deleteDialogueAudio(novelId, chapterId, shotIndex, characterName);

      if (result.success) {
        const audioKey = `${shotIndex}-${characterName}`;

        // 移除音频 URL
        set(state => {
          const newUrls = { ...state.audioUrls };
          const newSources = { ...state.audioSources };
          delete newUrls[audioKey];
          delete newSources[audioKey];
          return { audioUrls: newUrls, audioSources: newSources };
        });

        // 更新 shot 的 dialogues
        const updatedShots = get().shots.map(shot => {
          if (shot.index === shotIndex) {
            const updatedDialogues = shot.dialogues.map(d => {
              if (d.character_name === characterName) {
                const { audio_url: _, audio_source: __, audio_task_id: ___, ...rest } = d as any;
                return rest;
              }
              return d;
            });
            return { ...shot, dialogues: updatedDialogues };
          }
          return shot;
        });
        set({ shots: updatedShots });
      }
    } catch (error) {
      console.error('删除音频失败:', error);
    }
  },

  getAudioUrl: (shotIndex, characterName) => {
    const audioKey = `${shotIndex}-${characterName}`;
    return get().audioUrls[audioKey];
  },

  getAudioSource: (shotIndex, characterName) => {
    const audioKey = `${shotIndex}-${characterName}`;
    return get().audioSources[audioKey];
  },

  isShotAudioGenerating: (shotIndex) => {
    return get().generatingAudios.has(String(shotIndex));
  },

  isAudioUploading: (shotIndex, characterName) => {
    const uploadKey = `${shotIndex}-${characterName}`;
    return get().uploadingAudios.has(uploadKey);
  },

  getShotAudioTasks: (shotIndex) => {
    return get().audioTasks.filter(t => t.shotIndex === shotIndex);
  },

  initAudioFromShots: (shots) => {
    const audioUrls: Record<string, string> = {};
    const audioSources: Record<string, string> = {};

    shots.forEach(shot => {
      shot.dialogues.forEach(dialogue => {
        if (dialogue.audio_url) {
          const key = `${shot.index}-${dialogue.character_name}`;
          audioUrls[key] = dialogue.audio_url;
          audioSources[key] = dialogue.audio_source || 'ai_generated';
        }
      });
    });

    set({ audioUrls, audioSources });
  },

  // ========== 任务轮询方法 ==========

  checkShotTaskStatus: async (chapterId: string) => {
    try {
      // 使用正确的 API 端点，按章节和类型筛选任务
      const response = await fetch(`/api/tasks/?type=shot_image&chapter_id=${chapterId}`);
      const result = await response.json();

      if (result.success && result.data) {
        const tasks = result.data;

        // 构建 shotIndex -> task 的映射
        const taskMap: Record<number, any> = {};
        tasks.forEach((task: any) => {
          // 从 task.name 中提取镜号，例如 "生成分镜图：镜 1"
          const match = task.name?.match(/镜 (\d+)/);
          if (match) {
            const shotIndex = parseInt(match[1], 10);
            taskMap[shotIndex] = task;
          }
        });

        // 更新 shots 状态和 shotImages 映射
        const { shots, shotImages, generatingShots } = get();
        let shotImagesUpdated = false;
        let generatingShotsUpdated = false;
        const newShotImages = { ...shotImages };
        const newGeneratingShots = new Set(generatingShots);

        const updatedShots = shots.map((shot) => {
          const task = taskMap[shot.index];
          if (task) {
            const isCompleted = task.status === 'completed';
            const isFailed = task.status === 'failed';

            // 如果任务完成且有结果 URL，更新 shotImages
            if (isCompleted && task.result_url) {
              if (newShotImages[shot.index] !== task.result_url) {
                newShotImages[shot.index] = task.result_url;
                shotImagesUpdated = true;
              }
              // 从生成中集合移除
              if (newGeneratingShots.has(shot.index)) {
                newGeneratingShots.delete(shot.index);
                generatingShotsUpdated = true;
              }
            } else if (isFailed) {
              // 任务失败，从生成中集合移除
              if (newGeneratingShots.has(shot.index)) {
                newGeneratingShots.delete(shot.index);
                generatingShotsUpdated = true;
              }
            }

            return {
              ...shot,
              imageStatus: task.status,
              imageUrl: task.result_url || shot.imageUrl,
              imageTaskId: task.id || shot.imageTaskId,
            };
          }
          return shot;
        });

        // 只有当数据真正变化时才更新状态
        if (shotImagesUpdated || generatingShotsUpdated) {
          set({
            shots: updatedShots,
            shotImages: newShotImages,
            generatingShots: newGeneratingShots
          });
        } else {
          set({ shots: updatedShots });
        }
      }
    } catch (error) {
      console.error('检查图片任务状态失败:', error);
    }
  },

  checkVideoTaskStatus: async (chapterId: string) => {
    try {
      const response = await fetch(`/api/tasks/?chapter_id=${chapterId}&type=shot_video`);
      const result = await response.json();

      if (result.success && result.data) {
        // 构建 shotIndex -> task 的映射
        const taskMap: Record<number, any> = {};
        result.data.forEach((task: any) => {
          // 从 task.name 中提取镜号，例如 "生成分镜视频：镜 1"
          const match = task.name?.match(/镜 (\d+)/);
          if (match) {
            const shotIndex = parseInt(match[1], 10);
            taskMap[shotIndex] = task;
          }
        });

        const updatedShots = get().shots.map(shot => {
          const task = taskMap[shot.index];
          if (task) {
            return {
              ...shot,
              videoStatus: task.status,
              videoUrl: task.resultUrl || shot.videoUrl,
              videoTaskId: task.id || shot.videoTaskId,
            };
          }
          return shot;
        });
        set({ shots: updatedShots });
      }
    } catch (error) {
      console.error('检查视频任务状态失败:', error);
    }
  },

  checkTransitionTaskStatus: async (chapterId: string) => {
    try {
      const response = await fetch(`/api/tasks/?chapter_id=${chapterId}&type=transition`);
      const result = await response.json();

      if (result.success && result.data) {
        // 更新转场视频状态
        const newTransitionVideos = { ...get().transitionVideos };
        result.data.forEach((task: any) => {
          if (task.resultUrl) {
            // 从 task.name 中提取转场 key，例如 "转场视频：1-2"
            const match = task.name?.match(/(\d+)-(\d+)/);
            if (match) {
              const transitionKey = `${match[1]}-${match[2]}`;
              newTransitionVideos[transitionKey] = task.resultUrl;
            }
          }
        });
        set({ transitionVideos: newTransitionVideos });
      }
    } catch (error) {
      console.error('检查转场任务状态失败:', error);
    }
  },

  checkAudioTaskStatus: async (chapterId: string) => {
    try {
      const response = await fetch(`/api/tasks/?chapter_id=${chapterId}&type=audio`);
      const result = await response.json();

      if (result.success && result.data) {
        // 更新音频任务状态
        const updatedTasks = get().audioTasks.map(task => {
          const taskStatus = result.data.find((t: any) => t.id === task.taskId);
          if (taskStatus) {
            return { ...task, status: taskStatus.status };
          }
          return task;
        });
        set({ audioTasks: updatedTasks });

        // 更新音频 URL - 从任务名称提取信息
        const newAudioUrls = { ...get().audioUrls };
        result.data.forEach((task: any) => {
          if (task.resultUrl) {
            // 从任务名称提取镜号和角色名，例如 "音频生成：镜 1 - 角色"
            const match = task.name?.match(/镜 (\d+).*-\s*(.+)/);
            if (match) {
              const key = `${match[1]}-${match[2].trim()}`;
              newAudioUrls[key] = task.resultUrl;
            }
          }
        });
        set({ audioUrls: newAudioUrls });
      }
    } catch (error) {
      console.error('检查音频任务状态失败:', error);
    }
  },

  fetchActiveTasks: async (chapterId: string) => {
    // 获取所有活跃任务
    await Promise.all([
      get().checkShotTaskStatus(chapterId),
      get().checkVideoTaskStatus(chapterId),
      get().checkTransitionTaskStatus(chapterId),
      get().checkAudioTaskStatus(chapterId),
    ]);
  },
});
