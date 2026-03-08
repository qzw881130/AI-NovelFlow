/**
 * Chapter Actions Slice - 管理章节操作相关业务逻辑
 * 包含：拆分章节、保存JSON、合并角色图、跳转导航等
 */
import type { StateCreator } from 'zustand';
import type { ChapterGenerateStore, ChapterActionsState, Shot } from './types';
import { API_BASE } from '../../constants';
import { chapterApi } from '../../../../api/chapters';
import { mergeCharacterImages } from '../../utils';
import { toast } from '../../../../stores/toastStore';
import { useI18nStore } from '../../../../stores/i18nStore';

export interface ChapterActionsSlice extends ChapterActionsState {}

export const createChapterActionsSlice: StateCreator<
  ChapterGenerateStore,
  [],
  [],
  ChapterActionsSlice
> = (set, get) => ({
  // ========== 导航方法 ==========

  navigateToCharacter: (characterName: string) => {
    const novel = get().novel;
    if (!novel) return;

    const character = get().characters.find((c) => c.name === characterName);
    const highlight = character ? `&highlight=${character.id}` : '';
    window.location.href = `/characters?novel_id=${novel.id}${highlight}`;
  },

  navigateToScene: (sceneName: string) => {
    const novel = get().novel;
    if (!novel) return;

    const scene = get().scenes.find((s) => s.name === sceneName);
    const highlight = scene ? `&highlight=${scene.id}` : '';
    window.location.href = `/scenes?novel_id=${novel.id}${highlight}`;
  },

  navigateToProp: (propName: string) => {
    const novel = get().novel;
    if (!novel) return;

    const prop = get().props.find((p) => p.name === propName);
    const highlight = prop ? `&highlight=${prop.id}` : '';
    window.location.href = `/props?novel_id=${novel.id}${highlight}`;
  },

  // ========== 章节操作 ==========

  handleSplitChapter: async (novelId: string, chapterId: string) => {
    // 注意：此方法假设确认弹窗已经由 handleSplitChapterClick 打开
    // 这里不再重复设置弹窗状态，直接执行拆分
    await get().splitChapter(novelId, chapterId);
  },

  splitChapter: async (novelId: string, chapterId: string) => {
    const t = useI18nStore.getState().t;

    set({ splitConfirmDialog: { isOpen: false, hasResources: false } });

    // 清除旧资源
    try {
      await fetch(`${API_BASE}/novels/${novelId}/chapters/${chapterId}/clear-resources`, {
        method: 'POST',
      });
    } catch (error) {
      console.error('清除资源请求失败:', error);
    }

    set({ isSplitting: true });
    try {
      const res = await fetch(`${API_BASE}/novels/${novelId}/chapters/${chapterId}/split/`, {
        method: 'POST',
      });
      const data = await res.json();

      if (data.success) {
        // 从返回数据中提取 shots 数组
        const shots = data.data.shots || [];

        // 将 shots 转换为 Shot 类型
        const typedShots = shots.map((s: any) => s);

        set({
          shots: typedShots,
          shotImages: {},  // 清空已生成的图片（重新拆分后）
          shotVideos: {},  // 清空已生成的视频（重新拆分后）
          transitionVideos: {},
          mergedImage: null,
          parsedData: data.data,  // 包含 shots 数组
          editableJson: JSON.stringify(data.data, null, 2),
          activeTab: 'prepare',
        });
        toast.success(t('chapterGenerate.splitSuccess'));
        // 注意：不再调用 fetchChapter，因为它会覆盖 parsedData（数据库中的 parsed_data 不包含 shots）
      } else {
        toast.error(data.message || t('chapterGenerate.splitFailed'));
      }
    } catch (error) {
      console.error('拆分章节失败:', error);
      toast.error(t('chapterGenerate.splitFailedCheckNetwork'));
    } finally {
      set({ isSplitting: false });
    }
  },

  handleSaveJson: async (novelId: string, chapterId: string, editableJson: string) => {
    const t = useI18nStore.getState().t;

    if (!editableJson.trim()) return;

    let parsedJson;
    try {
      parsedJson = JSON.parse(editableJson);
    } catch (e) {
      toast.error(t('chapterGenerate.jsonFormatErrorCheck'));
      return;
    }

    set({ isSavingJson: true });
    try {
      const res = await fetch(`${API_BASE}/novels/${novelId}/chapters/${chapterId}/`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          parsedData: editableJson,
        }),
      });
      const data = await res.json();

      if (data.success) {
        set({ parsedData: parsedJson });
        toast.success(t('chapterGenerate.saveSuccess'));
      } else {
        toast.error(data.message || t('chapterGenerate.saveFailed'));
      }
    } catch (error) {
      console.error('保存JSON失败:', error);
      toast.error(t('chapterGenerate.saveFailedCheckNetwork'));
    } finally {
      set({ isSavingJson: false });
    }
  },

  handleMergeCharacterImages: async () => {
    const t = useI18nStore.getState().t;
    const currentShot = get().currentShot;
    const parsedData = get().parsedData;

    const currentShotData = parsedData?.shots?.[currentShot - 1];
    const shotCharacters = currentShotData?.characters || [];

    if (shotCharacters.length === 0) {
      toast.warning(t('chapterGenerate.noCharactersInShot'));
      return;
    }

    set({ isMerging: true });
    try {
      const result = await mergeCharacterImages(shotCharacters, get().getCharacterImage);
      if (result) {
        set({ mergedImage: result });
      } else {
        toast.warning(t('chapterGenerate.characterImagesNotGenerated'));
      }
    } catch (error) {
      console.error('合并角色图失败:', error);
      toast.error(t('chapterGenerate.mergeFailedRetry'));
    } finally {
      set({ isMerging: false });
    }
  },

  clearChapterResources: async (novelId: string, chapterId: string) => {
    try {
      const res = await fetch(`${API_BASE}/novels/${novelId}/chapters/${chapterId}/clear-resources`, {
        method: 'POST',
      });
      const data = await res.json();
      if (!data.success) {
        console.error('清除资源失败:', data.message);
      }
    } catch (error) {
      console.error('清除资源请求失败:', error);
    }
  },

  // ========== 资源重新生成方法 ==========

  handleRegenerateCharacter: (name: string) => {
    const novel = get().novel;
    if (!novel) return;
    const character = get().characters.find((c) => c.name === name);
    if (character) {
      window.location.href = `/characters?novel_id=${novel.id}&highlight=${character.id}&regenerate=true`;
    }
  },

  handleRegenerateScene: (name: string) => {
    const novel = get().novel;
    if (!novel) return;
    const scene = get().scenes.find((s) => s.name === name);
    if (scene) {
      window.location.href = `/scenes?novel_id=${novel.id}&highlight=${scene.id}&regenerate=true`;
    }
  },

  handleRegenerateProp: (name: string) => {
    const novel = get().novel;
    if (!novel) return;
    const prop = get().props.find((p) => p.name === name);
    if (prop) {
      window.location.href = `/props?novel_id=${novel.id}&highlight=${prop.id}&regenerate=true`;
    }
  },

  // ========== 下载章节素材 ==========

  downloadChapterMaterials: async (novelId: string, chapterId: string) => {
    const t = useI18nStore.getState().t;

    // 构建下载 URL
    const downloadUrl = `${API_BASE}/novels/${novelId}/chapters/${chapterId}/download-materials/`;

    // 使用临时链接触发下载
    const link = document.createElement('a');
    link.href = downloadUrl;
    link.setAttribute('download', '');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    toast.success(t('chapterGenerate.materialsDownloadSuccess'));
  },
});
