import { useState, useEffect, useCallback } from 'react';
import { toast } from '../../../stores/toastStore';
import { useTranslation } from '../../../stores/i18nStore';
import { promptTemplateApi } from '../../../api/promptTemplates';
import type { PromptTemplate } from '../../../types';
import type { TemplateType, PromptForm } from '../types';
import { DEFAULT_CHARACTER_TEMPLATE, DEFAULT_CHAPTER_SPLIT_TEMPLATE, DEFAULT_STYLE_TEMPLATE } from '../constants';

// 模板类型配置
export const TEMPLATE_TYPE_CONFIG: Record<TemplateType, { nameKey: string; descKey: string; defaultTemplate: string }> = {
  style: { nameKey: 'promptConfig.types.style', descKey: 'promptConfig.types.styleDesc', defaultTemplate: DEFAULT_STYLE_TEMPLATE },
  character_parse: { nameKey: 'promptConfig.types.characterParse', descKey: 'promptConfig.types.characterParseDesc', defaultTemplate: '' },
  scene_parse: { nameKey: 'promptConfig.types.sceneParse', descKey: 'promptConfig.types.sceneParseDesc', defaultTemplate: '' },
  character: { nameKey: 'promptConfig.types.character', descKey: 'promptConfig.types.characterDesc', defaultTemplate: DEFAULT_CHARACTER_TEMPLATE },
  scene: { nameKey: 'promptConfig.types.scene', descKey: 'promptConfig.types.sceneDesc', defaultTemplate: '' },
  chapter_split: { nameKey: 'promptConfig.types.chapterSplit', descKey: 'promptConfig.types.chapterSplitDesc', defaultTemplate: DEFAULT_CHAPTER_SPLIT_TEMPLATE },
};

export function usePromptConfigState() {
  const { t } = useTranslation();

  // 各类型模板状态
  const [templatesByType, setTemplatesByType] = useState<Record<TemplateType, PromptTemplate[]>>({
    style: [],
    character_parse: [],
    scene_parse: [],
    character: [],
    scene: [],
    chapter_split: [],
  });
  const [loadingByType, setLoadingByType] = useState<Record<TemplateType, boolean>>({
    style: true,
    character_parse: true,
    scene_parse: true,
    character: true,
    scene: true,
    chapter_split: true,
  });

  // 弹窗状态
  const [showModal, setShowModal] = useState(false);
  const [showViewModal, setShowViewModal] = useState(false);
  const [modalType, setModalType] = useState<TemplateType>('character');
  const [editingPrompt, setEditingPrompt] = useState<PromptTemplate | null>(null);
  const [viewingPrompt, setViewingPrompt] = useState<PromptTemplate | null>(null);
  const [form, setForm] = useState<PromptForm>({
    name: '', description: '', template: DEFAULT_CHARACTER_TEMPLATE, wordCount: 50
  });
  const [saving, setSaving] = useState(false);

  // 加载所有类型的模板
  useEffect(() => {
    const types: TemplateType[] = ['style', 'character_parse', 'scene_parse', 'character', 'scene', 'chapter_split'];
    types.forEach(type => fetchTemplates(type));
  }, []);

  const fetchTemplates = async (type: TemplateType) => {
    setLoadingByType(prev => ({ ...prev, [type]: true }));
    try {
      const data = await promptTemplateApi.fetchList(type);
      if (data.success && data.data) {
        setTemplatesByType(prev => ({ ...prev, [type]: data.data! }));
      }
    } catch (error) {
      console.error(`加载${type}提示词模板失败:`, error);
    } finally {
      setLoadingByType(prev => ({ ...prev, [type]: false }));
    }
  };

  const openModal = useCallback((type: TemplateType, template?: PromptTemplate) => {
    setModalType(type);
    if (template) {
      setEditingPrompt(template);
      let wordCount = 50;
      if (type === 'chapter_split') {
        const numMatch = template.template.match(/必须控制\s*(\d+)\s*字/);
        if (numMatch) wordCount = parseInt(numMatch[1]);
      }
      setForm({ name: template.name, description: template.description, template: template.template, wordCount });
    } else {
      setEditingPrompt(null);
      const config = TEMPLATE_TYPE_CONFIG[type];
      setForm({
        name: '', description: '',
        template: config.defaultTemplate,
        wordCount: 50
      });
    }
    setShowModal(true);
  }, []);

  const openViewModal = useCallback((template: PromptTemplate) => {
    setViewingPrompt(template);
    setShowViewModal(true);
  }, []);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      let templateContent = form.template;
      if (modalType === 'chapter_split') {
        templateContent = templateContent.replace(
          /每个分镜的剧情字数必须控制\s*{?每个分镜对应拆分故事字数}?\s*左右/,
          `每个分镜的剧情字数必须控制 ${form.wordCount} 字左右`
        );
        templateContent = templateContent.replace(/{每个分镜对应拆分故事字数}/g, `${form.wordCount}`);
      }
      const payload = { name: form.name, description: form.description, template: templateContent, type: modalType };
      const data = editingPrompt
        ? await promptTemplateApi.update(editingPrompt.id, payload)
        : await promptTemplateApi.create(payload);
      if (data.success) {
        toast.success(t('common.success'));
        setShowModal(false);
        fetchTemplates(modalType);
      } else {
        toast.error(data.message || t('common.saveFailed'));
      }
    } catch (error) {
      console.error('保存提示词模板失败:', error);
      toast.error(t('common.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const handleCopy = async (template: PromptTemplate) => {
    try {
      const data = await promptTemplateApi.copy(template.id);
      if (data.success) {
        toast.success(t('promptConfig.copySuccess'));
        fetchTemplates(template.type as TemplateType);
      } else {
        toast.error(data.message || t('common.copyFailed'));
      }
    } catch (error) {
      console.error('复制提示词模板失败:', error);
      toast.error(t('common.copyFailed'));
    }
  };

  const handleDelete = async (template: PromptTemplate) => {
    if (!confirm(`${t('promptConfig.confirmDelete')} "${template.name}" ?`)) return;
    try {
      const data = await promptTemplateApi.delete(template.id);
      if (data.success) {
        fetchTemplates(template.type as TemplateType);
      } else {
        toast.error(data.message || t('common.deleteFailed'));
      }
    } catch (error) {
      console.error('删除提示词模板失败:', error);
      toast.error(t('common.deleteFailed'));
    }
  };

  return {
    // State
    templatesByType,
    loadingByType,
    showModal, setShowModal, showViewModal, setShowViewModal,
    modalType, editingPrompt, viewingPrompt,
    form, setForm, saving,
    // Actions
    openModal, openViewModal, handleSave, handleCopy, handleDelete,
    fetchTemplates,
  };
}
