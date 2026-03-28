/**
 * 场景管理页面
 */
import { useState, useEffect, useRef } from 'react';
import { Plus, Search, Trash2, Loader2, MapPin, Image, X } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import type { Scene, Novel, PromptTemplate } from '../../types';
import { toast } from '../../stores/toastStore';
import { useTranslation } from '../../stores/i18nStore';
import { sceneApi } from '../../api/scenes';
import { promptTemplateApi } from '../../api/promptTemplates';
import { api } from '../../api';
import { ImagePreviewModal, SceneCard } from './components';
import { ALLOWED_IMAGE_TYPES, POLL_CONFIG } from './constants';
import type { ScenePrompt, PreviewImageState, DeleteAllConfirmDialog } from './types';

export default function Scenes() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [novels, setNovels] = useState<Novel[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const novelIdFromUrl = searchParams.get('novel') || '';
  const highlightId = searchParams.get('highlight');
  const [selectedNovel, setSelectedNovel] = useState<string>(novelIdFromUrl);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingScene, setEditingScene] = useState<Scene | null>(null);
  const [generatingId, setGeneratingId] = useState<string | null>(null);
  const [highlightedId, setHighlightedId] = useState<string | null>(highlightId);
  
  const [deleteAllConfirmDialog, setDeleteAllConfirmDialog] = useState<DeleteAllConfirmDialog>({ isOpen: false });
  const [previewImage, setPreviewImage] = useState<PreviewImageState>({ isOpen: false, url: null, name: '', sceneId: null });
  const [generatingAll, setGeneratingAll] = useState(false);
  const [uploadingId, setUploadingId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [currentUploadSceneId, setCurrentUploadSceneId] = useState<string | null>(null);
  const [scenePrompts, setScenePrompts] = useState<Record<string, ScenePrompt>>({});
  const [generatingSettingId, setGeneratingSettingId] = useState<string | null>(null);
  const [promptTemplates, setPromptTemplates] = useState<PromptTemplate[]>([]);
  
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    setting: '',
    novelId: '',
  });

  useEffect(() => {
    fetchScenes();
    fetchNovels();
    fetchPromptTemplates();
  }, [selectedNovel]);
  
  const fetchPromptTemplates = async () => {
    try {
      const data = await promptTemplateApi.fetchList('character');
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

  useEffect(() => {
    if (highlightedId && scenes.length > 0) {
      const element = document.getElementById(`scene-${highlightedId}`);
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setTimeout(() => setHighlightedId(null), 3000);
      }
    }
  }, [highlightedId, scenes]);

  const fetchScenes = async () => {
    if (!selectedNovel) {
      setScenes([]);
      setIsLoading(false);
      return;
    }
    
    setIsLoading(true);
    try {
      const data = await sceneApi.fetchList(selectedNovel);
      if (data.success) {
        setScenes(data.data || []);
        const sceneList = data.data || [];
        for (const scene of sceneList) {
          fetchScenePrompt(scene.id);
        }
      }
    } catch (error) {
      console.error('获取场景失败:', error);
    } finally {
      setIsLoading(false);
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
  
  const fetchScenePrompt = async (sceneId: string) => {
    try {
      const data = await sceneApi.fetchPrompt(sceneId);
      if (data.success) {
        setScenePrompts(prev => ({
          ...prev,
          [sceneId]: {
            prompt: data.data!.prompt,
            templateName: data.data!.templateName,
            templateId: data.data!.templateId,
            isSystem: data.data!.isSystem
          }
        }));
      }
    } catch (error) {
      console.error('获取场景提示词失败:', error);
    }
  };
  
  const generateSetting = async (scene: Scene) => {
    if (!scene.description) {
      toast.warning(t('scenes.settingTip'));
      return;
    }
    
    setGeneratingSettingId(scene.id);
    try {
      const data = await sceneApi.generateSetting(scene.id);
      if (data.success) {
        setScenes(prev => prev.map(s => 
          s.id === scene.id ? { ...s, setting: data.data!.setting } : s
        ));
        toast.success(t('scenes.generateSetting') + t('common.success'));
      } else {
        toast.error(t('common.error') + ': ' + data.message);
      }
    } catch (error) {
      console.error('生成场景设定失败:', error);
      toast.error(t('common.error'));
    } finally {
      setGeneratingSettingId(null);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const data = await sceneApi.create({
        novelId: formData.novelId,
        name: formData.name,
        description: formData.description,
        setting: formData.setting,
      });
      if (data.success) {
        setScenes([data.data!, ...scenes]);
        setShowCreateModal(false);
        setFormData({ name: '', description: '', setting: '', novelId: '' });
        toast.success(t('common.create') + t('common.success'));
      }
    } catch (error) {
      console.error('创建场景失败:', error);
      toast.error(t('common.error'));
    }
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingScene) return;
    
    try {
      const data = await sceneApi.update(editingScene.id, editingScene);
      if (data.success) {
        setScenes(scenes.map(s => s.id === data.data!.id ? data.data! : s));
        setEditingScene(null);
        toast.success(t('common.save') + t('common.success'));
      }
    } catch (error) {
      console.error('更新场景失败:', error);
      toast.error(t('common.error'));
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm(t('scenes.confirmDelete', { name: '' }).replace('""', ''))) return;
    
    try {
      await sceneApi.delete(id);
      setScenes(scenes.filter(s => s.id !== id));
      toast.success(t('common.delete') + t('common.success'));
    } catch (error) {
      console.error('删除场景失败:', error);
      toast.error(t('common.error'));
    }
  };

  const handleDeleteAllScenes = async () => {
    if (!selectedNovel) {
      toast.error(t('scenes.selectNovel'));
      return;
    }
    
    try {
      const data = await sceneApi.deleteAll(selectedNovel);
      if (data.success) {
        toast.success(data.message || t('common.delete') + t('common.success'));
        setScenes([]);
        setDeleteAllConfirmDialog({ isOpen: false });
      } else {
        toast.error(data.message || t('common.error'));
      }
    } catch (error) {
      console.error('批量删除场景失败:', error);
      toast.error(t('common.error'));
    }
  };

  const generateSceneImage = async (scene: Scene) => {
    if (scene.generatingStatus === 'running') {
      toast.info(t('scenes.generatingStatus'));
      return;
    }
    
    setGeneratingId(scene.id);
    try {
      const data = await sceneApi.generateImage(scene.id);
      if (data.success) {
        setScenes(prev => prev.map(s => 
          s.id === scene.id ? { ...s, generatingStatus: 'running' } : s
        ));
        toast.success(t('scenes.generatingStatus'));
        pollSceneStatus(scene.id);
      } else {
        toast.error(data.message || t('common.error'));
        setGeneratingId(null);
      }
    } catch (error) {
      console.error('生成场景图失败:', error);
      toast.error(t('common.error'));
      setGeneratingId(null);
    }
  };

  const pollSceneStatus = async (sceneId: string, maxAttempts = POLL_CONFIG.maxAttempts) => {
    let attempts = 0;
    const interval = setInterval(async () => {
      attempts++;
      if (attempts > maxAttempts) {
        clearInterval(interval);
        setGeneratingId(null);
        toast.warning(t('scenes.parseTip'));
        return;
      }
      
      try {
        const data = await sceneApi.fetch(sceneId);
        if (data.success && data.data) {
          const scene = data.data;
          setScenes(prev => prev.map(s => s.id === sceneId ? { ...s, ...scene } : s));
          
          if (scene.generatingStatus === 'completed') {
            clearInterval(interval);
            setGeneratingId(null);
            toast.success(t('scenes.generateImage') + t('common.success'));
          } else if (scene.generatingStatus === 'failed') {
            clearInterval(interval);
            setGeneratingId(null);
            toast.error(t('scenes.generateImage') + t('common.error'));
          }
        }
      } catch (error) {
        console.error('轮询状态失败:', error);
      }
    }, POLL_CONFIG.intervalMs);
  };

  const generateAllSceneImages = async () => {
    if (filteredScenes.length === 0) {
      toast.warning(t('scenes.noScenes'));
      return;
    }
    
    const scenesToGenerate = filteredScenes.filter(s => s.generatingStatus !== 'running');
    
    if (scenesToGenerate.length === 0) {
      toast.info(t('scenes.generatingStatus'));
      return;
    }
    
    const hasImageCount = scenesToGenerate.filter(s => s.imageUrl).length;
    const noImageCount = scenesToGenerate.length - hasImageCount;
    
    let confirmMessage = '';
    if (hasImageCount > 0 && noImageCount > 0) {
      confirmMessage = t('scenes.confirmGenerateMixed', { newCount: noImageCount, regenCount: hasImageCount });
    } else if (hasImageCount > 0) {
      confirmMessage = t('scenes.confirmRegenerateCount', { count: hasImageCount });
    } else {
      confirmMessage = t('scenes.confirmGenerateCount', { count: noImageCount });
    }
    
    if (!window.confirm(confirmMessage)) return;
    
    setGeneratingAll(true);
    
    try {
      await sceneApi.clearImagesDir(selectedNovel);
    } catch (error) {
      console.error('清空场景图片目录出错:', error);
    }
    
    let successCount = 0;
    let failCount = 0;
    
    for (const scene of scenesToGenerate) {
      try {
        const data = await sceneApi.generateImage(scene.id);
        if (data.success) {
          successCount++;
          setScenes(prev => prev.map(s => 
            s.id === scene.id ? { ...s, generatingStatus: 'running' } : s
          ));
        } else {
          failCount++;
          console.error(`场景 ${scene.name} 创建任务失败:`, data.message);
        }
      } catch (error) {
        failCount++;
        console.error(`场景 ${scene.name} 创建任务出错:`, error);
      }
    }
    
    if (successCount > 0) {
      toast.success(`已创建 ${successCount} 个场景图生成任务`);
      pollAllScenesStatus();
    }
    
    if (failCount > 0) {
      toast.error(`${failCount} 个场景创建任务失败`);
    }
    
    setGeneratingAll(false);
  };

  const pollAllScenesStatus = () => {
    if (!selectedNovel) return;
    
    const interval = setInterval(async () => {
      try {
        const data = await sceneApi.fetchList(selectedNovel);
        if (data.success) {
          const sceneList = data.data || [];
          setScenes(sceneList);
          
          const generatingSceneList = sceneList.filter((s: Scene) => s.generatingStatus === 'running');
          
          if (generatingSceneList.length === 0) {
            clearInterval(interval);
            toast.success(t('scenes.generateAllImages') + t('common.success'));
          }
        }
      } catch (error) {
        console.error('轮询状态失败:', error);
      }
    }, POLL_CONFIG.allIntervalMs);
  };

  const triggerFileUpload = (sceneId: string) => {
    setCurrentUploadSceneId(sceneId);
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const handleUploadImage = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !currentUploadSceneId) return;
    
    if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
      toast.error(t('common.error') + ': 仅支持 PNG, JPG, WEBP 格式');
      return;
    }
    
    setUploadingId(currentUploadSceneId);
    
    try {
      const data = await sceneApi.uploadImage(currentUploadSceneId, file);
      if (data.success) {
        setScenes(prev => prev.map(s => 
          s.id === currentUploadSceneId ? { ...s, ...data.data! } : s
        ));
        toast.success(t('scenes.uploadSuccess'));
      } else {
        toast.error(data.message || t('scenes.uploadFailed'));
      }
    } catch (error) {
      console.error('上传图片失败:', error);
      toast.error(t('scenes.uploadFailed'));
    } finally {
      setUploadingId(null);
      setCurrentUploadSceneId(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const openImagePreview = (url: string, name: string, sceneId: string) => {
    setPreviewImage({ isOpen: true, url, name, sceneId });
  };

  const closeImagePreview = () => {
    setPreviewImage({ isOpen: false, url: null, name: '', sceneId: null });
  };

  const navigatePreview = (direction: 'prev' | 'next') => {
    if (!previewImage.sceneId) return;
    
    const scenesWithImages = filteredScenes.filter(s => s.imageUrl);
    const currentIndex = scenesWithImages.findIndex(s => s.id === previewImage.sceneId);
    
    if (currentIndex === -1) return;
    
    let newIndex: number;
    if (direction === 'prev') {
      newIndex = currentIndex === 0 ? scenesWithImages.length - 1 : currentIndex - 1;
    } else {
      newIndex = currentIndex === scenesWithImages.length - 1 ? 0 : currentIndex + 1;
    }
    
    const newScene = scenesWithImages[newIndex];
    setPreviewImage({
      isOpen: true,
      url: newScene.imageUrl!,
      name: newScene.name,
      sceneId: newScene.id
    });
  };

  const filteredScenes = scenes.filter(s => 
    s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    s.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{t('scenes.title')}</h1>
          <p className="mt-1 text-sm text-gray-500">{t('scenes.subtitle')}</p>
        </div>
        <div className="flex gap-3">
          {filteredScenes.length > 0 && (
            <button
              onClick={generateAllSceneImages}
              disabled={generatingAll}
              className="btn-secondary text-green-600 border-green-200 hover:bg-green-50 disabled:opacity-50"
            >
              {generatingAll ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Image className="mr-2 h-4 w-4" />
              )}
              {t('scenes.generateAllImages')}
            </button>
          )}
          {selectedNovel && scenes.length > 0 && (
            <button
              onClick={() => setDeleteAllConfirmDialog({ isOpen: true })}
              className="btn-secondary text-red-600 border-red-200 hover:bg-red-50"
            >
              <Trash2 className="mr-2 h-4 w-4" />
              {t('scenes.deleteAll')}
            </button>
          )}
          <button
            onClick={() => {
              setFormData({ ...formData, novelId: selectedNovel });
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
            placeholder={t('scenes.searchScenes')}
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

      {/* Scenes Grid */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
        </div>
      ) : filteredScenes.length === 0 ? (
        <div className="card text-center py-12">
          <MapPin className="mx-auto h-12 w-12 text-gray-300" />
          <h3 className="mt-4 text-lg font-medium text-gray-900">{t('scenes.noScenes')}</h3>
          <p className="mt-1 text-sm text-gray-500">{t('scenes.noScenesTip')}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {filteredScenes.map((scene) => {
            const currentNovel = novels.find(n => n.id === selectedNovel);
            const template = promptTemplates.find(pt => pt.id === currentNovel?.promptTemplateId);
            
            return (
              <SceneCard
                key={scene.id}
                scene={scene}
                highlightedId={highlightedId}
                generatingId={generatingId}
                generatingSettingId={generatingSettingId}
                uploadingId={uploadingId}
                scenePrompt={scenePrompts[scene.id]}
                templateDisplayName={getTemplateDisplayName(template)}
                onDelete={handleDelete}
                onEdit={setEditingScene}
                onGenerateImage={generateSceneImage}
                onGenerateSetting={generateSetting}
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
        totalCount={filteredScenes.filter(s => s.imageUrl).length}
        onPrev={() => navigatePreview('prev')}
        onNext={() => navigatePreview('next')}
      />

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full max-h-[90vh] overflow-y-auto">
            <div className="p-4 border-b flex justify-between items-center">
              <h2 className="text-lg font-semibold">{t('scenes.createScene')}</h2>
              <button onClick={() => setShowCreateModal(false)}>
                <X className="h-5 w-5 text-gray-400" />
              </button>
            </div>
            <form onSubmit={handleCreate} className="p-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('scenes.name')} *</label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="input-field w-full"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('scenes.description')}</label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="input-field w-full"
                  rows={3}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('scenes.setting')}</label>
                <textarea
                  value={formData.setting}
                  onChange={(e) => setFormData({ ...formData, setting: e.target.value })}
                  className="input-field w-full"
                  rows={3}
                  placeholder={t('scenes.settingPlaceholder')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('scenes.novel')} *</label>
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
      {editingScene && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full max-h-[90vh] overflow-y-auto">
            <div className="p-4 border-b flex justify-between items-center">
              <h2 className="text-lg font-semibold">{t('scenes.editScene')}</h2>
              <button onClick={() => setEditingScene(null)}>
                <X className="h-5 w-5 text-gray-400" />
              </button>
            </div>
            <form onSubmit={handleUpdate} className="p-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('scenes.name')} *</label>
                <input
                  type="text"
                  value={editingScene.name}
                  onChange={(e) => setEditingScene({ ...editingScene, name: e.target.value })}
                  className="input-field w-full"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('scenes.description')}</label>
                <textarea
                  value={editingScene.description}
                  onChange={(e) => setEditingScene({ ...editingScene, description: e.target.value })}
                  className="input-field w-full"
                  rows={3}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('scenes.setting')}</label>
                <textarea
                  value={editingScene.setting}
                  onChange={(e) => setEditingScene({ ...editingScene, setting: e.target.value })}
                  className="input-field w-full"
                  rows={3}
                />
              </div>
              <div className="flex justify-end gap-2 pt-4">
                <button type="button" onClick={() => setEditingScene(null)} className="btn-secondary">{t('common.cancel')}</button>
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
            <h3 className="text-lg font-semibold text-gray-900 mb-4">{t('scenes.deleteAllTitle')}</h3>
            <p className="text-sm text-red-600 mb-6">{t('scenes.deleteAllConfirm')}</p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setDeleteAllConfirmDialog({ isOpen: false })} className="btn-secondary">{t('common.cancel')}</button>
              <button onClick={handleDeleteAllScenes} className="btn-primary bg-red-600 hover:bg-red-700">{t('common.confirm')}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
