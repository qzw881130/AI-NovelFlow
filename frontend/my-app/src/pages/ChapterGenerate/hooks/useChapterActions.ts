import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import { API_BASE } from '../constants';
import type { ParsedData, Character, Scene } from '../types';
import { mergeCharacterImages } from '../utils';

interface UseChapterActionsParams {
  id: string | undefined;
  cid: string | undefined;
  characters: Character[];
  scenes: Scene[];
  parsedData: ParsedData | null;
  shotImages: Record<number, string>;
  shotVideos: Record<number, string>;
  transitionVideos: Record<string, string>;
  mergedImage: string | null;
  getCharacterImage: (name: string) => string | undefined;
  setParsedData: (data: ParsedData | null) => void;
  setEditableJson: (json: string) => void;
  setShotImages: (images: Record<number, string> | ((prev: Record<number, string>) => Record<number, string>)) => void;
  setShotVideos: (videos: Record<number, string> | ((prev: Record<number, string>) => Record<number, string>)) => void;
  setTransitionVideos: (videos: Record<string, string> | ((prev: Record<string, string>) => Record<string, string>)) => void;
  setMergedImage: (image: string | null) => void;
  setEditorKey: (key: number | ((prev: number) => number)) => void;
  setActiveTab: (tab: 'json' | 'characters' | 'scenes' | 'script') => void;
  setIsSplitting: (splitting: boolean) => void;
  setIsSavingJson: (saving: boolean) => void;
  setIsMerging: (merging: boolean) => void;
  setSplitConfirmDialog: (dialog: { isOpen: boolean; hasResources: boolean }) => void;
  fetchChapter: (novelId: string, chapterId: string) => void;
  currentShot: number;
}

interface ShotWorkflow {
  id: string;
  name: string;
  isActive: boolean;
  extension?: {
    reference_image_count?: string;
  };
}

/**
 * 章节操作函数 Hook
 */
export default function useChapterActions({
  id,
  cid,
  characters,
  scenes,
  parsedData,
  shotImages,
  shotVideos,
  transitionVideos,
  mergedImage,
  getCharacterImage,
  setParsedData,
  setEditableJson,
  setShotImages,
  setShotVideos,
  setTransitionVideos,
  setMergedImage,
  setEditorKey,
  setActiveTab,
  setIsSplitting,
  setIsSavingJson,
  setIsMerging,
  setSplitConfirmDialog,
  fetchChapter,
  currentShot,
}: UseChapterActionsParams) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  // 跳转到角色库页面
  const handleRegenerateCharacter = useCallback((characterName: string) => {
    const character = characters.find(c => c.name === characterName);
    if (character) {
      navigate(`/characters?novel_id=${id}&highlight=${character.id}`);
    } else {
      navigate(`/characters?novel_id=${id}`);
    }
  }, [characters, id, navigate]);

  // 跳转到场景库页面
  const handleRegenerateScene = useCallback((sceneName: string) => {
    const scene = scenes.find(s => s.name === sceneName);
    if (scene) {
      navigate(`/scenes?novel_id=${id}&highlight=${scene.id}`);
    } else {
      navigate(`/scenes?novel_id=${id}`);
    }
  }, [scenes, id, navigate]);

  // 合并角色图
  const handleMergeCharacterImages = useCallback(async () => {
    const currentShotData = parsedData?.shots?.[currentShot - 1];
    const shotCharacters = currentShotData?.characters || [];
    
    if (shotCharacters.length === 0) {
      toast.warning(t('chapterGenerate.noCharactersInShot'));
      return;
    }

    setIsMerging(true);
    try {
      const result = await mergeCharacterImages(shotCharacters, getCharacterImage);
      if (result) {
        setMergedImage(result);
      } else {
        toast.warning(t('chapterGenerate.characterImagesNotGenerated'));
      }
    } catch (error) {
      console.error('合并角色图失败:', error);
      toast.error(t('chapterGenerate.mergeFailedRetry'));
    } finally {
      setIsMerging(false);
    }
  }, [parsedData, currentShot, getCharacterImage, setMergedImage, setIsMerging, t]);

  // 处理AI拆分分镜头按钮点击
  const handleSplitChapterClick = useCallback(() => {
    if (!id || !cid) return;
    
    const hasResources = !!parsedData || 
      Object.keys(shotImages).length > 0 || 
      Object.keys(shotVideos).length > 0 ||
      Object.keys(transitionVideos).length > 0 ||
      !!mergedImage;
    
    if (hasResources) {
      setSplitConfirmDialog({ isOpen: true, hasResources: true });
    } else {
      doSplitChapter();
    }
  }, [id, cid, parsedData, shotImages, shotVideos, transitionVideos, mergedImage, setSplitConfirmDialog]);

  // 确认后执行拆分
  const doSplitChapter = useCallback(async () => {
    if (!id || !cid) return;
    
    setSplitConfirmDialog({ isOpen: false, hasResources: false });
    
    try {
      const clearRes = await fetch(`${API_BASE}/novels/${id}/chapters/${cid}/clear-resources`, {
        method: 'POST'
      });
      const clearData = await clearRes.json();
      if (!clearData.success) {
        console.error('清除资源失败:', clearData.message);
      }
    } catch (error) {
      console.error('清除资源请求失败:', error);
    }
    
    setIsSplitting(true);
    try {
      const res = await fetch(`${API_BASE}/novels/${id}/chapters/${cid}/split/`, {
        method: 'POST'
      });
      const data = await res.json();
      
      if (data.success) {
        setShotImages({});
        setShotVideos({});
        setTransitionVideos({});
        setMergedImage(null);
        setParsedData(data.data);
        setEditableJson(JSON.stringify(data.data, null, 2));
        setEditorKey(prev => prev + 1);
        setActiveTab('json');
        toast.success(t('chapterGenerate.splitSuccess'));
        fetchChapter(id, cid);
      } else {
        toast.error(data.message || t('chapterGenerate.splitFailed'));
      }
    } catch (error) {
      console.error('拆分章节失败:', error);
      toast.error(t('chapterGenerate.splitFailedCheckNetwork'));
    } finally {
      setIsSplitting(false);
    }
  }, [id, cid, setSplitConfirmDialog, setIsSplitting, setShotImages, setShotVideos, setTransitionVideos, setMergedImage, setParsedData, setEditableJson, setEditorKey, setActiveTab, fetchChapter, t]);

  // 保存JSON修改
  const handleSaveJson = useCallback(async (editableJson: string) => {
    if (!id || !cid || !editableJson.trim()) return;
    
    let parsedJson;
    try {
      parsedJson = JSON.parse(editableJson);
    } catch (e) {
      toast.error(t('chapterGenerate.jsonFormatErrorCheck'));
      return;
    }
    
    setIsSavingJson(true);
    try {
      const res = await fetch(`${API_BASE}/novels/${id}/chapters/${cid}/`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          parsedData: editableJson
        })
      });
      const data = await res.json();
      
      if (data.success) {
        setParsedData(parsedJson);
        toast.success(t('chapterGenerate.saveSuccess'));
      } else {
        toast.error(data.message || t('chapterGenerate.saveFailed'));
      }
    } catch (error) {
      console.error('保存JSON失败:', error);
      toast.error(t('chapterGenerate.saveFailedCheckNetwork'));
    } finally {
      setIsSavingJson(false);
    }
  }, [id, cid, setIsSavingJson, setParsedData, t]);

  return {
    handleRegenerateCharacter,
    handleRegenerateScene,
    handleMergeCharacterImages,
    handleSplitChapterClick,
    doSplitChapter,
    handleSaveJson,
  };
}
