/**
 * 角色管理页面
 */
import { useState, useEffect, useRef } from 'react';
import { Plus, Search, Trash2, Loader2, User, Image } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import type { Character, Novel, PromptTemplate } from '../../types';
import { toast } from '../../stores/toastStore';
import { useTranslation } from '../../stores/i18nStore';
import { characterApi } from '../../api/characters';
import { promptTemplateApi } from '../../api/promptTemplates';
import { api } from '../../api';
import { ImagePreviewModal, CharacterCard } from './components';
import { ASPECT_RATIO_CLASSES, ALLOWED_IMAGE_TYPES, ALLOWED_AUDIO_TYPES, MAX_AUDIO_SIZE, POLL_CONFIG } from './constants';
import type { CharacterPrompt, PreviewImageState, DeleteAllConfirmDialog } from './types';

export default function Characters() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [characters, setCharacters] = useState<Character[]>([]);
  const [novels, setNovels] = useState<Novel[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const novelIdFromUrl = searchParams.get('novel') || searchParams.get('novel_id') || '';
  const highlightId = searchParams.get('highlight');
  const [selectedNovel, setSelectedNovel] = useState<string>(novelIdFromUrl);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingCharacter, setEditingCharacter] = useState<Character | null>(null);
  const [generatingId, setGeneratingId] = useState<string | null>(null);
  const [generatingAppearanceId, setGeneratingAppearanceId] = useState<string | null>(null);
  const [characterPrompts, setCharacterPrompts] = useState<Record<string, CharacterPrompt>>({});
  const [highlightedId, setHighlightedId] = useState<string | null>(highlightId);
  const [parsingNovelId, setParsingNovelId] = useState<string | null>(null);
  
  const [deleteAllConfirmDialog, setDeleteAllConfirmDialog] = useState<DeleteAllConfirmDialog>({ isOpen: false });
  const [previewImage, setPreviewImage] = useState<PreviewImageState>({ isOpen: false, url: null, name: '', characterId: null });
  const [generatingAll, setGeneratingAll] = useState(false);
  const [uploadingId, setUploadingId] = useState<string | null>(null);
  const [generatingVoiceId, setGeneratingVoiceId] = useState<string | null>(null);
  const [uploadingAudioId, setUploadingAudioId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const audioFileInputRef = useRef<HTMLInputElement | null>(null);
  const [currentUploadCharacterId, setCurrentUploadCharacterId] = useState<string | null>(null);
  const [currentAudioUploadCharacterId, setCurrentAudioUploadCharacterId] = useState<string | null>(null);
  
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

  // 处理高亮角色
  useEffect(() => {
    if (highlightedId && characters.length > 0) {
      const element = document.getElementById(`character-${highlightedId}`);
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setTimeout(() => setHighlightedId(null), 3000);
      }
    }
  }, [highlightedId, characters]);

  const fetchCharacters = async () => {
    if (!selectedNovel) {
      setCharacters([]);
      setIsLoading(false);
      return;
    }
    
    setIsLoading(true);
    try {
      const data = await characterApi.fetchList(selectedNovel);
      if (data.success) {
        setCharacters(data.data || []);
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
      const data = await characterApi.fetchPrompt(characterId);
      if (data.success) {
        setCharacterPrompts(prev => ({
          ...prev,
          [characterId]: {
            prompt: data.data!.prompt,
            templateName: data.data!.templateName,
            templateId: data.data!.templateId,
            isSystem: data.data!.isSystem
          }
        }));
      }
    } catch (error) {
      console.error('获取角色提示词失败:', error);
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
      const data = await characterApi.create({
        novelId: formData.novelId,
        name: formData.name,
        description: formData.description,
        appearance: formData.appearance,
      });
      if (data.success) {
        setCharacters([data.data!, ...characters]);
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
      const data = await characterApi.update(editingCharacter.id, {
        name: editingCharacter.name,
        description: editingCharacter.description,
        appearance: editingCharacter.appearance,
        voice_prompt: editingCharacter.voicePrompt,
      } as Partial<Character>);
      if (data.success) {
        setCharacters(characters.map(c => c.id === data.data!.id ? { ...c, ...data.data } : c));
        setEditingCharacter(null);
      }
    } catch (error) {
      console.error('更新角色失败:', error);
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm(t('characters.confirmDelete', { name: '' }).replace('""', ''))) return;
    
    try {
      await characterApi.delete(id);
      setCharacters(characters.filter(c => c.id !== id));
    } catch (error) {
      console.error('删除角色失败:', error);
    }
  };

  const handleDeleteAllCharacters = async () => {
    if (!selectedNovel) {
      toast.error(t('characters.selectNovel'));
      return;
    }
    
    try {
      const data = await characterApi.deleteAll(selectedNovel);
      if (data.success) {
        toast.success(data.message || t('common.delete') + t('common.success'));
        setCharacters([]);
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
      const data = await characterApi.generateAppearance(character.id);
      if (data.success) {
        setCharacters(prev => prev.map(c => 
          c.id === character.id ? { ...c, appearance: data.data!.appearance } : c
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
    if (character.generatingStatus === 'running') {
      toast.info(t('characters.generatingStatus'));
      return;
    }
    
    setGeneratingId(character.id);
    try {
      const data = await characterApi.generatePortrait(character.id);
      if (data.success) {
        setCharacters(prev => prev.map(c => 
          c.id === character.id ? { ...c, generatingStatus: 'running' } : c
        ));
        toast.success(t('characters.generatingStatus'));
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

  const pollCharacterStatus = async (characterId: string, maxAttempts = POLL_CONFIG.maxAttempts) => {
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
        const data = await characterApi.fetch(characterId);
        if (data.success && data.data) {
          const character = data.data;
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
    }, POLL_CONFIG.intervalMs);
  };

  const triggerFileUpload = (characterId: string) => {
    setCurrentUploadCharacterId(characterId);
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const triggerAudioUpload = (characterId: string) => {
    setCurrentAudioUploadCharacterId(characterId);
    if (audioFileInputRef.current) {
      audioFileInputRef.current.click();
    }
  };

  const handleUploadImage = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !currentUploadCharacterId) return;

    if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
      toast.error(t('common.error') + ': 仅支持 PNG, JPG, WEBP 格式');
      return;
    }

    setUploadingId(currentUploadCharacterId);

    try {
      const data = await characterApi.uploadImage(currentUploadCharacterId, file);
      if (data.success) {
        setCharacters(prev => prev.map(c =>
          c.id === currentUploadCharacterId ? { ...c, ...data.data! } : c
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
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleUploadAudio = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !currentAudioUploadCharacterId) return;

    if (!ALLOWED_AUDIO_TYPES.includes(file.type)) {
      toast.error(t('characters.invalidAudioFormat'));
      return;
    }

    if (file.size > MAX_AUDIO_SIZE) {
      toast.error(t('characters.audioTooLarge'));
      return;
    }

    setUploadingAudioId(currentAudioUploadCharacterId);

    try {
      const data = await characterApi.uploadAudio(currentAudioUploadCharacterId, file);
      if (data.success) {
        setCharacters(prev => prev.map(c =>
          c.id === currentAudioUploadCharacterId ? { ...c, referenceAudioUrl: data.data!.referenceAudioUrl } : c
        ));
        toast.success(t('characters.uploadAudioSuccess'));
      } else {
        toast.error(data.message || t('characters.uploadAudioFailed'));
      }
    } catch (error) {
      console.error('上传音频失败:', error);
      toast.error(t('characters.uploadAudioFailed'));
    } finally {
      setUploadingAudioId(null);
      setCurrentAudioUploadCharacterId(null);
      if (audioFileInputRef.current) {
        audioFileInputRef.current.value = '';
      }
    }
  };

  const generateAllPortraits = async () => {
    if (filteredCharacters.length === 0) {
      toast.warning(t('characters.noCharacters'));
      return;
    }
    
    const charactersToGenerate = filteredCharacters.filter(c => c.generatingStatus !== 'running');
    
    if (charactersToGenerate.length === 0) {
      toast.info(t('characters.generatingStatus'));
      return;
    }
    
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
    
    try {
      await characterApi.clearImagesDir(selectedNovel);
    } catch (error) {
      console.error('清空角色图片目录出错:', error);
    }
    
    let successCount = 0;
    let failCount = 0;
    
    for (const character of charactersToGenerate) {
      try {
        const data = await characterApi.generatePortrait(character.id);
        if (data.success) {
          successCount++;
          setCharacters(prev => prev.map(c =>
            c.id === character.id ? { ...c, generatingStatus: 'running' } : c
          ));
        } else {
          failCount++;
          // 显示具体的错误信息
          toast.error(`${character.name}: ${data.message || t('common.error')}`);
        }
      } catch (error) {
        console.error(`生成角色 ${character.name} 失败:`, error);
        failCount++;
        // 捕获异常时也显示错误信息
        const errorMessage = error instanceof Error ? error.message : t('common.error');
        toast.error(`${character.name}: ${errorMessage}`);
      }
    }

    setGeneratingAll(false);

    if (successCount > 0) {
      toast.success(`${t('common.success')} ${successCount}`);
      pollAllCharactersStatus();
    }
  };

  const pollAllCharactersStatus = () => {
    if (!selectedNovel) return;
    
    const interval = setInterval(async () => {
      try {
        const data = await characterApi.fetchList(selectedNovel);
        if (data.success) {
          const chars = data.data || [];
          setCharacters(chars);
          
          const generatingChars = chars.filter((c: Character) => c.generatingStatus === 'running');
          
          if (generatingChars.length === 0) {
            clearInterval(interval);
            toast.success(t('characters.generateAllPortraits') + t('common.success'));
          }
        }
      } catch (error) {
        console.error('轮询状态失败:', error);
      }
    }, POLL_CONFIG.allIntervalMs);
  };

  const openImagePreview = (url: string, name: string, characterId: string) => {
    setPreviewImage({ isOpen: true, url, name, characterId });
  };

  const closeImagePreview = () => {
    setPreviewImage({ isOpen: false, url: null, name: '', characterId: null });
  };

  const navigatePreview = (direction: 'prev' | 'next') => {
    if (!previewImage.characterId) return;
    
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

  const generateVoice = async (character: Character) => {
    if (!character.voicePrompt) {
      toast.warning(t('characters.needVoicePrompt'));
      return;
    }

    setGeneratingVoiceId(character.id);
    try {
      const data = await characterApi.generateVoice(character.id);
      if (data.success) {
        toast.success(t('characters.generatingVoice'));
        pollVoiceStatus(character.id);
      } else {
        toast.error(data.message || t('common.error'));
        setGeneratingVoiceId(null);
      }
    } catch (error) {
      console.error('生成音色失败:', error);
      toast.error(t('common.error'));
      setGeneratingVoiceId(null);
    }
  };

  const pollVoiceStatus = async (characterId: string, maxAttempts = 60) => {
    let attempts = 0;
    const interval = setInterval(async () => {
      attempts++;
      if (attempts > maxAttempts) {
        clearInterval(interval);
        setGeneratingVoiceId(null);
        toast.warning(t('characters.voiceGenerateTimeout'));
        return;
      }

      try {
        const data = await characterApi.getVoiceStatus(characterId);
        if (data.success && data.data) {
          const { status, referenceAudioUrl } = data.data;

          // 完成：状态为 completed 或 idle（任务完成后状态恢复），且有音频URL
          if ((status === 'completed' || status === 'idle') && referenceAudioUrl) {
            clearInterval(interval);
            setGeneratingVoiceId(null);
            setCharacters(prev => prev.map(c =>
              c.id === characterId ? { ...c, referenceAudioUrl } : c
            ));
            toast.success(t('characters.generateVoice') + t('common.success'));
          } else if (status === 'failed') {
            clearInterval(interval);
            setGeneratingVoiceId(null);
            toast.error(t('characters.generateVoice') + t('common.error'));
          }
        }
      } catch (error) {
        console.error('轮询音色状态失败:', error);
      }
    }, 2000);
  };

  const filteredCharacters = characters.filter(c => 
    c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    c.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const getNovelAspectRatio = (novelId: string): string => {
    const novel = novels.find(n => n.id === novelId);
    return novel?.aspectRatio || '16:9';
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{t('characters.title')}</h1>
          <p className="mt-1 text-sm text-gray-500">{t('characters.subtitle')}</p>
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
          <p className="mt-1 text-sm text-gray-500">{t('common.create')} {t('characters.subtitle')}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {filteredCharacters.map((character) => (
            <CharacterCard
              key={character.id}
              character={character}
              aspectRatio={getNovelAspectRatio(character.novelId)}
              highlightedId={highlightedId}
              generatingId={generatingId}
              generatingAppearanceId={generatingAppearanceId}
              uploadingId={uploadingId}
              generatingVoiceId={generatingVoiceId}
              uploadingAudioId={uploadingAudioId}
              characterPrompt={characterPrompts[character.id]}
              onDelete={handleDelete}
              onEdit={setEditingCharacter}
              onGeneratePortrait={generatePortrait}
              onGenerateAppearance={generateAppearance}
              onUploadImage={triggerFileUpload}
              onImageClick={openImagePreview}
              onGenerateVoice={generateVoice}
              onUploadAudio={triggerAudioUpload}
            />
          ))}
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

      {/* Hidden audio file input */}
      <input
        ref={audioFileInputRef}
        type="file"
        accept="audio/*"
        className="hidden"
        onChange={handleUploadAudio}
      />

      {/* Image Preview Modal */}
      <ImagePreviewModal
        isOpen={previewImage.isOpen}
        url={previewImage.url}
        name={previewImage.name}
        onClose={closeImagePreview}
        showNavigation={true}
        totalCount={filteredCharacters.filter(c => c.imageUrl).length}
        onPrev={() => navigatePreview('prev')}
        onNext={() => navigatePreview('next')}
      />

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('characters.createCharacter')}</h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">{t('characters.novelLabel')}</label>
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
                <label className="block text-sm font-medium text-gray-700">{t('characters.characterName')} *</label>
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
                <label className="block text-sm font-medium text-gray-700">{t('characters.description')}</label>
                <textarea
                  rows={3}
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="input-field mt-1"
                  placeholder={t('characters.descriptionPlaceholder')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">{t('characters.appearance')}</label>
                <textarea
                  rows={3}
                  value={formData.appearance}
                  onChange={(e) => setFormData({ ...formData, appearance: e.target.value })}
                  className="input-field mt-1"
                  placeholder={t('characters.appearancePlaceholder')}
                />
                <p className="mt-1 text-xs text-gray-500">{t('characters.appearanceTip')}</p>
              </div>
              <div className="flex justify-end gap-3 mt-6">
                <button type="button" onClick={() => setShowCreateModal(false)} className="btn-secondary">{t('common.cancel')}</button>
                <button type="submit" className="btn-primary">{t('common.create')}</button>
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
                <label className="block text-sm font-medium text-gray-700">{t('characters.characterName')} *</label>
                <input
                  type="text"
                  required
                  value={editingCharacter.name}
                  onChange={(e) => setEditingCharacter({ ...editingCharacter, name: e.target.value })}
                  className="input-field mt-1"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">{t('characters.description')}</label>
                <textarea
                  rows={3}
                  value={editingCharacter.description}
                  onChange={(e) => setEditingCharacter({ ...editingCharacter, description: e.target.value })}
                  className="input-field mt-1"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">{t('characters.appearance')}</label>
                <textarea
                  rows={3}
                  value={editingCharacter.appearance}
                  onChange={(e) => setEditingCharacter({ ...editingCharacter, appearance: e.target.value })}
                  className="input-field mt-1"
                  placeholder={t('characters.appearancePlaceholder')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">{t('characters.voicePromptLabel')}</label>
                <textarea
                  rows={2}
                  value={editingCharacter.voicePrompt || ''}
                  onChange={(e) => setEditingCharacter({ ...editingCharacter, voicePrompt: e.target.value })}
                  className="input-field mt-1"
                  placeholder={t('characters.voicePromptPlaceholder')}
                />
              </div>
              <div className="flex justify-end gap-3 mt-6">
                <button type="button" onClick={() => setEditingCharacter(null)} className="btn-secondary">{t('common.cancel')}</button>
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
            <h3 className="text-lg font-semibold text-gray-900 mb-4">{t('characters.deleteAllTitle')}</h3>
            <p className="text-sm text-red-600 mb-6">{t('characters.deleteAllWarning')}</p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setDeleteAllConfirmDialog({ isOpen: false })} className="btn-secondary">{t('common.cancel')}</button>
              <button onClick={handleDeleteAllCharacters} className="btn-primary bg-red-600 hover:bg-red-700">{t('characters.confirmDeleteBtn')}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
