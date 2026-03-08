/**
 * 数据 Slice - 管理章节数据、资源数据和分镜数据
 */
import type { StateCreator } from 'zustand';
import type {
  DataSliceState,
  ChapterGenerateStore,
  Shot,
  ParsedData,
} from './types';
import type { Character } from '../../types';
import { API_BASE } from '../../constants';
import { shotsApi } from '../../../../api/shots';

export interface DataSlice extends DataSliceState {
  fetchNovel: (novelId: string) => Promise<void>;
  fetchChapter: (novelId: string, chapterId: string) => Promise<void>;
  fetchCharacters: (novelId: string) => Promise<void>;
  fetchScenes: (novelId: string) => Promise<void>;
  fetchProps: (novelId: string) => Promise<void>;
  fetchShots: (novelId: string, chapterId: string) => Promise<void>;
  fetchShotsWithReturn: (novelId: string, chapterId: string) => Promise<Shot[]>;
  setParsedData: (data: ParsedData | null) => void;
  setEditableJson: (json: string) => void;
  setShots: (shots: Shot[]) => void;
  updateShot: (shotId: string, data: Partial<Shot>) => Promise<void>;
  getCharacterImage: (name: string) => string | undefined;
  getSceneImage: (name: string) => string | null;
  getPropImage: (name: string) => string | null;

  // 章节资源管理
  initChapterResources: () => void;
  addResourceToChapter: (type: 'character' | 'scene' | 'prop', name: string) => void;
  removeResourceFromChapter: (type: 'character' | 'scene' | 'prop', name: string) => void;
  saveChapterResources: (novelId: string, chapterId: string) => Promise<void>;
}

export const createDataSlice: StateCreator<
  ChapterGenerateStore,
  [],
  [],
  DataSlice
> = (set, get) => ({
  // ========== 初始状态 ==========
  chapter: null,
  novel: null,
  parsedData: null,
  editableJson: '',
  loading: true,
  characters: [] as Character[],
  scenes: [],
  props: [],
  shots: [],
  // 章节级资源初始化为空数组
  chapterCharacters: [],
  chapterScenes: [],
  chapterProps: [],

  // ========== 数据获取方法 ==========

  fetchNovel: async (novelId: string) => {
    try {
      const res = await fetch(`${API_BASE}/novels/${novelId}/`);
      const data = await res.json();
      if (data.success) {
        set({ novel: data.data });
      }
    } catch (error) {
      console.error('获取小说数据失败:', error);
    }
  },

  fetchChapter: async (novelId: string, chapterId: string) => {
    set({ loading: true });
    try {
      const res = await fetch(`${API_BASE}/novels/${novelId}/chapters/${chapterId}/`);
      const data = await res.json();
      if (data.success) {
        const chapter = data.data;
        set({ chapter });

        // 解析 parsedData
        if (chapter.parsedData) {
          try {
            const parsed = typeof chapter.parsedData === 'string'
              ? JSON.parse(chapter.parsedData)
              : chapter.parsedData;

            // 获取分镜数据并合并到 parsedData
            const shotsResult = await get().fetchShotsWithReturn(novelId, chapterId);

            // 将 shots 合并到 parsedData 中（前端代码依赖 parsedData.shots）
            const parsedWithShots = {
              ...parsed,
              shots: shotsResult
            };

            set({
              parsedData: parsedWithShots,
              editableJson: JSON.stringify(parsedWithShots, null, 2)
            });

            // 初始化章节级资源
            get().initChapterResources();
          } catch (e) {
            console.error('解析数据格式错误:', e);
          }
        } else {
          // 如果没有 parsedData，尝试获取 shots 并创建 parsedData
          const shotsResult = await get().fetchShotsWithReturn(novelId, chapterId);
          if (shotsResult && shotsResult.length > 0) {
            // Convert Shot[] to ShotData[] for compatibility
            const shotsData = shotsResult.map((shot) => ({
              id: shot.index, // Use index as number ID for ShotData
              description: shot.description,
              characters: shot.characters,
              scene: shot.scene,
              props: shot.props,
              duration: shot.duration,
              image_url: shot.imageUrl || undefined,
              image_path: shot.imagePath || undefined,
              merged_character_image: shot.mergedCharacterImage || undefined,
              dialogues: shot.dialogues,
            }));
            const parsedWithShots = {
              chapter: chapter.title,
              characters: [],
              scenes: [],
              shots: shotsData
            };
            set({
              parsedData: parsedWithShots,
              editableJson: JSON.stringify(parsedWithShots, null, 2)
            });

            // 初始化章节级资源
            get().initChapterResources();
          }
        }
      }
    } catch (error) {
      console.error('获取章节数据失败:', error);
    } finally {
      set({ loading: false });
    }
  },

  fetchCharacters: async (novelId: string) => {
    try {
      const res = await fetch(`${API_BASE}/characters/?novel_id=${novelId}`);
      const data = await res.json();
      if (data.success) {
        set({ characters: data.data });
      }
    } catch (error) {
      console.error('获取角色列表失败:', error);
    }
  },

  fetchScenes: async (novelId: string) => {
    try {
      const res = await fetch(`${API_BASE}/scenes/?novel_id=${novelId}`);
      const data = await res.json();
      if (data.success) {
        set({ scenes: data.data });
      }
    } catch (error) {
      console.error('获取场景列表失败:', error);
    }
  },

  fetchProps: async (novelId: string) => {
    try {
      const res = await fetch(`${API_BASE}/props/?novel_id=${novelId}`);
      const data = await res.json();
      if (data.success) {
        set({ props: data.data });
      }
    } catch (error) {
      console.error('获取道具列表失败:', error);
    }
  },

  fetchShots: async (novelId: string, chapterId: string) => {
    try {
      const result = await shotsApi.getShots(novelId, chapterId);
      if (result.success) {
        const shots = result.data;
        set({ shots });

        // 更新 shotImages 和 shotVideos 映射
        const shotImages: Record<number, string> = {};
        const shotVideos: Record<number, string> = {};

        shots.forEach((shot) => {
          if (shot.imageUrl) {
            shotImages[shot.index] = shot.imageUrl;
          }
          if (shot.videoUrl) {
            shotVideos[shot.index] = shot.videoUrl;
          }
        });

        set({ shotImages, shotVideos });

        // 初始化音频数据
        get().initAudioFromShots(shots);
      }
    } catch (error) {
      console.error('获取分镜列表失败:', error);
    }
  },

  fetchShotsWithReturn: async (novelId: string, chapterId: string): Promise<Shot[]> => {
    try {
      const result = await shotsApi.getShots(novelId, chapterId);
      if (result.success) {
        const shots = result.data;

        // 更新 shotImages 和 shotVideos 映射
        const shotImages: Record<number, string> = {};
        const shotVideos: Record<number, string> = {};

        shots.forEach((shot) => {
          if (shot.imageUrl) {
            shotImages[shot.index] = shot.imageUrl;
          }
          if (shot.videoUrl) {
            shotVideos[shot.index] = shot.videoUrl;
          }
        });

        set({ shots, shotImages, shotVideos });

        // 初始化音频数据
        get().initAudioFromShots(shots);

        return shots;
      }
      return [];
    } catch (error) {
      console.error('获取分镜列表失败:', error);
      return [];
    }
  },

  // ========== 数据更新方法 ==========

  setParsedData: (data: ParsedData | null) => {
    set({ parsedData: data });
  },

  setEditableJson: (json: string) => {
    set({ editableJson: json });
  },

  setShots: (shots: Shot[]) => {
    set({ shots });
  },

  updateShot: async (shotId: string, data: Partial<Shot>) => {
    const { chapter, shots } = get();
    if (!chapter) return;

    try {
      const result = await shotsApi.updateShot(
        chapter.novelId,
        chapter.id,
        shotId,
        data
      );

      if (result.success) {
        // 更新本地状态
        set({
          shots: shots.map((s) =>
            s.id === shotId ? { ...s, ...result.data } : s
          )
        });
      }
    } catch (error) {
      console.error('更新分镜失败:', error);
    }
  },

  // ========== 辅助方法 ==========

  getCharacterImage: (name: string): string | undefined => {
    const character = get().characters.find((c) => c.name === name);
    return character?.imageUrl ?? undefined;
  },

  getSceneImage: (name: string): string | null => {
    const scene = get().scenes.find((s) => s.name === name);
    return scene?.imageUrl || null;
  },

  getPropImage: (name: string): string | null => {
    const prop = get().props.find((p) => p.name === name);
    return prop?.imageUrl || null;
  },

  // ========== 章节资源管理方法 ==========

  /** 从 parsedData 初始化章节级资源 */
  initChapterResources: () => {
    const { parsedData } = get();
    if (!parsedData) return;

    const chapterCharacters = parsedData.characters || [];
    const chapterScenes = parsedData.scenes || [];
    const chapterProps = parsedData.props || [];

    set({ chapterCharacters, chapterScenes, chapterProps });
  },

  /** 添加资源到章节 */
  addResourceToChapter: (type: 'character' | 'scene' | 'prop', name: string) => {
    const key = type === 'character' ? 'chapterCharacters' : type === 'scene' ? 'chapterScenes' : 'chapterProps';
    const currentList = get()[key as keyof DataSliceState] as string[];

    if (!currentList.includes(name)) {
      set({ [key]: [...currentList, name] });
    }
  },

  /** 从章节移除资源 */
  removeResourceFromChapter: (type: 'character' | 'scene' | 'prop', name: string) => {
    const key = type === 'character' ? 'chapterCharacters' : type === 'scene' ? 'chapterScenes' : 'chapterProps';
    const currentList = get()[key as keyof DataSliceState] as string[];

    set({ [key]: currentList.filter((item) => item !== name) });
  },

  /** 保存章节资源到 parsedData 和后端 */
  saveChapterResources: async (novelId: string, chapterId: string) => {
    const { chapterCharacters, chapterScenes, chapterProps, parsedData, chapter } = get();

    if (!parsedData || !chapter) {
      console.error('缺少 parsedData 或 chapter 数据');
      return;
    }

    try {
      // 更新 parsedData 中的资源列表
      const updatedParsedData = {
        ...parsedData,
        characters: chapterCharacters,
        scenes: chapterScenes,
        props: chapterProps,
      };

      // 调用后端 API 保存
      const response = await fetch(`/api/novels/${novelId}/chapters/${chapterId}/resources`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          characters: chapterCharacters,
          scenes: chapterScenes,
          props: chapterProps,
        }),
      });

      const result = await response.json();

      if (result.success) {
        // 更新本地状态
        set({ parsedData: updatedParsedData });
        console.log('章节资源保存成功');
      } else {
        console.error('保存章节资源失败:', result.message);
      }
    } catch (error) {
      console.error('保存章节资源失败:', error);
    }
  },
});