import { useState, useEffect, useCallback } from 'react';
import { useNovelStore } from '../../../stores/novelStore';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import { promptTemplateApi } from '../../../api/promptTemplates';
import { sceneApi } from '../../../api/scenes';
import { propApi } from '../../../api/props';
import { novelApi } from '../../../api/novels';
import type { PromptTemplate } from '../../../types';
import type { ChapterRange, ConfirmDialogState, ParseType } from '../types';

// 模板类型列表
const TEMPLATE_TYPES = [
  'style',
  'character_parse',
  'scene_parse',
  'prop_parse',
  'character',
  'scene',
  'prop',
  'chapter_split',
  'shot_contract_repair',
  'keyframe_description',
  'shot_image_prompt',
  'video_mode_recommender',
  'keyframe_planner',
  'keyframe_image_prompt',
  'keyframe_transition',
  'h3_single_frame_prompt',
  'h3_first_last_frame_prompt',
  'h3_multi_keyframe_prompt',
] as const;
type TemplateType = typeof TEMPLATE_TYPES[number];

export function useNovelsState() {
  const { t } = useTranslation();
  const { novels, isLoading, fetchNovels, createNovel, copyNovel: copyNovelRequest, deleteNovel, importNovel, updateNovel } = useNovelStore();

  const [searchQuery, setSearchQuery] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showCopyModal, setShowCopyModal] = useState(false);
  const [editingNovel, setEditingNovel] = useState<any>(null);
  const [importing, setImporting] = useState(false);
  const [parsingNovelId, setParsingNovelId] = useState<string | null>(null);
  const [parsingScenesNovelId, setParsingScenesNovelId] = useState<string | null>(null);
  const [parsingPropsNovelId, setParsingPropsNovelId] = useState<string | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<ConfirmDialogState>({
    isOpen: false,
    novelId: null,
    type: 'characters'
  });
  const [chapterRange, setChapterRange] = useState<ChapterRange>({
    startChapter: null,
    endChapter: null,
    isIncremental: false
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

  const copyNovel = async (sourceId: string, title: string) => {
    const copied = await copyNovelRequest(sourceId, title);
    setSearchQuery('');
    toast.success(t('novels.copySuccess', { title: copied.title, count: copied.chapterCount }));
  };

  const openParseConfirm = (novelId: string, type: ParseType = 'characters') => {
    setConfirmDialog({ isOpen: true, novelId, type });
  };

  const closeParseConfirm = () => {
    setConfirmDialog({ isOpen: false, novelId: null, type: 'characters' });
  };

  const showCandidateResults = (data: any, novelId: string) => {
    const runs = Array.isArray(data.data) ? data.data : [];
    const first = runs.find((run: any) => !run.phase1Ready || run.phase2Ready === false) || runs[0];
    if (!first) { toast.error(data.message || t('novels.parseFailed')); return; }
    const message = t('novels.candidateParseResult', { count: data.statistics?.candidates || 0 });
    if (data.success) toast.success(message);
    else toast.warning(data.message || message);
    window.location.href = `/novels/${novelId}/chapters/${first.chapterId}`;
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
      showCandidateResults(data, novelId);
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
      const chapters = await novelApi.fetchChapters(novelId);
      if (!chapters.success || !chapters.data) throw new Error('读取章回失败');
      const ids = chapters.data.filter(chapter =>
        (chapterRange.startChapter == null || chapter.number >= chapterRange.startChapter) &&
        (chapterRange.endChapter == null || chapter.number <= chapterRange.endChapter)
      ).map(chapter => chapter.id);
      if (!ids.length) { toast.error('所选范围内没有章回'); return; }
      const data = await sceneApi.parseScenes(novelId, 'incremental', ids);
      showCandidateResults(data, novelId);
    } catch (error) {
      console.error(t('novels.parseFailed') + ':', error);
      toast.error(t('novels.parseNetworkError'));
    } finally {
      setParsingScenesNovelId(null);
    }
  };

  const confirmParseProps = async () => {
    const novelId = confirmDialog.novelId;
    if (!novelId) return;

    closeParseConfirm();
    setParsingPropsNovelId(novelId);

    try {
      const data = await propApi.parseProps(novelId, {
        startChapter: chapterRange.startChapter ?? undefined,
        endChapter: chapterRange.endChapter ?? undefined,
        isIncremental: chapterRange.isIncremental
      });
      showCandidateResults(data, novelId);
    } catch (error) {
      console.error(t('novels.parseFailed') + ':', error);
      toast.error(t('novels.parseNetworkError'));
    } finally {
      setParsingPropsNovelId(null);
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
    showCopyModal,
    setShowCopyModal,
    editingNovel,
    setEditingNovel,
    importing,
    parsingNovelId,
    parsingScenesNovelId,
    parsingPropsNovelId,
    confirmDialog,
    chapterRange,
    setChapterRange,
    templatesByType,
    filteredNovels,

    // Actions
    fetchNovels,
    createNovel,
    copyNovel,
    deleteNovel,
    updateNovel,
    handleImport,
    openParseConfirm,
    closeParseConfirm,
    confirmParseCharacters,
    confirmParseScenes,
    confirmParseProps,
    getTemplateDisplayName,
  };
}
