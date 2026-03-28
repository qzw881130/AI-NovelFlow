/**
 * 道具管理页面
 */
import { useState, useEffect, useRef } from 'react';
import { Plus, Search, Trash2, Loader2, Package, Image, X } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import type { Prop, Novel, PromptTemplate } from '../../types';
import { toast } from '../../stores/toastStore';
import { useTranslation } from '../../stores/i18nStore';
import { propApi } from '../../api/props';
import { promptTemplateApi } from '../../api/promptTemplates';
import { api } from '../../api';
import { ImagePreviewModal, PropCard } from './components';
import { ALLOWED_IMAGE_TYPES, POLL_CONFIG, ASPECT_RATIO_CLASSES } from './constants';
import type { PreviewImageState, DeleteAllConfirmDialog, PropPrompt } from './types';

export default function Props() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [props, setProps] = useState<Prop[]>([]);
  const [novels, setNovels] = useState<Novel[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const novelIdFromUrl = searchParams.get('novel') || '';
  const highlightId = searchParams.get('highlight');
  const [selectedNovel, setSelectedNovel] = useState<string>(novelIdFromUrl);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingProp, setEditingProp] = useState<Prop | null>(null);
  const [generatingId, setGeneratingId] = useState<string | null>(null);
  const [highlightedId, setHighlightedId] = useState<string | null>(highlightId);

  const [deleteAllConfirmDialog, setDeleteAllConfirmDialog] = useState<DeleteAllConfirmDialog>({ isOpen: false });
  const [previewImage, setPreviewImage] = useState<PreviewImageState>({ isOpen: false, url: null, name: '', propId: null });
  const [generatingAll, setGeneratingAll] = useState(false);
  const [uploadingId, setUploadingId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [currentUploadPropId, setCurrentUploadPropId] = useState<string | null>(null);
  const [propPrompts, setPropPrompts] = useState<Record<string, PropPrompt>>({});
  const [generatingAppearanceId, setGeneratingAppearanceId] = useState<string | null>(null);
  const [promptTemplates, setPromptTemplates] = useState<PromptTemplate[]>([]);

  const [formData, setFormData] = useState({
    name: '',
    description: '',
    appearance: '',
    novelId: '',
  });

  useEffect(() => {
    fetchProps();
    fetchNovels();
    fetchPromptTemplates();
  }, [selectedNovel]);

  useEffect(() => {
    if (highlightedId && props.length > 0) {
      const element = document.getElementById(`prop-${highlightedId}`);
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setTimeout(() => setHighlightedId(null), 3000);
      }
    }
  }, [highlightedId, props]);

  const fetchPromptTemplates = async () => {
    try {
      const data = await promptTemplateApi.fetchList('prop');
      if (data.success && data.data) {
        setPromptTemplates(data.data);
      }
    } catch (error) {
      console.error('加载提示词模板失败:', error);
    }
  };

  const getTemplateDisplayName = (template: PromptTemplate | undefined): string => {
    if (!template) return t('novels.default');
    if (template.isSystem) {
      return t(`promptConfig.templateNames.${template.name}`, { defaultValue: template.name });
    }
    return template.name;
  };

  const fetchProps = async () => {
    if (!selectedNovel) {
      setProps([]);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    try {
      const data = await propApi.fetchList(selectedNovel);
      if (data.success) {
        setProps(data.data || []);
        const propList = data.data || [];
        for (const prop of propList) {
          fetchPropPrompt(prop.id);
        }
      }
    } catch (error) {
      console.error('获取道具失败:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const fetchPropPrompt = async (propId: string) => {
    try {
      const data = await propApi.fetchPrompt(propId);
      if (data.success) {
        setPropPrompts(prev => ({
          ...prev,
          [propId]: {
            prompt: data.data!.prompt,
            templateName: data.data!.templateName,
            templateId: data.data!.templateId,
            isSystem: data.data!.isSystem
          }
        }));
      }
    } catch (error) {
      console.error('获取道具提示词失败:', error);
    }
  };

  const fetchNovels = async () => {
    try {
      const data = await api.get<Novel[]>('/novels/');
      if (data.success) {
        const novelsList = data.data || [];
        setNovels(novelsList);

        if (!selectedNovel && novelsList.length > 0) {
          const firstNovelId = novelsList[0].id;
          setSelectedNovel(firstNovelId);
          setSearchParams({ novel: firstNovelId });
        }
      }
    } catch (error) {
      console.error('获取小说失败:', error);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const data = await propApi.create({
        novelId: formData.novelId,
        name: formData.name,
        description: formData.description,
        appearance: formData.appearance,
      });
      if (data.success) {
        setProps([data.data!, ...props]);
        setShowCreateModal(false);
        setFormData({ name: '', description: '', appearance: '', novelId: '' });
        toast.success(t('common.create') + t('common.success'));
      }
    } catch (error) {
      console.error('创建道具失败:', error);
      toast.error(t('common.error'));
    }
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingProp) return;

    try {
      const data = await propApi.update(editingProp.id, editingProp);
      if (data.success) {
        setProps(props.map(p => p.id === data.data!.id ? data.data! : p));
        setEditingProp(null);
        toast.success(t('common.save') + t('common.success'));
      }
    } catch (error) {
      console.error('更新道具失败:', error);
      toast.error(t('common.error'));
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm(t('props.confirmDelete', { name: '' }).replace('""', ''))) return;

    try {
      await propApi.delete(id);
      setProps(props.filter(p => p.id !== id));
      toast.success(t('common.delete') + t('common.success'));
    } catch (error) {
      console.error('删除道具失败:', error);
      toast.error(t('common.error'));
    }
  };

  const handleDeleteAllProps = async () => {
    if (!selectedNovel) {
      toast.error(t('props.selectNovel'));
      return;
    }

    try {
      const data = await propApi.deleteAll(selectedNovel);
      if (data.success) {
        toast.success(data.message || t('common.delete') + t('common.success'));
        setProps([]);
        setDeleteAllConfirmDialog({ isOpen: false });
      } else {
        toast.error(data.message || t('common.error'));
      }
    } catch (error) {
      console.error('批量删除道具失败:', error);
      toast.error(t('common.error'));
    }
  };

  const generateAppearance = async (prop: Prop) => {
    if (!prop.description) {
      toast.warning(t('props.appearanceTip'));
      return;
    }

    setGeneratingAppearanceId(prop.id);
    try {
      const data = await propApi.generateAppearance(prop.id);
      if (data.success) {
        setProps(prev => prev.map(p =>
          p.id === prop.id ? { ...p, appearance: data.data!.appearance } : p
        ));
        toast.success(t('props.generateAppearance') + t('common.success'));
      } else {
        toast.error(t('common.error') + ': ' + data.message);
      }
    } catch (error) {
      console.error('生成道具外观失败:', error);
      toast.error(t('common.error'));
    } finally {
      setGeneratingAppearanceId(null);
    }
  };

  const generatePropImage = async (prop: Prop) => {
    if (prop.generatingStatus === 'running') {
      toast.info(t('props.generatingStatus'));
      return;
    }

    setGeneratingId(prop.id);
    try {
      // 使用默认工作流生成道具图片
      const data = await propApi.generateImage(prop.id);
      if (data.success) {
        setProps(prev => prev.map(p =>
          p.id === prop.id ? { ...p, generatingStatus: 'running' } : p
        ));
        toast.success(t('props.generatingStatus'));
        pollPropStatus(prop.id);
      } else {
        toast.error(data.message || t('common.error'));
        setGeneratingId(null);
      }
    } catch (error) {
      console.error('生成道具图片失败:', error);
      toast.error(t('common.error'));
      setGeneratingId(null);
    }
  };

  const pollPropStatus = async (propId: string, maxAttempts = POLL_CONFIG.maxAttempts) => {
    let attempts = 0;
    const interval = setInterval(async () => {
      attempts++;
      if (attempts > maxAttempts) {
        clearInterval(interval);
        setGeneratingId(null);
        toast.warning(t('props.parseTip'));
        return;
      }

      try {
        const data = await propApi.fetch(propId);
        if (data.success && data.data) {
          const prop = data.data;
          setProps(prev => prev.map(p => p.id === propId ? { ...p, ...prop } : p));

          if (prop.generatingStatus === 'completed') {
            clearInterval(interval);
            setGeneratingId(null);
            toast.success(t('props.generateImage') + t('common.success'));
          } else if (prop.generatingStatus === 'failed') {
            clearInterval(interval);
            setGeneratingId(null);
            toast.error(t('props.generateImage') + t('common.error'));
          }
        }
      } catch (error) {
        console.error('轮询状态失败:', error);
      }
    }, POLL_CONFIG.intervalMs);
  };

  const generateAllPropImages = async () => {
    if (filteredProps.length === 0) {
      toast.warning(t('props.noProps'));
      return;
    }

    const propsToGenerate = filteredProps.filter(p => p.generatingStatus !== 'running');

    if (propsToGenerate.length === 0) {
      toast.info(t('props.generatingStatus'));
      return;
    }

    const hasImageCount = propsToGenerate.filter(p => p.imageUrl).length;
    const noImageCount = propsToGenerate.length - hasImageCount;

    let confirmMessage = '';
    if (hasImageCount > 0 && noImageCount > 0) {
      confirmMessage = t('props.confirmGenerateMixed', { newCount: noImageCount, regenCount: hasImageCount });
    } else if (hasImageCount > 0) {
      confirmMessage = t('props.confirmRegenerateCount', { count: hasImageCount });
    } else {
      confirmMessage = t('props.confirmGenerateCount', { count: noImageCount });
    }

    if (!window.confirm(confirmMessage)) return;

    setGeneratingAll(true);

    let successCount = 0;
    let failCount = 0;

    for (const prop of propsToGenerate) {
      try {
        const data = await propApi.generateImage(prop.id);
        if (data.success) {
          successCount++;
          setProps(prev => prev.map(p =>
            p.id === prop.id ? { ...p, generatingStatus: 'running' } : p
          ));
        } else {
          failCount++;
        }
      } catch (error) {
        console.error(`生成道具 ${prop.name} 失败:`, error);
        failCount++;
      }
    }

    setGeneratingAll(false);

    if (successCount > 0) {
      toast.success(`${t('common.success')} ${successCount}`);
      pollAllPropsStatus();
    }
    if (failCount > 0) {
      toast.error(`${t('common.error')} ${failCount}`);
    }
  };

  const pollAllPropsStatus = () => {
    if (!selectedNovel) return;

    const interval = setInterval(async () => {
      try {
        const data = await propApi.fetchList(selectedNovel);
        if (data.success) {
          const propList = data.data || [];
          setProps(propList);

          const generatingPropList = propList.filter((p: Prop) => p.generatingStatus === 'running');

          if (generatingPropList.length === 0) {
            clearInterval(interval);
            toast.success(t('props.generateAllImages') + t('common.success'));
          }
        }
      } catch (error) {
        console.error('轮询状态失败:', error);
      }
    }, POLL_CONFIG.allIntervalMs);
  };

  const triggerFileUpload = (propId: string) => {
    setCurrentUploadPropId(propId);
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const handleUploadImage = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !currentUploadPropId) return;

    if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
      toast.error(t('common.error') + ': 仅支持 PNG, JPG, WEBP 格式');
      return;
    }

    setUploadingId(currentUploadPropId);

    try {
      const data = await propApi.uploadImage(currentUploadPropId, file);
      if (data.success) {
        setProps(prev => prev.map(p =>
          p.id === currentUploadPropId ? { ...p, ...data.data! } : p
        ));
        toast.success(t('props.uploadSuccess'));
      } else {
        toast.error(data.message || t('props.uploadFailed'));
      }
    } catch (error) {
      console.error('上传图片失败:', error);
      toast.error(t('props.uploadFailed'));
    } finally {
      setUploadingId(null);
      setCurrentUploadPropId(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const openImagePreview = (url: string, name: string, propId: string) => {
    setPreviewImage({ isOpen: true, url, name, propId });
  };

  const closeImagePreview = () => {
    setPreviewImage({ isOpen: false, url: null, name: '', propId: null });
  };

  const navigatePreview = (direction: 'prev' | 'next') => {
    if (!previewImage.propId) return;

    const propsWithImages = filteredProps.filter(p => p.imageUrl);
    const currentIndex = propsWithImages.findIndex(p => p.id === previewImage.propId);

    if (currentIndex === -1) return;

    let newIndex: number;
    if (direction === 'prev') {
      newIndex = currentIndex === 0 ? propsWithImages.length - 1 : currentIndex - 1;
    } else {
      newIndex = currentIndex === propsWithImages.length - 1 ? 0 : currentIndex + 1;
    }

    const newProp = propsWithImages[newIndex];
    setPreviewImage({
      isOpen: true,
      url: newProp.imageUrl!,
      name: newProp.name,
      propId: newProp.id
    });
  };

  const filteredProps = props.filter(p =>
    p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    p.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const getNovelAspectRatio = (novelId: string): string => {
    const novel = novels.find(n => n.id === novelId);
    return novel?.aspectRatio || '1:1';
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{t('props.title')}</h1>
          <p className="mt-1 text-sm text-gray-500">{t('props.subtitle')}</p>
        </div>
        <div className="flex gap-3">
          {filteredProps.length > 0 && (
            <button
              onClick={generateAllPropImages}
              disabled={generatingAll}
              className="btn-secondary text-amber-600 border-amber-200 hover:bg-amber-50 disabled:opacity-50"
            >
              {generatingAll ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Image className="mr-2 h-4 w-4" />
              )}
              {t('props.generateAllImages')}
            </button>
          )}
          {selectedNovel && props.length > 0 && (
            <button
              onClick={() => setDeleteAllConfirmDialog({ isOpen: true })}
              className="btn-secondary text-red-600 border-red-200 hover:bg-red-50"
            >
              <Trash2 className="mr-2 h-4 w-4" />
              {t('props.deleteAll')}
            </button>
          )}
          <button
            onClick={() => {
              setFormData({ name: '', description: '', appearance: '', novelId: selectedNovel });
              setShowCreateModal(true);
            }}
            className="btn-primary"
          >
            <Plus className="mr-2 h-4 w-4" />
            {t('common.create')}
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-4">
        <div className="relative flex-[3]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400" />
          <input
            type="text"
            placeholder={t('props.searchProps')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="input-field pl-10 w-full"
          />
        </div>
        <select
          value={selectedNovel}
          onChange={(e) => {
            setSelectedNovel(e.target.value);
            setSearchParams({ novel: e.target.value });
          }}
          className="input-field flex-1"
        >
          {novels.map(novel => (
            <option key={novel.id} value={novel.id}>{novel.title}</option>
          ))}
        </select>
      </div>

      {/* Props Grid */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
        </div>
      ) : filteredProps.length === 0 ? (
        <div className="card text-center py-12">
          <Package className="mx-auto h-12 w-12 text-gray-300" />
          <h3 className="mt-4 text-lg font-medium text-gray-900">{t('props.noProps')}</h3>
          <p className="mt-1 text-sm text-gray-500">{t('props.noPropsTip')}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {filteredProps.map((prop) => {
            const currentNovel = novels.find(n => n.id === selectedNovel);
            const template = promptTemplates.find(pt => pt.id === currentNovel?.propPromptTemplateId);

            return (
              <PropCard
                key={prop.id}
                prop={prop}
                aspectRatio={getNovelAspectRatio(prop.novelId)}
                highlightedId={highlightedId}
                generatingId={generatingId}
                generatingAppearanceId={generatingAppearanceId}
                uploadingId={uploadingId}
                propPrompt={propPrompts[prop.id]}
                templateDisplayName={getTemplateDisplayName(template)}
                onDelete={handleDelete}
                onEdit={setEditingProp}
                onGenerateImage={generatePropImage}
                onGenerateAppearance={generateAppearance}
                onUploadImage={triggerFileUpload}
                onImageClick={openImagePreview}
              />
            );
          })}
        </div>
      )}

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={handleUploadImage}
      />

      {/* Image Preview Modal */}
      <ImagePreviewModal
        isOpen={previewImage.isOpen}
        url={previewImage.url}
        name={previewImage.name}
        onClose={closeImagePreview}
        showNavigation={true}
        totalCount={filteredProps.filter(p => p.imageUrl).length}
        onPrev={() => navigatePreview('prev')}
        onNext={() => navigatePreview('next')}
      />

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full max-h-[90vh] overflow-y-auto">
            <div className="p-4 border-b flex justify-between items-center">
              <h2 className="text-lg font-semibold">{t('props.createProp')}</h2>
              <button onClick={() => setShowCreateModal(false)}>
                <X className="h-5 w-5 text-gray-400" />
              </button>
            </div>
            <form onSubmit={handleCreate} className="p-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('props.name')} *</label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="input-field w-full"
                  required
                  placeholder={t('props.namePlaceholder')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('props.description')}</label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="input-field w-full"
                  rows={3}
                  placeholder={t('props.descriptionPlaceholder')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('props.appearance')}</label>
                <textarea
                  value={formData.appearance}
                  onChange={(e) => setFormData({ ...formData, appearance: e.target.value })}
                  className="input-field w-full"
                  rows={3}
                  placeholder={t('props.appearancePlaceholder')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('props.novel')} *</label>
                <select
                  value={formData.novelId || selectedNovel}
                  onChange={(e) => setFormData({ ...formData, novelId: e.target.value })}
                  className="input-field w-full"
                  required
                >
                  {novels.map(novel => (
                    <option key={novel.id} value={novel.id}>{novel.title}</option>
                  ))}
                </select>
              </div>
              <div className="flex justify-end gap-2 pt-4">
                <button type="button" onClick={() => setShowCreateModal(false)} className="btn-secondary">{t('common.cancel')}</button>
                <button type="submit" className="btn-primary">{t('common.create')}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {editingProp && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full max-h-[90vh] overflow-y-auto">
            <div className="p-4 border-b flex justify-between items-center">
              <h2 className="text-lg font-semibold">{t('props.editProp')}</h2>
              <button onClick={() => setEditingProp(null)}>
                <X className="h-5 w-5 text-gray-400" />
              </button>
            </div>
            <form onSubmit={handleUpdate} className="p-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('props.name')} *</label>
                <input
                  type="text"
                  value={editingProp.name}
                  onChange={(e) => setEditingProp({ ...editingProp, name: e.target.value })}
                  className="input-field w-full"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('props.description')}</label>
                <textarea
                  value={editingProp.description}
                  onChange={(e) => setEditingProp({ ...editingProp, description: e.target.value })}
                  className="input-field w-full"
                  rows={3}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('props.appearance')}</label>
                <textarea
                  value={editingProp.appearance}
                  onChange={(e) => setEditingProp({ ...editingProp, appearance: e.target.value })}
                  className="input-field w-full"
                  rows={3}
                  placeholder={t('props.appearancePlaceholder')}
                />
              </div>
              <div className="flex justify-end gap-2 pt-4">
                <button type="button" onClick={() => setEditingProp(null)} className="btn-secondary">{t('common.cancel')}</button>
                <button type="submit" className="btn-primary">{t('common.save')}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete All Confirm Dialog */}
      {deleteAllConfirmDialog.isOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">{t('props.deleteAllTitle')}</h3>
            <p className="text-sm text-red-600 mb-6">{t('props.deleteAllConfirm')}</p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setDeleteAllConfirmDialog({ isOpen: false })} className="btn-secondary">{t('common.cancel')}</button>
              <button onClick={handleDeleteAllProps} className="btn-primary bg-red-600 hover:bg-red-700">{t('common.confirm')}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}