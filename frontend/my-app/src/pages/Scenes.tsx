import { useState, useEffect } from 'react';
import { 
  Plus, 
  Search, 
  Trash2, 
  Edit2, 
  Loader2,
  MapPin,
  Image,
  RefreshCw,
  X,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  Wand2,
  Sparkles
} from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import type { Scene, Novel } from '../types';
import { toast } from '../stores/toastStore';
import { useTranslation } from '../stores/i18nStore';

// API 基础 URL
const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

interface SceneWithNovel extends Scene {
  novelName?: string;
}

export default function Scenes() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [scenes, setScenes] = useState<SceneWithNovel[]>([]);
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
  
  // 删除所有场景确认对话框状态
  const [deleteAllConfirmDialog, setDeleteAllConfirmDialog] = useState<{
    isOpen: boolean;
  }>({ isOpen: false });
  
  // 图片预览弹窗状态
  const [previewImage, setPreviewImage] = useState<{
    isOpen: boolean;
    url: string | null;
    name: string;
    sceneId: string | null;
  }>({ isOpen: false, url: null, name: '', sceneId: null });
  
  // 批量生成所有场景图
  const [generatingAll, setGeneratingAll] = useState(false);
  
  // 场景提示词
  const [scenePrompts, setScenePrompts] = useState<Record<string, { prompt: string; templateName: string; templateId?: string; isSystem?: boolean }>>({});
  
  // 生成场景设定中的场景ID
  const [generatingSettingId, setGeneratingSettingId] = useState<string | null>(null);
  
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    setting: '',
    novelId: '',
  });

  // 加载场景和小说数据
  useEffect(() => {
    fetchScenes();
    fetchNovels();
  }, [selectedNovel]);

  // 处理高亮场景
  useEffect(() => {
    if (highlightedId && scenes.length > 0) {
      const element = document.getElementById(`scene-${highlightedId}`);
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setTimeout(() => setHighlightedId(null), 3000);
      }
    }
  }, [highlightedId, scenes]);

  // 监听键盘事件
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!previewImage.isOpen) return;
      
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        navigatePreview('prev');
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        navigatePreview('next');
      } else if (e.key === 'Escape') {
        e.preventDefault();
        closeImagePreview();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewImage.isOpen, previewImage.sceneId]);

  const fetchScenes = async () => {
    if (!selectedNovel) {
      setScenes([]);
      setIsLoading(false);
      return;
    }
    
    setIsLoading(true);
    try {
      const url = `${API_BASE}/scenes?novel_id=${selectedNovel}`;
      const res = await fetch(url);
      const data = await res.json();
      if (data.success) {
        setScenes(data.data || []);
        // 加载每个场景的提示词
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
      const res = await fetch(`${API_BASE}/novels/`);
      const data = await res.json();
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
      const res = await fetch(`${API_BASE}/scenes/${sceneId}/prompt`);
      const data = await res.json();
      if (data.success) {
        setScenePrompts(prev => ({
          ...prev,
          [sceneId]: {
            prompt: data.data.prompt,
            templateName: data.data.templateName,
            templateId: data.data.templateId,
            isSystem: data.data.isSystem
          }
        }));
      }
    } catch (error) {
      console.error('获取场景提示词失败:', error);
    }
  };
  
  // 生成场景设定
  const generateSetting = async (scene: Scene) => {
    if (!scene.description) {
      toast.warning(t('scenes.settingTip'));
      return;
    }
    
    setGeneratingSettingId(scene.id);
    try {
      const res = await fetch(`${API_BASE}/scenes/${scene.id}/generate-setting`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await res.json();
      if (data.success) {
        // 更新场景数据
        setScenes(prev => prev.map(s => 
          s.id === scene.id ? { ...s, setting: data.data.setting } : s
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
      const res = await fetch(`${API_BASE}/scenes/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });
      const data = await res.json();
      if (data.success) {
        setScenes([data.data, ...scenes]);
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
      const res = await fetch(`${API_BASE}/scenes/${editingScene.id}/`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editingScene),
      });
      const data = await res.json();
      if (data.success) {
        setScenes(scenes.map(s => s.id === data.data.id ? data.data : s));
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
      await fetch(`${API_BASE}/scenes/${id}/`, { method: 'DELETE' });
      setScenes(scenes.filter(s => s.id !== id));
      toast.success(t('common.delete') + t('common.success'));
    } catch (error) {
      console.error('删除场景失败:', error);
      toast.error(t('common.error'));
    }
  };

  // 删除当前小说的所有场景
  const handleDeleteAllScenes = async () => {
    if (!selectedNovel) {
      toast.error(t('scenes.selectNovel'));
      return;
    }
    
    try {
      const res = await fetch(`${API_BASE}/scenes/?novel_id=${selectedNovel}`, { 
        method: 'DELETE' 
      });
      const data = await res.json();
      
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

  // 生成单个场景图
  const generateSceneImage = async (scene: Scene) => {
    if (scene.generatingStatus === 'running') {
      toast.info(t('scenes.generatingStatus'));
      return;
    }
    
    setGeneratingId(scene.id);
    try {
      const res = await fetch(`${API_BASE}/tasks/scene/${scene.id}/generate-image`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await res.json();
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

  // 轮询检查场景生成状态
  const pollSceneStatus = async (sceneId: string, maxAttempts = 60) => {
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
        const res = await fetch(`${API_BASE}/scenes/${sceneId}`);
        const data = await res.json();
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
    }, 3000);
  };

  // 批量生成所有场景图
  const generateAllSceneImages = async () => {
    if (filteredScenes.length === 0) {
      toast.warning(t('scenes.noScenes'));
      return;
    }
    
    const scenesToGenerate = filteredScenes.filter(
      s => s.generatingStatus !== 'running'
    );
    
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
    
    // 先清空场景图片目录
    try {
      const clearRes = await fetch(`${API_BASE}/scenes/clear-scenes-dir?novel_id=${selectedNovel}`, {
        method: 'POST',
      });
      if (!clearRes.ok) {
        console.warn('清空场景图片目录失败');
      }
    } catch (error) {
      console.error('清空场景图片目录出错:', error);
    }
    
    // 逐个创建场景生成任务
    let successCount = 0;
    let failCount = 0;
    
    for (const scene of scenesToGenerate) {
      try {
        const res = await fetch(`${API_BASE}/tasks/scene/${scene.id}/generate-image`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        });
        const data = await res.json();
        if (data.success) {
          successCount++;
          // 更新场景状态为 running
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

  // 轮询所有生成中的场景状态
  const pollAllScenesStatus = () => {
    if (!selectedNovel) return;
    
    const interval = setInterval(async () => {
      try {
        const url = `${API_BASE}/scenes?novel_id=${selectedNovel}`;
        const res = await fetch(url);
        const data = await res.json();
        if (data.success) {
          const sceneList = data.data || [];
          setScenes(sceneList);
          
          const generatingSceneList = sceneList.filter(
            (s: Scene) => s.generatingStatus === 'running'
          );
          
          if (generatingSceneList.length === 0) {
            clearInterval(interval);
            toast.success(t('scenes.generateAllImages') + t('common.success'));
          }
        }
      } catch (error) {
        console.error('轮询状态失败:', error);
      }
    }, 5000);
  };

  // 打开图片预览
  const openImagePreview = (url: string, name: string, sceneId: string) => {
    setPreviewImage({ isOpen: true, url, name, sceneId });
  };

  // 关闭图片预览
  const closeImagePreview = () => {
    setPreviewImage({ isOpen: false, url: null, name: '', sceneId: null });
  };

  const filteredScenes = scenes.filter(s => 
    s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    s.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // 切换到上一个/下一个场景图片
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

  const getNovelName = (novelId: string) => {
    const novel = novels.find(n => n.id === novelId);
    return novel?.title || t('scenes.selectNovel');
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{t('scenes.title')}</h1>
          <p className="mt-1 text-sm text-gray-500">
            {t('scenes.subtitle')}
          </p>
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
          <p className="mt-1 text-sm text-gray-500">
            {t('scenes.noScenesTip')}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {filteredScenes.map((scene) => (
            <div
              key={scene.id}
              id={`scene-${scene.id}`}
              className={`bg-white rounded-lg shadow-sm border overflow-hidden hover:shadow-md transition-all group ${
                highlightedId === scene.id 
                  ? 'ring-4 ring-blue-500 ring-opacity-50 border-blue-500 animate-pulse' 
                  : 'border-gray-200'
              }`}
            >
              {/* Scene Image */}
              <div className="relative aspect-video bg-gray-100 w-full">
                {scene.imageUrl ? (
                  <img
                    src={scene.imageUrl}
                    alt={scene.name}
                    className="w-full h-full object-cover cursor-pointer"
                    onClick={() => openImagePreview(scene.imageUrl!, scene.name, scene.id)}
                  />
                ) : (
                  <div className="absolute inset-0 flex items-center justify-center">
                    <MapPin className="h-20 w-20 text-gray-300" />
                  </div>
                )}
                
                {/* Status Badge */}
                {scene.generatingStatus === 'running' && (
                  <div className="absolute top-2 left-2 px-2 py-1 bg-blue-500 text-white text-xs rounded-full flex items-center gap-1">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    {t('scenes.generating')}
                  </div>
                )}
                {scene.generatingStatus === 'failed' && (
                  <div className="absolute top-2 left-2 px-2 py-1 bg-red-500 text-white text-xs rounded-full">
                    {t('scenes.generateFailed')}
                  </div>
                )}
                
                {/* Delete Button - 右上角 */}
                <button
                  onClick={() => handleDelete(scene.id)}
                  className="absolute top-2 right-2 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100"
                  title={t('common.delete')}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
                
                {/* Edit Button - 左下角 */}
                <button
                  onClick={() => setEditingScene(scene)}
                  className="absolute bottom-2 left-2 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors opacity-0 group-hover:opacity-100"
                  title={t('common.edit')}
                >
                  <Edit2 className="h-4 w-4" />
                </button>
                
                {/* AI生成场景图 Button - 右下角，带文字 */}
                <button
                  onClick={() => generateSceneImage(scene)}
                  disabled={generatingId === scene.id || scene.generatingStatus === 'running'}
                  className="absolute bottom-2 right-2 flex items-center gap-1 px-3 py-1.5 bg-green-600/90 hover:bg-green-700 text-white rounded-lg transition-colors disabled:opacity-70 opacity-0 group-hover:opacity-100 text-xs"
                  title={scene.generatingStatus === 'running' ? t('scenes.generatingStatus') : (scene.imageUrl ? t('scenes.regenerate') : t('scenes.generateImage'))}
                >
                  {scene.generatingStatus === 'running' || generatingId === scene.id ? (
                    <>
                      <Loader2 className="h-3 w-3 animate-spin" />
                      <span>{t('scenes.generatingStatus')}</span>
                    </>
                  ) : (
                    <>
                      <Wand2 className="h-3 w-3" />
                      <span>AI{t('scenes.generateImage')}</span>
                    </>
                  )}
                </button>
                
                {/* Loading Overlay */}
                {generatingId === scene.id && (
                  <div className="absolute inset-0 bg-black bg-opacity-50 flex items-center justify-center">
                    <div className="text-center">
                      <Loader2 className="h-8 w-8 animate-spin text-white mx-auto" />
                      <p className="text-white text-sm mt-2">{t('scenes.generating')}</p>
                    </div>
                  </div>
                )}
              </div>

              {/* Scene Info */}
              <div className="p-4">
                <h3 className="text-lg font-semibold text-gray-900 truncate">
                  {scene.name}
                </h3>
                
                {/* 场景描述 - 可滚动显示完整内容 */}
                {scene.description && (
                  <div className="mt-3">
                    <p className="text-xs text-gray-400 mb-1">{t('scenes.descriptionLabel')}</p>
                    <div className="text-sm text-gray-600 max-h-20 overflow-y-auto pr-1 scrollbar-thin">
                      {scene.description}
                    </div>
                  </div>
                )}
                
                {/* 环境设定 - 可滚动显示完整内容 */}
                {scene.setting ? (
                  <div className="mt-3">
                    <p className="text-xs text-gray-400 mb-1">{t('scenes.setting')}</p>
                    <div className="text-xs text-gray-500 bg-gray-50 rounded p-2 max-h-24 overflow-y-auto scrollbar-thin">
                      {scene.setting}
                    </div>
                  </div>
                ) : (
                  <div className="mt-3">
                    <button
                      onClick={() => generateSetting(scene)}
                      disabled={generatingSettingId === scene.id || !scene.description}
                      className="text-xs inline-flex items-center text-primary-600 hover:text-primary-700 disabled:opacity-50"
                    >
                      {generatingSettingId === scene.id ? (
                        <>
                          <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                          {t('scenes.generatingStatus')}
                        </>
                      ) : (
                        <>
                          <Sparkles className="h-3 w-3 mr-1" />
                          {t('scenes.generateSetting')}
                        </>
                      )}
                    </button>
                  </div>
                )}

                {/* 生成提示词 */}
                {scenePrompts[scene.id] && (
                  <div className="mt-3 pt-3 border-t border-gray-100">
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-xs text-gray-400">{t('scenes.promptLabel')}</p>
                      <span className="text-xs text-gray-400">
                        {scenePrompts[scene.id].isSystem 
                          ? t(`promptConfig.templateNames.${scenePrompts[scene.id].templateName}`, { defaultValue: scenePrompts[scene.id].templateName })
                          : scenePrompts[scene.id].templateName
                        }
                      </span>
                    </div>
                    <div className="text-xs text-gray-500 bg-gray-50 rounded p-2 max-h-20 overflow-y-auto scrollbar-thin font-mono">
                      {scenePrompts[scene.id].prompt}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

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
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('scenes.name')} *
                </label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="input-field w-full"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('scenes.description')}
                </label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="input-field w-full"
                  rows={3}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('scenes.setting')}
                </label>
                <textarea
                  value={formData.setting}
                  onChange={(e) => setFormData({ ...formData, setting: e.target.value })}
                  className="input-field w-full"
                  rows={3}
                  placeholder={t('scenes.settingPlaceholder')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('scenes.novel')} *
                </label>
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
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="btn-secondary"
                >
                  {t('common.cancel')}
                </button>
                <button type="submit" className="btn-primary">
                  {t('common.create')}
                </button>
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
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('scenes.name')} *
                </label>
                <input
                  type="text"
                  value={editingScene.name}
                  onChange={(e) => setEditingScene({ ...editingScene, name: e.target.value })}
                  className="input-field w-full"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('scenes.description')}
                </label>
                <textarea
                  value={editingScene.description}
                  onChange={(e) => setEditingScene({ ...editingScene, description: e.target.value })}
                  className="input-field w-full"
                  rows={3}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('scenes.setting')}
                </label>
                <textarea
                  value={editingScene.setting}
                  onChange={(e) => setEditingScene({ ...editingScene, setting: e.target.value })}
                  className="input-field w-full"
                  rows={3}
                />
              </div>
              <div className="flex justify-end gap-2 pt-4">
                <button
                  type="button"
                  onClick={() => setEditingScene(null)}
                  className="btn-secondary"
                >
                  {t('common.cancel')}
                </button>
                <button type="submit" className="btn-primary">
                  {t('common.save')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete All Confirm Dialog */}
      {deleteAllConfirmDialog.isOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6">
            <div className="flex items-center gap-3 mb-4">
              <AlertTriangle className="h-6 w-6 text-red-500" />
              <h2 className="text-lg font-semibold">{t('scenes.deleteAllTitle')}</h2>
            </div>
            <p className="text-gray-600 mb-6">
              {t('scenes.deleteAllConfirm')}
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setDeleteAllConfirmDialog({ isOpen: false })}
                className="btn-secondary"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleDeleteAllScenes}
                className="btn-danger"
              >
                {t('common.delete')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Image Preview Modal */}
      {previewImage.isOpen && previewImage.url && (
        <div 
          className="fixed inset-0 bg-black/90 flex items-center justify-center z-50"
          onClick={closeImagePreview}
        >
          <button
            onClick={(e) => { e.stopPropagation(); navigatePreview('prev'); }}
            className="absolute left-4 text-white/70 hover:text-white p-2"
          >
            <ChevronLeft className="h-8 w-8" />
          </button>
          
          <div className="max-w-5xl max-h-[90vh] relative" onClick={e => e.stopPropagation()}>
            <img
              src={previewImage.url}
              alt={previewImage.name}
              className="max-w-full max-h-[90vh] object-contain"
            />
            <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 to-transparent p-4">
              <h3 className="text-white font-medium">{previewImage.name}</h3>
            </div>
          </div>
          
          <button
            onClick={(e) => { e.stopPropagation(); navigatePreview('next'); }}
            className="absolute right-4 text-white/70 hover:text-white p-2"
          >
            <ChevronRight className="h-8 w-8" />
          </button>
          
          <button
            onClick={closeImagePreview}
            className="absolute top-4 right-4 text-white/70 hover:text-white"
          >
            <X className="h-6 w-6" />
          </button>
        </div>
      )}
    </div>
  );
}
