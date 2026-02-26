import { useState, useEffect, useCallback } from 'react';
import { useNovelStore } from '../../../stores/novelStore';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import { promptTemplateApi } from '../../../api/promptTemplates';
import { sceneApi } from '../../../api/scenes';
import type { PromptTemplate } from '../../../types';
import type { ChapterRange, ConfirmDialogState, ParseType } from '../types';

// 模板类型列表
const TEMPLATE_TYPES = ['style', 'character_parse', 'scene_parse', 'character', 'scene', 'chapter_split'] as const;
type TemplateType = typeof TEMPLATE_TYPES[number];

export function useNovelsState() {
  const { t } = useTranslation();
  const { novels, isLoading, fetchNovels, createNovel, deleteNovel, importNovel, updateNovel } = useNovelStore();
  
  const [searchQuery, setSearchQuery] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingNovel, setEditingNovel] = useState<any>(null);
  const [importing, setImporting] = useState(false);
  const [parsingNovelId, setParsingNovelId] = useState<string | null>(null);
  const [parsingScenesNovelId, setParsingScenesNovelId] = useState<string | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<ConfirmDialogState>({
    isOpen: false,
    novelId: null,
    type: 'characters'
  });
  const [chapterRange, setChapterRange] = useState<ChapterRange>({
    startChapter: null,
    endChapter: null,
    isIncremental: true
  });
  
  // 使用 Record 存储各类型模板
  const [templatesByType, setTemplatesByType] = useState<Record<string, PromptTemplate[]>>({});

  useEffect(() => {
    fetchNovels();
    fetchAllTemplates();
  }, []);

  const fetchAllTemplates = async () => {
    try {
      const results = await Promise.all(
        TEMPLATE_TYPES.map(type => promptTemplateApi.fetchList(type as any))
      );
      
      const newTemplatesByType: Record<string, PromptTemplate[]> = {};
      TEMPLATE_TYPES.forEach((type, index) => {
        if (results[index].success && results[index].data) {
          newTemplatesByType[type] = results[index].data!;
        } else {
          newTemplatesByType[type] = [];
        }
      });
      
      setTemplatesByType(newTemplatesByType);
    } catch (error) {
      console.error('加载提示词模板失败:', error);
    }
  };

  const getTemplateDisplayName = useCallback((template: PromptTemplate | undefined): string => {
    if (!template) return t('novels.default');
    if (template.isSystem) {
      return t(`promptConfig.templateNames.${template.name}`, { defaultValue: template.name });
    }
    return template.name;
  }, [t]);

  const filteredNovels = novels.filter(
    (novel) =>
      novel.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      novel.author.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const openParseConfirm = (novelId: string, type: ParseType = 'characters') => {
    setConfirmDialog({ isOpen: true, novelId, type });
  };

  const closeParseConfirm = () => {
    setConfirmDialog({ isOpen: false, novelId: null, type: 'characters' });
  };

  const confirmParseCharacters = async () => {
    const novelId = confirmDialog.novelId;
    if (!novelId) return;
    
    closeParseConfirm();
    setParsingNovelId(novelId);
    
    try {
      const params = {
        sync: true,
        start_chapter: chapterRange.startChapter ?? undefined,
        end_chapter: chapterRange.endChapter ?? undefined,
        is_incremental: chapterRange.isIncremental
      };
      
      const res = await fetch(`/api/novels/${novelId}/parse-characters/?sync=true${params.start_chapter ? `&start_chapter=${params.start_chapter}` : ''}${params.end_chapter ? `&end_chapter=${params.end_chapter}` : ''}&is_incremental=${params.is_incremental}`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data.success) {
        const stats = data.statistics || {};
        let message = '';
        if (stats.created > 0) {
          message += t('novels.parseResult', { created: stats.created, updated: stats.updated });
        }
        if (message) {
          toast.success(message);
        } else {
          toast.warning(t('novels.noNewCharacters'));
        }
        setChapterRange({ startChapter: null, endChapter: null, isIncremental: true });
        window.location.href = `/characters?novel=${novelId}`;
      } else {
        toast.error(t('novels.parseError') + ': ' + data.message);
      }
    } catch (error) {
      console.error(t('novels.parseFailed') + ':', error);
      toast.error(t('novels.parseNetworkError'));
    } finally {
      setParsingNovelId(null);
    }
  };

  const confirmParseScenes = async () => {
    const novelId = confirmDialog.novelId;
    if (!novelId) return;
    
    closeParseConfirm();
    setParsingScenesNovelId(novelId);
    
    try {
      const data = await sceneApi.parseScenes(novelId, chapterRange.isIncremental ? 'incremental' : 'full');
      if (data.success) {
        const stats = (data.data as { statistics?: { created?: number; updated?: number } })?.statistics || {};
        let message = '';
        if ((stats.created ?? 0) > 0 || (stats.updated ?? 0) > 0) {
          message = t('novels.parseScenesResult', { created: stats.created || 0, updated: stats.updated || 0 });
        }
        if (message) {
          toast.success(message);
        } else {
          toast.info(t('novels.noNewScenes'));
        }
        setChapterRange({ startChapter: null, endChapter: null, isIncremental: true });
        window.location.href = `/scenes?novel=${novelId}`;
      } else {
        toast.error(t('novels.parseError') + ': ' + data.message);
      }
    } catch (error) {
      console.error(t('novels.parseFailed') + ':', error);
      toast.error(t('novels.parseNetworkError'));
    } finally {
      setParsingScenesNovelId(null);
    }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    await importNovel(file);
    setImporting(false);
  };

  return {
    // State
    novels,
    isLoading,
    searchQuery,
    setSearchQuery,
    showCreateModal,
    setShowCreateModal,
    editingNovel,
    setEditingNovel,
    importing,
    parsingNovelId,
    parsingScenesNovelId,
    confirmDialog,
    chapterRange,
    setChapterRange,
    templatesByType,
    filteredNovels,
    
    // Actions
    fetchNovels,
    createNovel,
    deleteNovel,
    updateNovel,
    handleImport,
    openParseConfirm,
    closeParseConfirm,
    confirmParseCharacters,
    confirmParseScenes,
    getTemplateDisplayName,
  };
}
