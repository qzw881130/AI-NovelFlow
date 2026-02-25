import { useState, useEffect, useRef } from 'react';
import { 
  Plus, 
  Search, 
  Trash2, 
  Edit2, 
  Loader2,
  User,
  Wand2,
  Sparkles,
  RefreshCw,
  X,
  Image,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  Upload
} from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import type { Character, Novel } from '../types';
import { toast } from '../stores/toastStore';
import { useTranslation } from '../stores/i18nStore';

// API 基础 URL
const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

interface CharacterWithNovel extends Character {
  novelName?: string;
}

export default function Characters() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [characters, setCharacters] = useState<CharacterWithNovel[]>([]);
  const [novels, setNovels] = useState<Novel[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  // 支持 novel 或 novel_id 参数（不再支持 'all'，必须选择具体小说）
  const novelIdFromUrl = searchParams.get('novel') || searchParams.get('novel_id') || '';
  const highlightId = searchParams.get('highlight');
  const [selectedNovel, setSelectedNovel] = useState<string>(novelIdFromUrl);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingCharacter, setEditingCharacter] = useState<Character | null>(null);
  const [generatingId, setGeneratingId] = useState<string | null>(null);
  const [generatingAppearanceId, setGeneratingAppearanceId] = useState<string | null>(null);
  const [characterPrompts, setCharacterPrompts] = useState<Record<string, { prompt: string; templateName: string; templateId?: string; isSystem?: boolean }>>({});
  const [highlightedId, setHighlightedId] = useState<string | null>(highlightId);
  const [parsingNovelId, setParsingNovelId] = useState<string | null>(null);
  
  // 删除所有角色确认对话框状态
  const [deleteAllConfirmDialog, setDeleteAllConfirmDialog] = useState<{
    isOpen: boolean;
  }>({ isOpen: false });
  
  // 图片预览弹窗状态
  const [previewImage, setPreviewImage] = useState<{
    isOpen: boolean;
    url: string | null;
    name: string;
    characterId: string | null;
  }>({ isOpen: false, url: null, name: '', characterId: null });
  
  // 批量生成所有角色形象
  const [generatingAll, setGeneratingAll] = useState(false);
  
  // 上传状态
  const [uploadingId, setUploadingId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [currentUploadCharacterId, setCurrentUploadCharacterId] = useState<string | null>(null);
  
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    appearance: '',
    novelId: '',
  });

  // 加载角色和小说数据
  useEffect(() => {
    fetchCharacters();
    fetchNovels();
  }, [selectedNovel]);

  // 处理高亮角色 - 滚动到对应位置并添加高亮效果
  useEffect(() => {
    if (highlightedId && characters.length > 0) {
      const element = document.getElementById(`character-${highlightedId}`);
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        // 3秒后移除高亮效果
        setTimeout(() => setHighlightedId(null), 3000);
      }
    }
  }, [highlightedId, characters]);

  // 监听键盘事件 - 图片预览左右切换（在 filteredCharacters 定义后初始化）
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
  }, [previewImage.isOpen, previewImage.characterId]);

  const fetchCharacters = async () => {
    // 如果没有选择小说，不获取角色
    if (!selectedNovel) {
      setCharacters([]);
      setIsLoading(false);
      return;
    }
    
    setIsLoading(true);
    try {
      const url = `${API_BASE}/characters?novel_id=${selectedNovel}`;
      const res = await fetch(url);
      const data = await res.json();
      if (data.success) {
        setCharacters(data.data || []);
        // 加载每个角色的提示词
        const chars = data.data || [];
        for (const char of chars) {
          fetchCharacterPrompt(char.id);
        }
      }
    } catch (error) {
      console.error('获取角色失败:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const fetchCharacterPrompt = async (characterId: string) => {
    try {
      const res = await fetch(`${API_BASE}/characters/${characterId}/prompt/`);
      const data = await res.json();
      if (data.success) {
        setCharacterPrompts(prev => ({
          ...prev,
          [characterId]: {
            prompt: data.data.prompt,
            templateName: data.data.templateName,
            templateId: data.data.templateId,
            isSystem: data.data.isSystem
          }
        }));
      }
    } catch (error) {
      console.error('获取角色提示词失败:', error);
    }
  };

  const fetchNovels = async () => {
    try {
      const res = await fetch(`${API_BASE}/novels/`);
      const data = await res.json();
      if (data.success) {
        const novelsList = data.data || [];
        setNovels(novelsList);
        
        // 如果没有选择小说，默认选择第一个
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
      const res = await fetch(`${API_BASE}/characters/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });
      const data = await res.json();
      if (data.success) {
        setCharacters([data.data, ...characters]);
        setShowCreateModal(false);
        setFormData({ name: '', description: '', appearance: '', novelId: '' });
      }
    } catch (error) {
      console.error('创建角色失败:', error);
    }
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingCharacter) return;
    
    try {
      const res = await fetch(`${API_BASE}/characters/${editingCharacter.id}/`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editingCharacter),
      });
      const data = await res.json();
      if (data.success) {
        setCharacters(characters.map(c => c.id === data.data.id ? data.data : c));
        setEditingCharacter(null);
      }
    } catch (error) {
      console.error('更新角色失败:', error);
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm(t('characters.confirmDelete', { name: '' }).replace('""', ''))) return;
    
    try {
      await fetch(`${API_BASE}/characters/${id}/`, { method: 'DELETE' });
      setCharacters(characters.filter(c => c.id !== id));
    } catch (error) {
      console.error('删除角色失败:', error);
    }
  };

  // 删除当前小说的所有角色
  const handleDeleteAllCharacters = async () => {
    if (!selectedNovel) {
      toast.error(t('characters.selectNovel'));
      return;
    }
    
    try {
      const res = await fetch(`${API_BASE}/characters/?novel_id=${selectedNovel}`, { 
        method: 'DELETE' 
      });
      const data = await res.json();
      
      if (data.success) {
        toast.success(data.message || t('common.delete') + t('common.success'));
        setCharacters([]); // 清空本地角色列表
        setDeleteAllConfirmDialog({ isOpen: false });
      } else {
        toast.error(data.message || t('common.delete') + t('common.error'));
      }
    } catch (error) {
      console.error('批量删除角色失败:', error);
      toast.error(t('common.delete') + t('common.error'));
    }
  };

  const generateAppearance = async (character: Character) => {
    if (!character.description) {
      toast.warning(t('characters.appearanceTip'));
      return;
    }
    
    setGeneratingAppearanceId(character.id);
    try {
      const res = await fetch(`${API_BASE}/characters/${character.id}/generate-appearance/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await res.json();
      if (data.success) {
        // 更新角色数据
        setCharacters(prev => prev.map(c => 
          c.id === character.id ? { ...c, appearance: data.data.appearance } : c
        ));
        toast.success(t('characters.generateAppearance') + t('common.success'));
      } else {
        toast.error(t('common.error') + ': ' + data.message);
      }
    } catch (error) {
      console.error('生成外貌描述失败:', error);
      toast.error(t('common.error'));
    } finally {
      setGeneratingAppearanceId(null);
    }
  };

  const generatePortrait = async (character: Character) => {
    // 检查是否已经在生成中
    if (character.generatingStatus === 'running') {
      toast.info(t('characters.generatingStatus'));
      return;
    }
    
    setGeneratingId(character.id);
    try {
      // 调用任务API创建设定图生成任务
      const res = await fetch(`${API_BASE}/tasks/character/${character.id}/generate-portrait/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await res.json();
      if (data.success) {
        // 更新本地状态为生成中
        setCharacters(prev => prev.map(c => 
          c.id === character.id ? { ...c, generatingStatus: 'running' } : c
        ));
        toast.success(t('characters.generatingStatus'));
        
        // 开始轮询检查生成状态
        pollCharacterStatus(character.id);
      } else {
        toast.error(data.message || t('common.error'));
        setGeneratingId(null);
      }
    } catch (error) {
      console.error('生成人设图失败:', error);
      toast.error(t('common.error'));
      setGeneratingId(null);
    }
  };

  // 轮询检查角色生成状态
  const pollCharacterStatus = async (characterId: string, maxAttempts = 60) => {
    let attempts = 0;
    const interval = setInterval(async () => {
      attempts++;
      if (attempts > maxAttempts) {
        clearInterval(interval);
        setGeneratingId(null);
        toast.warning(t('characters.parseTip'));
        return;
      }
      
      try {
        // 直接查询单个角色状态，避免 state 闭包问题
        const res = await fetch(`${API_BASE}/characters/${characterId}`);
        const data = await res.json();
        if (data.success && data.data) {
          const character = data.data;
          // 更新本地角色列表中的该角色
          setCharacters(prev => prev.map(c => c.id === characterId ? { ...c, ...character } : c));
          
          if (character.generatingStatus === 'completed') {
            clearInterval(interval);
            setGeneratingId(null);
            toast.success(t('characters.generatePortrait') + t('common.success'));
          } else if (character.generatingStatus === 'failed') {
            clearInterval(interval);
            setGeneratingId(null);
            toast.error(t('characters.generatePortrait') + t('common.error'));
          }
        }
      } catch (error) {
        console.error('轮询状态失败:', error);
      }
    }, 3000); // 每3秒检查一次
  };

  // 触发文件选择
  const triggerFileUpload = (characterId: string) => {
    setCurrentUploadCharacterId(characterId);
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  // 上传角色图片
  const handleUploadImage = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !currentUploadCharacterId) return;
    
    // 验证文件类型
    const allowedTypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/webp'];
    if (!allowedTypes.includes(file.type)) {
      toast.error(t('common.error') + ': 仅支持 PNG, JPG, WEBP 格式');
      return;
    }
    
    setUploadingId(currentUploadCharacterId);
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      const res = await fetch(`${API_BASE}/characters/${currentUploadCharacterId}/upload-image`, {
        method: 'POST',
        body: formData
      });
      
      const data = await res.json();
      
      if (data.success) {
        // 更新本地角色列表
        setCharacters(prev => prev.map(c => 
          c.id === currentUploadCharacterId ? { ...c, ...data.data } : c
        ));
        toast.success(t('characters.uploadSuccess'));
      } else {
        toast.error(data.message || t('characters.uploadFailed'));
      }
    } catch (error) {
      console.error('上传图片失败:', error);
      toast.error(t('characters.uploadFailed'));
    } finally {
      setUploadingId(null);
      setCurrentUploadCharacterId(null);
      // 清空文件输入
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  // 批量生成所有角色形象
  const generateAllPortraits = async () => {
    if (filteredCharacters.length === 0) {
      toast.warning(t('characters.noCharacters'));
      return;
    }
    
    // 过滤出不在生成中的角色
    const charactersToGenerate = filteredCharacters.filter(
      c => c.generatingStatus !== 'running'
    );
    
    if (charactersToGenerate.length === 0) {
      toast.info(t('characters.generatingStatus'));
      return;
    }
    
    // 统计已有形象的角色数量
    const hasImageCount = charactersToGenerate.filter(c => c.imageUrl).length;
    const noImageCount = charactersToGenerate.length - hasImageCount;
    
    let confirmMessage = '';
    if (hasImageCount > 0 && noImageCount > 0) {
      confirmMessage = t('characters.confirmGenerateMixed', { newCount: noImageCount, regenCount: hasImageCount });
    } else if (hasImageCount > 0) {
      confirmMessage = t('characters.confirmRegenerateCount', { count: hasImageCount });
    } else {
      confirmMessage = t('characters.confirmGenerateCount', { count: noImageCount });
    }
    
    if (!window.confirm(confirmMessage)) return;
    
    setGeneratingAll(true);
    
    // 先清空角色图片目录
    try {
      const clearRes = await fetch(`${API_BASE}/characters/clear-characters-dir?novel_id=${selectedNovel}`, {
        method: 'POST',
      });
      if (!clearRes.ok) {
        console.warn('清空角色图片目录失败');
      }
    } catch (error) {
      console.error('清空角色图片目录出错:', error);
    }
    let successCount = 0;
    let failCount = 0;
    
    for (const character of charactersToGenerate) {
      try {
        const res = await fetch(`${API_BASE}/tasks/character/${character.id}/generate-portrait/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        });
        const data = await res.json();
        if (data.success) {
          successCount++;
          // 更新本地状态为生成中
          setCharacters(prev => prev.map(c => 
            c.id === character.id ? { ...c, generatingStatus: 'running' } : c
          ));
        } else {
          failCount++;
        }
      } catch (error) {
        console.error(`生成角色 ${character.name} 失败:`, error);
        failCount++;
      }
    }
    
    setGeneratingAll(false);
    
    if (successCount > 0) {
      toast.success(`${t('common.success')} ${successCount}`);
      // 开始轮询所有角色状态
      pollAllCharactersStatus();
    }
    if (failCount > 0) {
      toast.error(`${t('common.error')} ${failCount}`);
    }
  };

  // 轮询所有生成中的角色状态
  const pollAllCharactersStatus = () => {
    // 如果没有选择小说，不启动轮询
    if (!selectedNovel) return;
    
    const interval = setInterval(async () => {
      try {
        // 直接获取最新角色列表，避免 state 闭包问题
        const url = `${API_BASE}/characters?novel_id=${selectedNovel}`;
        const res = await fetch(url);
        const data = await res.json();
        if (data.success) {
          const chars = data.data || [];
          setCharacters(chars);
          
          // 检查是否还有生成中的角色
          const generatingChars = chars.filter(
            (c: Character) => c.generatingStatus === 'running'
          );
          
          if (generatingChars.length === 0) {
            clearInterval(interval);
            toast.success(t('characters.generateAllPortraits') + t('common.success'));
          }
        }
      } catch (error) {
        console.error('轮询状态失败:', error);
      }
    }, 5000); // 每5秒检查一次
  };

  // 打开图片预览
  const openImagePreview = (url: string, name: string, characterId: string) => {
    setPreviewImage({ isOpen: true, url, name, characterId });
  };

  // 关闭图片预览
  const closeImagePreview = () => {
    setPreviewImage({ isOpen: false, url: null, name: '', characterId: null });
  };

  const filteredCharacters = characters.filter(c => 
    c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    c.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // 切换到上一个/下一个角色图片
  const navigatePreview = (direction: 'prev' | 'next') => {
    if (!previewImage.characterId) return;
    
    // 获取所有有图片的角色（使用当前筛选后的角色）
    const charactersWithImages = filteredCharacters.filter(c => c.imageUrl);
    const currentIndex = charactersWithImages.findIndex(c => c.id === previewImage.characterId);
    
    if (currentIndex === -1) return;
    
    let newIndex: number;
    if (direction === 'prev') {
      newIndex = currentIndex === 0 ? charactersWithImages.length - 1 : currentIndex - 1;
    } else {
      newIndex = currentIndex === charactersWithImages.length - 1 ? 0 : currentIndex + 1;
    }
    
    const newCharacter = charactersWithImages[newIndex];
    setPreviewImage({
      isOpen: true,
      url: newCharacter.imageUrl!,
      name: newCharacter.name,
      characterId: newCharacter.id
    });
  };



  const getNovelName = (novelId: string) => {
    const novel = novels.find(n => n.id === novelId);
    return novel?.title || t('characters.selectNovel');
  };

  // 根据小说ID获取画面比例
  const getNovelAspectRatio = (novelId: string): string => {
    const novel = novels.find(n => n.id === novelId);
    return novel?.aspectRatio || '16:9';
  };

  // 根据画面比例计算图片容器样式
  const getAspectRatioClass = (aspectRatio: string): string => {
    switch (aspectRatio) {
      case '16:9':
        return 'aspect-video'; // 16:9
      case '9:16':
        return 'aspect-[9/16]';
      case '4:3':
        return 'aspect-[4/3]';
      case '3:4':
        return 'aspect-[3/4]';
      case '1:1':
        return 'aspect-square';
      case '21:9':
        return 'aspect-[21/9]';
      case '2.35:1':
        return 'aspect-[2.35/1]';
      default:
        return 'aspect-video';
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{t('characters.title')}</h1>
          <p className="mt-1 text-sm text-gray-500">
            {t('characters.subtitle')}
          </p>
        </div>
        <div className="flex gap-3">
          {filteredCharacters.length > 0 && (
            <button
              onClick={generateAllPortraits}
              disabled={generatingAll}
              className="btn-secondary text-purple-600 border-purple-200 hover:bg-purple-50 disabled:opacity-50"
            >
              {generatingAll ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Image className="mr-2 h-4 w-4" />
              )}
              {t('characters.generateAllPortraits')}
            </button>
          )}
          {selectedNovel && characters.length > 0 && (
            <button
              onClick={() => setDeleteAllConfirmDialog({ isOpen: true })}
              className="btn-secondary text-red-600 border-red-200 hover:bg-red-50"
            >
              <Trash2 className="mr-2 h-4 w-4" />
              {t('characters.deleteAll')}
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
            placeholder={t('characters.searchCharacters')}
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

      {/* Characters Grid */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
        </div>
      ) : filteredCharacters.length === 0 ? (
        <div className="card text-center py-12">
          <User className="mx-auto h-12 w-12 text-gray-300" />
          <h3 className="mt-4 text-lg font-medium text-gray-900">{t('characters.noCharacters')}</h3>
          <p className="mt-1 text-sm text-gray-500">
            {t('common.create')} {t('characters.subtitle')}
          </p>

        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {filteredCharacters.map((character) => {
            const aspectRatio = getNovelAspectRatio(character.novelId);
            const aspectClass = getAspectRatioClass(aspectRatio);
            
            return (
            <div
              key={character.id}
              id={`character-${character.id}`}
              className={`bg-white rounded-lg shadow-sm border overflow-hidden hover:shadow-md transition-all group ${
                highlightedId === character.id 
                  ? 'ring-4 ring-blue-500 ring-opacity-50 border-blue-500 animate-pulse' 
                  : 'border-gray-200'
              }`}
            >
              {/* Character Image - 根据小说画面比例显示 */}
              <div className={`${aspectClass} bg-gray-100 relative w-full`}>
                {character.imageUrl ? (
                  <img
                    src={character.imageUrl}
                    alt={character.name}
                    className="w-full h-full object-cover cursor-pointer"
                    onClick={() => openImagePreview(character.imageUrl!, character.name, character.id)}
                  />
                ) : (
                  <div className="absolute inset-0 flex items-center justify-center">
                    <User className="h-20 w-20 text-gray-300" />
                  </div>
                )}
                
                {/* Status Badge */}
                {character.generatingStatus === 'running' && (
                  <div className="absolute top-2 left-2 px-2 py-1 bg-blue-500 text-white text-xs rounded-full flex items-center gap-1">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    {t('characters.generating')}
                  </div>
                )}
                {character.generatingStatus === 'failed' && (
                  <div className="absolute top-2 left-2 px-2 py-1 bg-red-500 text-white text-xs rounded-full">
                    {t('characters.generateFailed')}
                  </div>
                )}
                
                {/* Delete Button - 右上角 */}
                <button
                  onClick={() => handleDelete(character.id)}
                  className="absolute top-2 right-2 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100"
                  title={t('common.delete')}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
                
                {/* Edit Button - 左下角 */}
                <button
                  onClick={() => setEditingCharacter(character)}
                  className="absolute bottom-2 left-2 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors opacity-0 group-hover:opacity-100"
                  title={t('common.edit')}
                >
                  <Edit2 className="h-4 w-4" />
                </button>
                
                {/* 上传按钮 - 左下角（编辑按钮右边） */}
                <button
                  onClick={() => triggerFileUpload(character.id)}
                  disabled={uploadingId === character.id}
                  className="absolute bottom-2 left-12 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-green-600 hover:bg-green-50 transition-colors disabled:opacity-70 opacity-0 group-hover:opacity-100"
                  title={t('characters.uploadImage')}
                >
                  {uploadingId === character.id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Upload className="h-4 w-4" />
                  )}
                </button>
                
                {/* AI生成形象 Button - 右下角，带文字 */}
                <button
                  onClick={() => generatePortrait(character)}
                  disabled={generatingId === character.id || character.generatingStatus === 'running'}
                  className="absolute bottom-2 right-2 flex items-center gap-1 px-3 py-1.5 bg-purple-600/90 hover:bg-purple-700 text-white rounded-lg transition-colors disabled:opacity-70 opacity-0 group-hover:opacity-100 text-xs"
                  title={character.generatingStatus === 'running' ? t('characters.generatingStatus') : (character.imageUrl ? t('characters.regenerate') : t('characters.generatePortrait'))}
                >
                  {character.generatingStatus === 'running' || generatingId === character.id ? (
                    <>
                      <Loader2 className="h-3 w-3 animate-spin" />
                      <span>{t('characters.generatingStatus')}</span>
                    </>
                  ) : (
                    <>
                      <Wand2 className="h-3 w-3" />
                      <span>AI{t('characters.generatePortrait')}</span>
                    </>
                  )}
                </button>
                
                {/* Loading Overlay - when local state shows generating */}
                {generatingId === character.id && (
                  <div className="absolute inset-0 bg-black bg-opacity-50 flex items-center justify-center">
                    <div className="text-center">
                      <Loader2 className="h-8 w-8 animate-spin text-white mx-auto" />
                      <p className="text-white text-sm mt-2">{t('characters.generating')}</p>
                    </div>
                  </div>
                )}
              </div>

              {/* Character Info */}
              <div className="p-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-semibold text-gray-900 truncate">
                    {character.name}
                  </h3>
                  <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-500 rounded">
                    {aspectRatio}
                  </span>
                </div>
                
                {/* 角色描述 - 可滚动显示完整内容 */}
                {character.description && (
                  <div className="mt-3">
                    <p className="text-xs text-gray-400 mb-1">{t('characters.descriptionLabel')}</p>
                    <div className="text-sm text-gray-600 max-h-20 overflow-y-auto pr-1 scrollbar-thin">
                      {character.description}
                    </div>
                  </div>
                )}
                
                {/* 外貌特征 - 可滚动显示完整内容 */}
                {character.appearance ? (
                  <div className="mt-3">
                    <p className="text-xs text-gray-400 mb-1">{t('characters.appearance')}</p>
                    <div className="text-xs text-gray-500 bg-gray-50 rounded p-2 max-h-24 overflow-y-auto scrollbar-thin">
                      {character.appearance}
                    </div>
                  </div>
                ) : (
                  <div className="mt-3">
                    <button
                      onClick={() => generateAppearance(character)}
                      disabled={generatingAppearanceId === character.id || !character.description}
                      className="text-xs inline-flex items-center text-primary-600 hover:text-primary-700 disabled:opacity-50"
                    >
                      {generatingAppearanceId === character.id ? (
                        <>
                          <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                          {t('characters.generatingStatus')}
                        </>
                      ) : (
                        <>
                          <Sparkles className="h-3 w-3 mr-1" />
                          {t('characters.generateAppearance')}
                        </>
                      )}
                    </button>
                  </div>
                )}

                {/* 生成提示词 */}
                {characterPrompts[character.id] && (
                  <div className="mt-3 pt-3 border-t border-gray-100">
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-xs text-gray-400">{t('characters.promptLabel')}</p>
                      <span className="text-xs text-gray-400">
                        {characterPrompts[character.id].isSystem 
                          ? t(`promptConfig.templateNames.${characterPrompts[character.id].templateName}`, { defaultValue: characterPrompts[character.id].templateName })
                          : characterPrompts[character.id].templateName
                        }
                      </span>
                    </div>
                    <div className="text-xs text-gray-500 bg-gray-50 rounded p-2 max-h-20 overflow-y-auto scrollbar-thin font-mono">
                      {characterPrompts[character.id].prompt}
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
          })}
        </div>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('characters.createCharacter')}</h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('characters.novelLabel')}
                </label>
                <select
                  required
                  value={formData.novelId}
                  onChange={(e) => setFormData({ ...formData, novelId: e.target.value })}
                  className="input-field mt-1"
                >
                  <option value="">{t('characters.selectNovel')}</option>
                  {novels.map(novel => (
                    <option key={novel.id} value={novel.id}>{novel.title}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('characters.characterName')} *
                </label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="input-field mt-1"
                  placeholder={t('characters.namePlaceholder')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('characters.description')}
                </label>
                <textarea
                  rows={3}
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="input-field mt-1"
                  placeholder={t('characters.descriptionPlaceholder')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('characters.appearance')}
                </label>
                <textarea
                  rows={3}
                  value={formData.appearance}
                  onChange={(e) => setFormData({ ...formData, appearance: e.target.value })}
                  className="input-field mt-1"
                  placeholder={t('characters.appearancePlaceholder')}
                />
                <p className="mt-1 text-xs text-gray-500">
                  {t('characters.appearanceTip')}
                </p>
              </div>
              <div className="flex justify-end gap-3 mt-6">
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
      {editingCharacter && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('common.edit')}</h2>
            <form onSubmit={handleUpdate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('characters.characterName')} *
                </label>
                <input
                  type="text"
                  required
                  value={editingCharacter.name}
                  onChange={(e) => setEditingCharacter({ ...editingCharacter, name: e.target.value })}
                  className="input-field mt-1"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('characters.description')}
                </label>
                <textarea
                  rows={3}
                  value={editingCharacter.description}
                  onChange={(e) => setEditingCharacter({ ...editingCharacter, description: e.target.value })}
                  className="input-field mt-1"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  {t('characters.appearance')}
                </label>
                <textarea
                  rows={3}
                  value={editingCharacter.appearance}
                  onChange={(e) => setEditingCharacter({ ...editingCharacter, appearance: e.target.value })}
                  className="input-field mt-1"
                  placeholder={t('characters.appearancePlaceholder')}
                />
              </div>
              <div className="flex justify-end gap-3 mt-6">
                <button
                  type="button"
                  onClick={() => setEditingCharacter(null)}
                  className="btn-secondary"
                >
                  {t('common.cancel')}
                </button>
                <button type="submit" className="btn-primary">
                  {t('characters.saveChanges')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}


      {/* 删除所有角色确认对话框 */}
      {deleteAllConfirmDialog.isOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-md shadow-xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 bg-red-100 rounded-full">
                <AlertTriangle className="h-6 w-6 text-red-600" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900">{t('characters.deleteAllTitle')}</h3>
            </div>
            <p className="text-gray-600 mb-2">
              {t('characters.confirmDelete', { name: novels.find(n => n.id === selectedNovel)?.title || '' })}
            </p>
            <p className="text-sm text-red-500 mb-6">
              {t('characters.deleteAllWarning')}
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setDeleteAllConfirmDialog({ isOpen: false })}
                className="px-4 py-2 text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleDeleteAllCharacters}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg transition-colors"
              >
                {t('characters.confirmDeleteBtn')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 图片预览弹窗 */}
      {previewImage.isOpen && previewImage.url && (
        <div 
          className="fixed inset-0 bg-black bg-opacity-90 flex items-center justify-center z-50 p-4"
          onClick={closeImagePreview}
        >
          <div className="relative max-w-4xl max-h-[90vh] w-full flex items-center">
            {/* 左箭头 */}
            <button
              onClick={(e) => { e.stopPropagation(); navigatePreview('prev'); }}
              className="absolute -left-16 top-1/2 -translate-y-1/2 p-3 text-white hover:text-gray-300 hover:bg-white/10 rounded-full transition-all"
              title={t('characters.previous')}
            >
              <ChevronLeft className="h-10 w-10" />
            </button>
            
            <div className="flex-1">
              {/* 关闭按钮 */}
              <button
                onClick={closeImagePreview}
                className="absolute -top-12 right-0 p-2 text-white hover:text-gray-300 transition-colors"
              >
                <X className="h-8 w-8" />
              </button>
              
              {/* 角色名称 */}
              <h3 className="text-white text-lg font-semibold mb-4 text-center">
                {previewImage.name}
              </h3>
              
              {/* 图片 */}
              <img
                src={previewImage.url}
                alt={previewImage.name}
                className="w-full h-full object-contain max-h-[80vh] rounded-lg cursor-pointer"
                onClick={(e) => e.stopPropagation()}
              />
              
              {/* 底部提示 */}
              <div className="mt-4 text-center text-gray-400 text-sm">
                <span className="inline-flex items-center gap-2">
                  <kbd className="px-2 py-1 bg-gray-700 rounded text-xs">←</kbd>
                  <kbd className="px-2 py-1 bg-gray-700 rounded text-xs">→</kbd>
                  <span>{t('characters.keyboardNavigate')}</span>
                  <span className="mx-2">|</span>
                  <span>
                    {filteredCharacters.filter(c => c.imageUrl).findIndex(c => c.id === previewImage.characterId) + 1} / {filteredCharacters.filter(c => c.imageUrl).length}
                  </span>
                </span>
              </div>
            </div>
            
            {/* 右箭头 */}
            <button
              onClick={(e) => { e.stopPropagation(); navigatePreview('next'); }}
              className="absolute -right-16 top-1/2 -translate-y-1/2 p-3 text-white hover:text-gray-300 hover:bg-white/10 rounded-full transition-all"
              title={t('characters.next')}
            >
              <ChevronRight className="h-10 w-10" />
            </button>
          </div>
        </div>
      )}
      
      {/* 隐藏的文件输入 */}
      <input
        type="file"
        ref={fileInputRef}
        className="hidden"
        accept="image/png,image/jpeg,image/jpg,image/webp"
        onChange={handleUploadImage}
      />
    </div>
  );
}
