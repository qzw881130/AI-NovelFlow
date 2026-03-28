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
  KeyframeTask,
  ReferenceAudioMergeTask,
} from './types';
import { shotsApi } from '../../../../api/shots';
import { chapterApi } from '../../../../api/chapters';

export interface GenerationSlice extends GenerationSliceState {
  // ========== 图片生成 ==========
  generateShotImage: (novelId: string, chapterId: string, shotId: string) => Promise<void>;
  generateAllImages: (novelId: string, chapterId: string) => Promise<void>;
  uploadShotImage: (novelId: string, chapterId: string, shotId: string, file: File) => Promise<void>;
  setShotImages: (images: Record<string, string> | ((prev: Record<string, string>) => Record<string, string>)) => void;

  // ========== 视频生成 ==========
  generateShotVideo: (novelId: string, chapterId: string, shotId: string) => Promise<void>;
  generateAllVideos: (novelId: string, chapterId: string) => Promise<void>;
  setShotVideos: (videos: Record<string, string> | ((prev: Record<string, string>) => Record<string, string>)) => void;

  // ========== 转场生成 ==========
  generateTransition: (novelId: string, chapterId: string, fromIndex: number, toIndex: number, useCustomConfig?: boolean) => Promise<void>;
  generateAllTransitions: (novelId: string, chapterId: string) => Promise<void>;
  fetchTransitionWorkflows: () => Promise<void>;
  setSelectedTransitionWorkflow: (workflowId: string) => void;
  setTransitionDuration: (duration: number) => void;

  // ========== 音频生成 ==========
  generateShotAudio: (novelId: string, chapterId: string, shotId: string, dialogues: DialogueData[]) => Promise<void>;
  generateAllAudio: (novelId: string, chapterId: string) => Promise<void>;
  regenerateAudio: (novelId: string, chapterId: string, shotId: string, characterName: string, dialogue: DialogueData) => Promise<void>;
  uploadDialogueAudio: (novelId: string, chapterId: string, shotId: string, characterName: string, file: File) => Promise<void>;
  deleteDialogueAudio: (novelId: string, chapterId: string, shotId: string, characterName: string) => Promise<void>;
  getAudioUrl: (shotId: string, characterName: string) => string | undefined;
  getAudioSource: (shotId: string, characterName: string) => string | undefined;
  isShotAudioGenerating: (shotId: string) => boolean;
  isAudioUploading: (shotId: string, characterName: string) => boolean;
  getShotAudioTasks: (shotId: string) => AudioTask[];
  initAudioFromShots: (shots: Shot[]) => void;

  // ========== 任务轮询 ==========
  checkShotTaskStatus: (chapterId: string) => Promise<void>;
  checkVideoTaskStatus: (chapterId: string) => Promise<void>;
  checkTransitionTaskStatus: (chapterId: string) => Promise<void>;
  checkAudioTaskStatus: (chapterId: string) => Promise<void>;
  checkKeyframeTaskStatus: (chapterId: string) => Promise<void>;
  fetchActiveTasks: (chapterId: string) => Promise<void>;

  // ========== 关键帧生成 ==========
  generateKeyframeDescriptions: (novelId: string, chapterId: string, shotId: string, count?: number) => Promise<void>;
  generateKeyframeImage: (novelId: string, chapterId: string, shotId: string, frameIndex: number, workflowId?: string) => Promise<void>;
  uploadKeyframeImage: (novelId: string, chapterId: string, shotId: string, frameIndex: number, file: File) => Promise<void>;
  uploadKeyframeReferenceImage: (novelId: string, chapterId: string, shotId: string, frameIndex: number, file: File) => Promise<void>;
  setKeyframeReferenceImage: (novelId: string, chapterId: string, shotId: string, frameIndex: number, mode: 'auto_select' | 'custom' | 'none', referenceUrl?: string) => Promise<void>;
  isKeyframeGenerating: (shotId: string, frameIndex: number) => boolean;
  getKeyframeImageUrl: (shotId: string, frameIndex: number) => string | undefined;
  getKeyframeTask: (shotId: string, frameIndex: number) => KeyframeTask | undefined;

  // ========== 参考音频 ==========
  mergeDialogueAudio: (novelId: string, chapterId: string, shotId: string) => Promise<void>;
  uploadReferenceAudio: (novelId: string, chapterId: string, shotId: string, file: File) => Promise<void>;
  setReferenceAudio: (novelId: string, chapterId: string, shotId: string, mode: 'none' | 'merged' | 'uploaded' | 'character', characterName?: string) => Promise<void>;
  getReferenceAudioUrl: (shotId: string) => string | undefined;
  inferReferenceAudioSourceType: (shotId: string) => 'none' | 'merged' | 'uploaded' | 'character';
  isReferenceAudioMerging: (shotId: string) => boolean;
  isReferenceAudioUploading: (shotId: string) => boolean;
}

export const createGenerationSlice: StateCreator<
  ChapterGenerateStore,
  [],
  [],
  GenerationSlice
> = (set, get) => ({
  // ========== 初始状态 ==========
  // 图片生成
  generatingShots: new Set<string>(),
  pendingShots: new Set<string>(),
  shotImages: {},
  isGeneratingAll: false,
  uploadingShotId: null,

  // 视频生成
  generatingVideos: new Set<string>(),
  pendingVideos: new Set<string>(),
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

  // 关键帧生成
  generatingKeyframes: new Set(),
  keyframeTasks: [],
  keyframeImageUrls: {},

  // 参考音频
  mergingReferenceAudios: new Set<string>(),
  uploadingReferenceAudios: new Set<string>(),
  referenceAudioMergeTasks: [],

  // ========== 图片生成方法 ==========

  generateShotImage: async (novelId: string, chapterId: string, shotId: string) => {
    const shot = get().shots.find(s => s.id === shotId);
    if (!shot) {
      console.error('[generateShotImage] Shot not found:', shotId);
      return;
    }

    // 添加到生成中集合
    console.log('[generateShotImage] Adding to generatingShots:', shotId);
    set(state => ({
      generatingShots: new Set([...state.generatingShots, shotId])
    }));

    // 验证状态已更新
    console.log('[generateShotImage] generatingShots after update:', [...get().generatingShots]);

    try {
      const result = await shotsApi.generateImage(novelId, chapterId, shotId);
      console.log('[generateShotImage] API result:', result);

      if (result.success) {
        // 更新 shot 的 imageStatus
        const updatedShots = get().shots.map(s =>
          s.id === shotId
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
        newSet.delete(shotId);
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
        ...pendingShots.map(s => s.id)
      ])
    }));

    // 顺序执行生成
    for (const shot of pendingShots) {
      await get().generateShotImage(novelId, chapterId, shot.id);
    }

    set({ isGeneratingAll: false });
  },

  uploadShotImage: async (novelId: string, chapterId: string, shotId: string, file: File) => {
    set({ uploadingShotId: shotId });

    try {
      const result = await shotsApi.uploadImage(novelId, chapterId, shotId, file);

      if (result.success && result.data) {
        // 更新 shotImages
        set(state => ({
          shotImages: { ...state.shotImages, [shotId]: result.data?.imageUrl || '' }
        }));

        // 更新 shot 的 imageUrl
        const updatedShots = get().shots.map(s =>
          s.id === shotId
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
      set({ uploadingShotId: null });
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

  generateShotVideo: async (novelId: string, chapterId: string, shotId: string) => {
    const shot = get().shots.find(s => s.id === shotId);
    if (!shot) return;

    set(state => ({
      generatingVideos: new Set([...state.generatingVideos, shotId])
    }));

    try {
      const result = await shotsApi.generateVideo(novelId, chapterId, shotId);

      if (result.success) {
        const updatedShots = get().shots.map(s =>
          s.id === shotId
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
        newSet.delete(shotId);
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
        ...pendingVideos.map(s => s.id)
      ])
    }));

    for (const shot of pendingVideos) {
      await get().generateShotVideo(novelId, chapterId, shot.id);
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

  generateShotAudio: async (novelId, chapterId, shotId, dialogues) => {
    const shot = get().shots.find(s => s.id === shotId);
    if (!shot) return;

    // 为每个角色生成 key
    const generatingKeys = dialogues.map(d => `${shotId}-${d.character_name}`);
    set(state => ({
      generatingAudios: new Set([...state.generatingAudios, ...generatingKeys])
    }));

    try {
      const result = await shotsApi.generateAudio(novelId, chapterId, shotId, dialogues);

      if (result.success && result.data) {
        // 更新音频任务
        const newTasks: AudioTask[] = result.data.tasks.map((t: any) => ({
          shotId,
          characterName: t.character_name,
          taskId: t.task_id,
          status: t.status as AudioTask['status'],
        }));

        set(state => ({
          audioTasks: [...state.audioTasks, ...newTasks],
          audioWarnings: [...state.audioWarnings, ...(result.data?.warnings || [])]
        }));
      } else {
        // 任务提交失败，清除 generating 状态
        set(state => {
          const newSet = new Set(state.generatingAudios);
          generatingKeys.forEach(key => newSet.delete(key));
          return { generatingAudios: newSet };
        });
        throw new Error(result.message || '生成失败');
      }
    } catch (error) {
      console.error('生成音频失败:', error);
      // 出错时清除 generating 状态
      set(state => {
        const newSet = new Set(state.generatingAudios);
        generatingKeys.forEach(key => newSet.delete(key));
        return { generatingAudios: newSet };
      });
    }
    // 注意：成功提交任务后不清除 generating 状态，等待轮询更新
  },

  generateAllAudio: async (novelId, chapterId) => {
    try {
      const result = await shotsApi.generateAllAudio(novelId, chapterId);

      if (result.success && result.data) {
        interface TaskResult {
          character_name: string;
          task_id: string;
          status: string;
          shot_id?: string;
        }

        const newTasks: AudioTask[] = (result.data.tasks as TaskResult[]).map(t => ({
          shotId: t.shot_id ?? '',
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

  regenerateAudio: async (novelId, chapterId, shotId, characterName, dialogue) => {
    // 删除旧音频并重新生成
    await get().deleteDialogueAudio(novelId, chapterId, shotId, characterName);
    await get().generateShotAudio(novelId, chapterId, shotId, [dialogue]);
  },

  uploadDialogueAudio: async (novelId, chapterId, shotId, characterName, file) => {
    const uploadKey = `${shotId}-${characterName}`;
    set(state => ({
      uploadingAudios: new Set([...state.uploadingAudios, uploadKey])
    }));

    try {
      const result = await shotsApi.uploadDialogueAudio(novelId, chapterId, shotId, characterName, file);

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
          if (shot.id === shotId) {
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

  deleteDialogueAudio: async (novelId, chapterId, shotId, characterName) => {
    try {
      const result = await shotsApi.deleteDialogueAudio(novelId, chapterId, shotId, characterName);

      if (result.success) {
        const audioKey = `${shotId}-${characterName}`;

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
          if (shot.id === shotId) {
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

  getAudioUrl: (shotId, characterName) => {
    const audioKey = `${shotId}-${characterName}`;
    return get().audioUrls[audioKey];
  },

  getAudioSource: (shotId, characterName) => {
    const audioKey = `${shotId}-${characterName}`;
    return get().audioSources[audioKey];
  },

  isShotAudioGenerating: (shotId) => {
    return get().generatingAudios.has(String(shotId));
  },

  isAudioUploading: (shotId, characterName) => {
    const uploadKey = `${shotId}-${characterName}`;
    return get().uploadingAudios.has(uploadKey);
  },

  getShotAudioTasks: (shotId) => {
    return get().audioTasks.filter(t => t.shotId === shotId);
  },

  initAudioFromShots: (shots) => {
    const audioUrls: Record<string, string> = {};
    const audioSources: Record<string, string> = {};

    shots.forEach(shot => {
      shot.dialogues.forEach(dialogue => {
        if (dialogue.audio_url) {
          const key = `${shot.id}-${dialogue.character_name}`;
          audioUrls[key] = dialogue.audio_url;
          audioSources[key] = dialogue.audio_source || 'ai_generated';
        }
      });
    });

    set({ audioUrls, audioSources });
  },

  // ========== 任务轮询方法 ==========

  checkShotTaskStatus: async (chapterId: string) => {
    console.log('[checkShotTaskStatus] Start, current generatingShots:', [...get().generatingShots]);
    try {
      // 使用正确的 API 端点，按章节和类型筛选任务
      const response = await fetch(`/api/tasks/?type=shot_image&chapter_id=${chapterId}`);
      const result = await response.json();

      console.log('[checkShotTaskStatus] API result:', result.data?.length, 'tasks');

      if (result.success && result.data) {
        const tasks = result.data;

        // 构建 shotId -> tasks[] 的映射（同一个 shotId 可能有多个任务）
        const tasksByShotId: Record<string, any[]> = {};
        tasks.forEach((task: any) => {
          console.log('[checkShotTaskStatus] Task:', task.id, 'shotId:', task.shotId, 'status:', task.status);
          // 优先使用 task.shotId 字段（后端返回驼峰格式）
          if (task.shotId) {
            if (!tasksByShotId[task.shotId]) {
              tasksByShotId[task.shotId] = [];
            }
            tasksByShotId[task.shotId].push(task);
          } else {
            // 兼容旧逻辑：从 task.name 中提取镜号，然后查找对应的 shot
            const match = task.name?.match(/镜\s*(\d+)/);
            if (match) {
              const shotIndex = parseInt(match[1], 10);
              const shot = get().shots.find(s => s.index === shotIndex);
              if (shot) {
                if (!tasksByShotId[shot.id]) {
                  tasksByShotId[shot.id] = [];
                }
                tasksByShotId[shot.id].push(task);
              }
            }
          }
        });

        console.log('[checkShotTaskStatus] tasksByShotId keys:', Object.keys(tasksByShotId));

        // 更新 shots 状态和 shotImages 映射
        const { shots, shotImages, generatingShots } = get();
        let shotImagesUpdated = false;
        let generatingShotsUpdated = false;
        const newShotImages = { ...shotImages };
        const newGeneratingShots = new Set(generatingShots);

        const updatedShots = shots.map((shot) => {
          const shotTasks = tasksByShotId[shot.id];
          if (shotTasks && shotTasks.length > 0) {
            // 找到最新的任务（按创建时间排序，取最新的）
            const sortedTasks = [...shotTasks].sort((a, b) =>
              new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
            );
            const latestTask = sortedTasks[0];

            // 检查是否有任何任务正在运行
            const hasRunningTask = shotTasks.some(t => t.status === 'running' || t.status === 'pending');

            // 如果有任务正在运行，确保在 generatingShots 中
            if (hasRunningTask && !newGeneratingShots.has(shot.id)) {
              newGeneratingShots.add(shot.id);
              generatingShotsUpdated = true;
            }

            // 如果没有任何务正在运行，从 generatingShots 中移除
            if (!hasRunningTask && newGeneratingShots.has(shot.id)) {
              newGeneratingShots.delete(shot.id);
              generatingShotsUpdated = true;
            }

            // 使用最新任务的结果 URL（优先使用已完成的任务）
            const completedTask = sortedTasks.find(t => t.status === 'completed' && t.resultUrl);
            if (completedTask && completedTask.resultUrl) {
              if (newShotImages[shot.id] !== completedTask.resultUrl) {
                newShotImages[shot.id] = completedTask.resultUrl;
                shotImagesUpdated = true;
              }
            }

            return {
              ...shot,
              imageStatus: latestTask.status,
              imageUrl: completedTask?.resultUrl || shot.imageUrl,
              imageTaskId: latestTask.id || shot.imageTaskId,
            };
          }
          return shot;
        });

        // 只有当数据真正变化时才更新状态
        console.log('[checkShotTaskStatus] shotImagesUpdated:', shotImagesUpdated, 'generatingShotsUpdated:', generatingShotsUpdated);
        console.log('[checkShotTaskStatus] newGeneratingShots:', [...newGeneratingShots]);
        if (shotImagesUpdated || generatingShotsUpdated) {
          set({
            shots: updatedShots,
            shotImages: newShotImages,
            generatingShots: newGeneratingShots
          });
          console.log('[checkShotTaskStatus] State updated with newGeneratingShots');
        } else {
          set({ shots: updatedShots });
          console.log('[checkShotTaskStatus] Only shots updated');
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
        // 构建 shotId -> task 的映射（优先使用 shotId 字段）
        const taskMap: Record<string, any> = {};
        result.data.forEach((task: any) => {
          // 优先使用 task.shotId 字段（后端返回驼峰格式）
          if (task.shotId) {
            taskMap[task.shotId] = task;
          } else {
            // 兼容旧逻辑：从 task.name 中提取镜号
            const match = task.name?.match(/镜\s*(\d+)/);
            if (match) {
              const shotIndex = parseInt(match[1], 10);
              const shot = get().shots.find(s => s.index === shotIndex);
              if (shot) {
                taskMap[shot.id] = task;
              }
            }
          }
        });

        const { shots, shotVideos, generatingVideos } = get();
        let shotVideosUpdated = false;
        let generatingVideosUpdated = false;
        const newShotVideos = { ...shotVideos };
        const newGeneratingVideos = new Set(generatingVideos);

        const updatedShots = shots.map(shot => {
          const task = taskMap[shot.id];
          if (task) {
            const isCompleted = task.status === 'completed';
            const isFailed = task.status === 'failed';
            const isRunning = task.status === 'running' || task.status === 'pending';

            // 如果任务正在运行，确保在 generatingVideos 中
            if (isRunning && !newGeneratingVideos.has(shot.id)) {
              newGeneratingVideos.add(shot.id);
              generatingVideosUpdated = true;
            }

            if (isCompleted && task.resultUrl) {
              if (newShotVideos[shot.id] !== task.resultUrl) {
                newShotVideos[shot.id] = task.resultUrl;
                shotVideosUpdated = true;
              }
              // 从生成中集合移除（使用 shotId）
              if (newGeneratingVideos.has(shot.id)) {
                newGeneratingVideos.delete(shot.id);
                generatingVideosUpdated = true;
              }
            } else if (isFailed) {
              if (newGeneratingVideos.has(shot.id)) {
                newGeneratingVideos.delete(shot.id);
                generatingVideosUpdated = true;
              }
            }

            return {
              ...shot,
              videoStatus: task.status,
              videoUrl: task.resultUrl || shot.videoUrl,
              videoTaskId: task.id || shot.videoTaskId,
            };
          }
          return shot;
        });

        if (shotVideosUpdated || generatingVideosUpdated) {
          set({
            shots: updatedShots,
            shotVideos: newShotVideos,
            generatingVideos: newGeneratingVideos
          });
        } else {
          set({ shots: updatedShots });
        }
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
      // 音频任务类型包括 character_audio 和 narrator_audio
      const [characterAudioRes, narratorAudioRes] = await Promise.all([
        fetch(`/api/tasks/?chapter_id=${chapterId}&type=character_audio`),
        fetch(`/api/tasks/?chapter_id=${chapterId}&type=narrator_audio`)
      ]);

      const [characterResult, narratorResult] = await Promise.all([
        characterAudioRes.json(),
        narratorAudioRes.json()
      ]);

      // 合并两种类型的任务数据
      const allTasks = [
        ...(characterResult.success && characterResult.data ? characterResult.data : []),
        ...(narratorResult.success && narratorResult.data ? narratorResult.data : [])
      ];

      if (allTasks.length > 0) {
        // 更新音频任务状态
        const updatedTasks = get().audioTasks.map(task => {
          const taskStatus = allTasks.find((t: any) => t.id === task.taskId);
          if (taskStatus) {
            return { ...task, status: taskStatus.status };
          }
          return task;
        });
        set({ audioTasks: updatedTasks });

        // 更新音频 URL 和清除完成的 generating 状态
        const newAudioUrls = { ...get().audioUrls };
        const completedKeys: string[] = [];

        allTasks.forEach((task: any) => {
          // 从任务名称提取角色名
          const nameMatch = task.name?.match(/-\s*(.+)$/);
          const characterName = nameMatch ? nameMatch[1].trim() : '';

          // 使用 shotId 或从任务名称提取镜号
          let key = '';
          if (task.shotId && characterName) {
            key = `${task.shotId}-${characterName}`;
          } else if (characterName) {
            // 从任务名称提取镜号：镜1-角色名
            const indexMatch = task.name?.match(/镜\s*(\d+)/);
            if (indexMatch) {
              key = `${indexMatch[1]}-${characterName}`;
            }
          }

          if (key) {
            // 更新音频 URL
            if (task.resultUrl) {
              newAudioUrls[key] = task.resultUrl;
            }

            // 任务完成或失败时清除 generating 状态
            if (task.status === 'completed' || task.status === 'failed') {
              completedKeys.push(key);
            }
          }
        });
        set({ audioUrls: newAudioUrls });

        // 清除已完成任务的 generating 状态
        if (completedKeys.length > 0) {
          console.log('[checkAudioTaskStatus] Clearing completed keys:', completedKeys);
          set(state => {
            const newSet = new Set(state.generatingAudios);
            completedKeys.forEach(key => newSet.delete(key));
            return { generatingAudios: newSet };
          });
        }
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
      get().checkKeyframeTaskStatus(chapterId),
    ]);
  },

  checkKeyframeTaskStatus: async (chapterId: string) => {
    try {
      const response = await fetch(`/api/tasks/?chapter_id=${chapterId}&type=keyframe_image`);
      const result = await response.json();

      if (result.success && result.data) {
        // 更新关键帧任务状态和图片URL
        const { keyframeTasks, generatingKeyframes, keyframeImageUrls, shots } = get();
        let keyframeTasksUpdated = false;
        let generatingKeyframesUpdated = false;
        let keyframeImageUrlsUpdated = false;
        const newKeyframeTasks = [...keyframeTasks];
        const newGeneratingKeyframes = new Set(generatingKeyframes);
        const newKeyframeImageUrls = { ...keyframeImageUrls };
        const updatedShots = [...shots];

        result.data.forEach((task: any) => {
          // 从 task.name 中提取 shotId 和 frameIndex
          // 格式类似 "关键帧图片: shotId-frameIndex"
          const match = task.name?.match(/关键帧.*?([a-f0-9-]{36})-(\d+)/i);
          if (match) {
            const shotId = match[1];
            const frameIndex = parseInt(match[2], 10);
            const keyframeKey = `${shotId}-${frameIndex}`;

            // 更新任务状态
            const taskIndex = newKeyframeTasks.findIndex(t => t.taskId === task.id);
            if (taskIndex >= 0) {
              newKeyframeTasks[taskIndex] = { ...newKeyframeTasks[taskIndex], status: task.status };
              keyframeTasksUpdated = true;
            }

            // 如果完成，更新图片URL
            if (task.status === 'completed' && task.resultUrl) {
              if (newKeyframeImageUrls[keyframeKey] !== task.resultUrl) {
                newKeyframeImageUrls[keyframeKey] = task.resultUrl;
                keyframeImageUrlsUpdated = true;
              }

              // 从生成中集合移除
              if (newGeneratingKeyframes.has(keyframeKey)) {
                newGeneratingKeyframes.delete(keyframeKey);
                generatingKeyframesUpdated = true;
              }

              // 更新 shot 的 keyframes
              const shotIndex = updatedShots.findIndex(s => s.id === shotId);
              if (shotIndex >= 0) {
                const shot = updatedShots[shotIndex];
                const updatedKeyframes = (shot.keyframes || []).map((kf: any) =>
                  kf.frame_index === frameIndex
                    ? { ...kf, image_url: task.resultUrl, image_task_id: task.id }
                    : kf
                );
                updatedShots[shotIndex] = { ...shot, keyframes: updatedKeyframes };
              }
            } else if (task.status === 'failed') {
              // 失败时从生成中集合移除
              if (newGeneratingKeyframes.has(keyframeKey)) {
                newGeneratingKeyframes.delete(keyframeKey);
                generatingKeyframesUpdated = true;
              }
            }
          }
        });

        // 只在数据变化时更新状态
        if (keyframeTasksUpdated || generatingKeyframesUpdated || keyframeImageUrlsUpdated) {
          set({
            keyframeTasks: newKeyframeTasks,
            generatingKeyframes: newGeneratingKeyframes,
            keyframeImageUrls: newKeyframeImageUrls,
            shots: updatedShots,
          });
        }
      }
    } catch (error) {
      console.error('检查关键帧任务状态失败:', error);
    }
  },

  // ========== 关键帧生成方法 ==========

  generateKeyframeDescriptions: async (novelId, chapterId, shotId, count = 3) => {
    try {
      const result = await shotsApi.generateKeyframeDescriptions(novelId, chapterId, shotId, count);

      if (result.success && result.data?.keyframes) {
        // 更新 shot 的 keyframes
        const updatedShots = get().shots.map(shot => {
          if (shot.id === shotId) {
            // 合并新描述到现有 keyframes，或创建新的
            const existingKeyframes = shot.keyframes || [];
            const newKeyframes = result.data!.keyframes.map((kf: any, index: number) => ({
              frame_index: existingKeyframes.length + index,
              description: kf.description,
              image_url: undefined,
              image_task_id: undefined,
              reference_image_url: undefined,
            }));
            return {
              ...shot,
              keyframes: [...existingKeyframes, ...newKeyframes],
            };
          }
          return shot;
        });
        set({ shots: updatedShots });
      } else {
        throw new Error(result.message || '生成关键帧描述失败');
      }
    } catch (error) {
      console.error('生成关键帧描述失败:', error);
      throw error;
    }
  },

  generateKeyframeImage: async (novelId, chapterId, shotId, frameIndex, workflowId) => {
    const keyframeKey = `${shotId}-${frameIndex}`;
    set(state => ({
      generatingKeyframes: new Set([...state.generatingKeyframes, keyframeKey])
    }));

    try {
      const result = await shotsApi.generateKeyframeImage(novelId, chapterId, shotId, frameIndex, workflowId);

      if (result.success && result.data?.task_id) {
        // 添加到 keyframeTasks
        const newTask: KeyframeTask = {
          shotId,
          frameIndex,
          taskId: result.data.task_id,
          status: 'pending',
        };
        set(state => ({
          keyframeTasks: [...state.keyframeTasks, newTask]
        }));

        // 更新 shot 的 keyframes
        const updatedShots = get().shots.map(shot => {
          if (shot.id === shotId) {
            const updatedKeyframes = (shot.keyframes || []).map((kf: any) =>
              kf.frame_index === frameIndex
                ? { ...kf, image_task_id: result.data!.task_id }
                : kf
            );
            return { ...shot, keyframes: updatedKeyframes };
          }
          return shot;
        });
        set({ shots: updatedShots });
      } else {
        throw new Error(result.message || '生成关键帧图片失败');
      }
    } catch (error) {
      console.error('生成关键帧图片失败:', error);
      set(state => {
        const newSet = new Set(state.generatingKeyframes);
        newSet.delete(keyframeKey);
        return { generatingKeyframes: newSet };
      });
      throw error;
    }
  },

  uploadKeyframeImage: async (novelId, chapterId, shotId, frameIndex, file) => {
    try {
      const result = await shotsApi.uploadKeyframeImage(novelId, chapterId, shotId, frameIndex, file);

      if (result.success && result.data?.image_url) {
        const keyframeKey = `${shotId}-${frameIndex}`;

        // 更新 keyframeImageUrls
        set(state => ({
          keyframeImageUrls: {
            ...state.keyframeImageUrls,
            [keyframeKey]: result.data!.image_url
          }
        }));

        // 更新 shot 的 keyframes
        const updatedShots = get().shots.map(shot => {
          if (shot.id === shotId) {
            const updatedKeyframes = (shot.keyframes || []).map((kf: any) =>
              kf.frame_index === frameIndex
                ? { ...kf, image_url: result.data!.image_url }
                : kf
            );
            return { ...shot, keyframes: updatedKeyframes };
          }
          return shot;
        });
        set({ shots: updatedShots });
      } else {
        throw new Error(result.message || '上传关键帧图片失败');
      }
    } catch (error) {
      console.error('上传关键帧图片失败:', error);
      throw error;
    }
  },

  uploadKeyframeReferenceImage: async (novelId, chapterId, shotId, frameIndex, file) => {
    try {
      const result = await shotsApi.uploadKeyframeReferenceImage(novelId, chapterId, shotId, frameIndex, file);

      if (result.success && result.data?.reference_url) {
        // 更新 shot 的 keyframes
        const updatedShots = get().shots.map(shot => {
          if (shot.id === shotId) {
            const updatedKeyframes = (shot.keyframes || []).map((kf: any) =>
              kf.frame_index === frameIndex
                ? { ...kf, reference_image_url: result.data!.reference_url }
                : kf
            );
            return { ...shot, keyframes: updatedKeyframes };
          }
          return shot;
        });
        set({ shots: updatedShots });
      } else {
        throw new Error(result.message || '上传参考图失败');
      }
    } catch (error) {
      console.error('上传参考图失败:', error);
      throw error;
    }
  },

  setKeyframeReferenceImage: async (novelId, chapterId, shotId, frameIndex, mode, referenceUrl) => {
    try {
      const result = await shotsApi.setKeyframeReferenceImage(novelId, chapterId, shotId, frameIndex, mode, referenceUrl);

      if (result.success) {
        // 更新 shot 的 keyframes
        const updatedShots = get().shots.map(shot => {
          if (shot.id === shotId) {
            const updatedKeyframes = (shot.keyframes || []).map((kf: any) =>
              kf.frame_index === frameIndex
                ? { ...kf, reference_image_url: result.data?.reference_url || null }
                : kf
            );
            return { ...shot, keyframes: updatedKeyframes };
          }
          return shot;
        });
        set({ shots: updatedShots });
      } else {
        throw new Error(result.message || '设置参考图失败');
      }
    } catch (error) {
      console.error('设置参考图失败:', error);
      throw error;
    }
  },

  isKeyframeGenerating: (shotId, frameIndex) => {
    const keyframeKey = `${shotId}-${frameIndex}`;
    return get().generatingKeyframes.has(keyframeKey);
  },

  getKeyframeImageUrl: (shotId, frameIndex) => {
    const keyframeKey = `${shotId}-${frameIndex}`;
    return get().keyframeImageUrls[keyframeKey];
  },

  getKeyframeTask: (shotId, frameIndex) => {
    return get().keyframeTasks.find(t => t.shotId === shotId && t.frameIndex === frameIndex);
  },

  // ========== 参考音频方法 ==========

  mergeDialogueAudio: async (novelId, chapterId, shotId) => {
    set(state => ({
      mergingReferenceAudios: new Set([...state.mergingReferenceAudios, shotId])
    }));

    try {
      const result = await shotsApi.mergeDialogueAudio(novelId, chapterId, shotId);

      if (result.success && result.audio_url) {
        // 更新 shot 的 referenceAudioUrl
        const updatedShots = get().shots.map(shot => {
          if (shot.id === shotId) {
            return { ...shot, referenceAudioUrl: result.audio_url };
          }
          return shot;
        });
        set({ shots: updatedShots });
      } else {
        throw new Error(result.message || '合并音频失败');
      }
    } catch (error) {
      console.error('合并台词音频失败:', error);
      throw error;
    } finally {
      set(state => {
        const newSet = new Set(state.mergingReferenceAudios);
        newSet.delete(shotId);
        return { mergingReferenceAudios: newSet };
      });
    }
  },

  uploadReferenceAudio: async (novelId, chapterId, shotId, file) => {
    set(state => ({
      uploadingReferenceAudios: new Set([...state.uploadingReferenceAudios, shotId])
    }));

    try {
      const result = await shotsApi.uploadReferenceAudio(novelId, chapterId, shotId, file);

      if (result.success && result.audio_url) {
        // 更新 shot 的 referenceAudioUrl
        const updatedShots = get().shots.map(shot => {
          if (shot.id === shotId) {
            return { ...shot, referenceAudioUrl: result.audio_url };
          }
          return shot;
        });
        set({ shots: updatedShots });
      } else {
        throw new Error(result.message || '上传音频失败');
      }
    } catch (error) {
      console.error('上传参考音频失败:', error);
      throw error;
    } finally {
      set(state => {
        const newSet = new Set(state.uploadingReferenceAudios);
        newSet.delete(shotId);
        return { uploadingReferenceAudios: newSet };
      });
    }
  },

  setReferenceAudio: async (novelId, chapterId, shotId, mode, characterName) => {
    try {
      const result = await shotsApi.setReferenceAudio(novelId, chapterId, shotId, mode, characterName);

      if (result.success) {
        // 更新 shot 的 referenceAudioUrl
        const updatedShots = get().shots.map(shot => {
          if (shot.id === shotId) {
            return { ...shot, referenceAudioUrl: result.audio_url || undefined };
          }
          return shot;
        });
        set({ shots: updatedShots });
      } else {
        throw new Error(result.message || '设置参考音频失败');
      }
    } catch (error) {
      console.error('设置参考音频失败:', error);
      throw error;
    }
  },

  getReferenceAudioUrl: (shotId) => {
    const shot = get().shots.find(s => s.id === shotId);
    return shot?.referenceAudioUrl ?? undefined;
  },

  inferReferenceAudioSourceType: (shotId) => {
    const shot = get().shots.find(s => s.id === shotId);
    if (!shot?.referenceAudioUrl) {
      return 'none';
    }

    const url = shot.referenceAudioUrl;

    // 根据 URL 模式推断来源类型
    if (url.includes('merged_audio')) {
      return 'merged';
    } else if (url.includes('reference_audio')) {
      return 'uploaded';
    } else {
      // 可能是角色音色，需要进一步检查
      return 'character';
    }
  },

  isReferenceAudioMerging: (shotId) => {
    return get().mergingReferenceAudios.has(shotId);
  },

  isReferenceAudioUploading: (shotId) => {
    return get().uploadingReferenceAudios.has(shotId);
  },
});
