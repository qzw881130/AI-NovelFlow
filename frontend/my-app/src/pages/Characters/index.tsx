/**
 * 角色管理页面
 */
import { useState, useEffect, useRef } from 'react';
import { Plus, Search, Trash2, Loader2, User, Image, X, Mic, Check, Upload, Play } from 'lucide-react';
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
import { getLastSelectedNovelId, setLastSelectedNovelId } from '../../utils/lastSelectedNovel';

export default function Characters() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [characters, setCharacters] = useState<Character[]>([]);
  const [novels, setNovels] = useState<Novel[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const novelIdFromUrl = searchParams.get('novel') || searchParams.get('novel_id') || '';
  const highlightId = searchParams.get('highlight');
  const [selectedNovel, setSelectedNovel] = useState<string>(novelIdFromUrl || getLastSelectedNovelId());
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingCharacter, setEditingCharacter] = useState<Character | null>(null);
  const [generatingId, setGeneratingId] = useState<string | null>(null);
  const [generatingAppearanceId, setGeneratingAppearanceId] = useState<string | null>(null);
  const [characterPrompts, setCharacterPrompts] = useState<Record<string, CharacterPrompt>>({});
  const [highlightedId, setHighlightedId] = useState<string | null>(highlightId);
  const [parsingNovelId, setParsingNovelId] = useState<string | null>(null);
  
  const [deleteAllConfirmDialog, setDeleteAllConfirmDialog] = useState<DeleteAllConfirmDialog>({ isOpen: false });
  const [previewImage, setPreviewImage] = useState<PreviewImageState>({ isOpen: false, url: null, name: '', characterId: null });
  const [imageEditCharacter, setImageEditCharacter] = useState<Character | null>(null);
  const [imageEditOptions, setImageEditOptions] = useState<string[]>([]);
  const [imageEditOther, setImageEditOther] = useState('');
  const [imageEditResultUrl, setImageEditResultUrl] = useState<string | null>(null);
  const [imageEditResultSize, setImageEditResultSize] = useState<{ width: number; height: number } | null>(null);
  const [editingImageId, setEditingImageId] = useState<string | null>(null);
  const [replacingImageId, setReplacingImageId] = useState<string | null>(null);
  const [generatingAll, setGeneratingAll] = useState(false);
  const [generatingMissing, setGeneratingMissing] = useState(false);
  const [uploadingId, setUploadingId] = useState<string | null>(null);
  const [generatingVoiceId, setGeneratingVoiceId] = useState<string | null>(null);
  const [uploadingAudioId, setUploadingAudioId] = useState<string | null>(null);
  const [showVoiceBatchModal, setShowVoiceBatchModal] = useState(false);
  const [selectedVoiceIds, setSelectedVoiceIds] = useState<Set<string>>(new Set());
  const [submittingVoiceBatch, setSubmittingVoiceBatch] = useState(false);
  const [statusFilter, setStatusFilter] = useState<'all' | 'generated' | 'notGenerated' | 'running' | 'pending'>('all');
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const audioFileInputRef = useRef<HTMLInputElement | null>(null);
  const voicePollRef = useRef<number | null>(null);
  const [currentUploadCharacterId, setCurrentUploadCharacterId] = useState<string | null>(null);
  const [currentAudioUploadCharacterId, setCurrentAudioUploadCharacterId] = useState<string | null>(null);
  
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    appearance: '',
    novelId: '',
  });

  const syncSelectedNovel = (novelId: string, replace = false) => {
    if (!novelId) return;
    setLastSelectedNovelId(novelId);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set('novel', novelId);
    nextParams.delete('novel_id');
    setSearchParams(nextParams, { replace });
  };

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

  useEffect(() => {
    return () => {
      if (voicePollRef.current) window.clearInterval(voicePollRef.current);
    };
  }, []);

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

        if (novelsList.length > 0) {
          const selectedExists = novelsList.some(novel => novel.id === selectedNovel);
          const savedNovelId = getLastSelectedNovelId();
          const savedExists = novelsList.some(novel => novel.id === savedNovelId);
          const nextNovelId = selectedExists ? selectedNovel : savedExists ? savedNovelId : novelsList[0].id;

          if (nextNovelId !== selectedNovel) {
            setSelectedNovel(nextNovelId);
          }
          syncSelectedNovel(nextNovelId, true);
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
    if (character.generatingStatus === 'pending' || character.generatingStatus === 'running') {
      toast.info(t('characters.generatingStatus'));
      return;
    }
    
    setGeneratingId(character.id);
    try {
      const data = await characterApi.generatePortrait(character.id);
      if (data.success) {
        setCharacters(prev => prev.map(c => 
          c.id === character.id ? { ...c, generatingStatus: 'pending' } : c
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
          c.id === currentAudioUploadCharacterId ? { ...c, referenceAudioUrl: data.data!.referenceAudioUrl, voiceTaskStatus: 'completed' } : c
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
    
    const charactersToGenerate = filteredCharacters.filter(c => c.generatingStatus !== 'pending' && c.generatingStatus !== 'running');
    
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

    const regeneratingIds = new Set(charactersToGenerate.map(character => character.id));
    setCharacters(prev => prev.map(character => (
      regeneratingIds.has(character.id)
        ? { ...character, imageUrl: undefined, generatingStatus: 'pending' }
        : character
    )));
    
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
            c.id === character.id ? { ...c, imageUrl: undefined, generatingStatus: 'pending' } : c
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

  const generateMissingPortraits = async () => {
    if (!selectedNovel) return;

    const charactersToGenerate = characters.filter(character => (
      (!character.imageUrl || character.generatingStatus === 'failed') &&
      character.generatingStatus !== 'pending' &&
      character.generatingStatus !== 'running'
    ));

    if (charactersToGenerate.length === 0) {
      toast.info(t('characters.noRemainingPortraits'));
      return;
    }

    if (!window.confirm(t('characters.confirmGenerateRemaining', { count: charactersToGenerate.length }))) return;

    setGeneratingMissing(true);
    try {
      const data = await characterApi.generateMissingPortraits(selectedNovel);
      if (data.success) {
        const queuedCount = data.data?.queuedCount || 0;
        const queuedIds = new Set(charactersToGenerate.map(character => character.id));
        setCharacters(prev => prev.map(character => (
          queuedIds.has(character.id)
            ? { ...character, generatingStatus: 'pending' }
            : character
        )));
        toast.success(t('characters.remainingQueued', { count: queuedCount }));
        if (queuedCount > 0) {
          pollAllCharactersStatus();
        }
      } else {
        toast.error(data.message || t('common.error'));
      }
    } catch (error) {
      console.error('生成剩余角色形象失败:', error);
      toast.error(t('common.error'));
    } finally {
      setGeneratingMissing(false);
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
          
          const generatingChars = chars.filter((c: Character) => c.generatingStatus === 'pending' || c.generatingStatus === 'running');
          
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

  const openImageEdit = (character: Character) => {
    setImageEditCharacter(character);
    setImageEditOptions([]);
    setImageEditOther('');
    setImageEditResultUrl(null);
    setImageEditResultSize(null);
  };

  const closeImageEdit = () => {
    if (editingImageId || replacingImageId) return;
    setImageEditCharacter(null);
    setImageEditOptions([]);
    setImageEditOther('');
    setImageEditResultUrl(null);
    setImageEditResultSize(null);
  };

  const toggleImageEditOption = (option: string) => {
    setImageEditOptions(prev => (
      prev.includes(option)
        ? prev.filter(item => item !== option)
        : [...prev, option]
    ));
  };

  const buildImageEditPrompt = () => {
    const selectedPrompts = imageEditOptions
      .filter(option => option !== 'other')
      .map(option => {
        if (option === 'removeWeapons') return '去除武器';
        if (option === 'makeFourView') return '修改成四视图';
        return '保持原图布局';
      });
    const otherPrompt = imageEditOptions.includes('other') ? imageEditOther.trim() : '';
    return [...selectedPrompts, otherPrompt].filter(Boolean).join('\n');
  };

  const handleEditImage = async () => {
    if (!imageEditCharacter) return;
    const prompt = buildImageEditPrompt();
    if (!prompt) {
      toast.warning(t('characters.editImagePromptRequired'));
      return;
    }

    setEditingImageId(imageEditCharacter.id);
    setImageEditResultUrl(null);
    setImageEditResultSize(null);
    try {
      const data = await characterApi.editImage(imageEditCharacter.id, prompt);
      if (data.success && data.data?.imageUrl) {
        setImageEditResultUrl(data.data.imageUrl);
        toast.success(t('characters.editImageSuccess'));
      } else {
        toast.error((data as any).detail || data.message || t('characters.editImageFailed'));
      }
    } catch (error) {
      console.error('编辑角色图片失败:', error);
      toast.error(t('characters.editImageFailed'));
    } finally {
      setEditingImageId(null);
    }
  };

  const handleReplaceImage = async () => {
    if (!imageEditCharacter || !imageEditResultUrl) return;
    setReplacingImageId(imageEditCharacter.id);
    try {
      const data = await characterApi.replaceImage(imageEditCharacter.id, imageEditResultUrl);
      if (data.success && data.data) {
        setCharacters(prev => prev.map(c => c.id === imageEditCharacter.id ? { ...c, ...data.data! } : c));
        toast.success(t('characters.replaceImageSuccess'));
        setImageEditCharacter(null);
        setImageEditOptions([]);
        setImageEditOther('');
        setImageEditResultUrl(null);
        setImageEditResultSize(null);
      } else {
        toast.error((data as any).detail || data.message || t('common.error'));
      }
    } catch (error) {
      console.error('替换角色图片失败:', error);
      toast.error(t('common.error'));
    } finally {
      setReplacingImageId(null);
    }
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
        setCharacters(prev => prev.map(c =>
          c.id === character.id ? { ...c, voiceTaskStatus: 'pending', voiceTaskId: (data.data as any)?.taskId || c.voiceTaskId } : c
        ));
        toast.success(t('characters.generatingVoice'));
        pollAllVoiceStatus();
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

  const pollAllVoiceStatus = () => {
    if (!selectedNovel) return;
    if (voicePollRef.current) window.clearInterval(voicePollRef.current);

    voicePollRef.current = window.setInterval(async () => {
      try {
        const data = await characterApi.fetchList(selectedNovel);
        if (!data.success) return;
        const chars = data.data || [];
        setCharacters(chars);
        const hasActiveVoiceTask = chars.some((char: Character) =>
          char.voiceTaskStatus === 'pending' || char.voiceTaskStatus === 'running'
        );
        if (!hasActiveVoiceTask && voicePollRef.current) {
          window.clearInterval(voicePollRef.current);
          voicePollRef.current = null;
          setGeneratingVoiceId(null);
        }
      } catch (error) {
        console.error('轮询角色音色状态失败:', error);
      }
    }, 2000);
  };

  const openVoiceBatchModal = () => {
    const missingVoiceIds = characters
      .filter(character => !character.referenceAudioUrl && character.voicePrompt)
      .map(character => character.id);
    setSelectedVoiceIds(new Set(missingVoiceIds));
    setShowVoiceBatchModal(true);
  };

  const toggleVoiceSelection = (characterId: string) => {
    setSelectedVoiceIds(prev => {
      const next = new Set(prev);
      if (next.has(characterId)) next.delete(characterId);
      else next.add(characterId);
      return next;
    });
  };

  const selectAllVoices = () => {
    setSelectedVoiceIds(new Set(characters.filter(character => character.voicePrompt).map(character => character.id)));
  };

  const selectMissingVoices = () => {
    setSelectedVoiceIds(new Set(
      characters
        .filter(character => !character.referenceAudioUrl && character.voicePrompt)
        .map(character => character.id)
    ));
  };

  const submitVoiceBatch = async () => {
    if (!selectedNovel || selectedVoiceIds.size === 0) return;
    setSubmittingVoiceBatch(true);
    try {
      const data = await characterApi.generateVoiceBatch(selectedNovel, Array.from(selectedVoiceIds));
      if (data.success) {
        const queuedIds = new Set((data.data?.tasks || []).map(item => item.id));
        setCharacters(prev => prev.map(character => (
          queuedIds.has(character.id)
            ? { ...character, voiceTaskStatus: 'pending' }
            : character
        )));
        toast.success(`已提交 ${data.data?.queuedCount || 0} 个角色音色任务`);
        pollAllVoiceStatus();
      } else {
        toast.error(data.message || t('common.error'));
      }
    } catch (error) {
      console.error('批量生成角色音色失败:', error);
      toast.error(t('common.error'));
    } finally {
      setSubmittingVoiceBatch(false);
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

  const matchesStatusFilter = (character: Character) => {
    if (statusFilter === 'all') return true;
    if (statusFilter === 'pending') return character.generatingStatus === 'pending';
    if (statusFilter === 'running') return character.generatingStatus === 'running';
    if (statusFilter === 'generated') return Boolean(character.imageUrl) && character.generatingStatus !== 'failed';
    return (!character.imageUrl || character.generatingStatus === 'failed')
      && character.generatingStatus !== 'pending'
      && character.generatingStatus !== 'running';
  };

  const sortNarratorFirst = (items: Character[]) => [...items].sort((a, b) => {
    if (a.isNarrator === b.isNarrator) return 0;
    return a.isNarrator ? -1 : 1;
  });

  const sortedCharacters = sortNarratorFirst(characters);
  const filteredCharacters = sortNarratorFirst(characters.filter(c => (
    c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    c.description.toLowerCase().includes(searchQuery.toLowerCase())
  ) && matchesStatusFilter(c)));

  const characterStats = characters.reduce(
    (stats, character) => {
      stats.total += 1;
      if (character.generatingStatus === 'pending') {
        stats.pending += 1;
      } else if (character.generatingStatus === 'running') {
        stats.running += 1;
      } else if (character.imageUrl && character.generatingStatus !== 'failed') {
        stats.generated += 1;
      } else {
        stats.notGenerated += 1;
      }
      return stats;
    },
    { total: 0, generated: 0, notGenerated: 0, running: 0, pending: 0 }
  );

  const statCardClass = (filter: typeof statusFilter, className: string) =>
    `rounded-lg border px-4 py-3 text-left transition hover:shadow-sm focus:outline-none focus:ring-2 focus:ring-primary-500 ${className} ${
      statusFilter === filter ? 'ring-2 ring-primary-500 shadow-sm' : ''
    }`;

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
          {selectedNovel && characters.length > 0 && (
            <button
              onClick={openVoiceBatchModal}
              className="btn-secondary text-pink-600 border-pink-200 hover:bg-pink-50"
            >
              <Mic className="mr-2 h-4 w-4" />
              生成角色音色
            </button>
          )}
          {filteredCharacters.length > 0 && (
            <button
              onClick={generateAllPortraits}
              disabled={generatingAll || generatingMissing}
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
          {characters.length > 0 && (
            <button
              onClick={generateMissingPortraits}
              disabled={generatingAll || generatingMissing}
              className="btn-secondary text-blue-600 border-blue-200 hover:bg-blue-50 disabled:opacity-50"
            >
              {generatingMissing ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Image className="mr-2 h-4 w-4" />
              )}
              {t('characters.generateRemainingPortraits')}
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
            const novelId = e.target.value;
            setSelectedNovel(novelId);
            syncSelectedNovel(novelId);
          }}
          className="input-field flex-1"
        >
          {novels.map(novel => (
            <option key={novel.id} value={novel.id}>{novel.title}</option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <button
          type="button"
          onClick={() => setStatusFilter('all')}
          className={statCardClass('all', 'border-gray-200 bg-white')}
        >
          <p className="text-xs text-gray-500">{t('characters.totalCount')}</p>
          <p className="mt-1 text-xl font-semibold text-gray-900">{characterStats.total}</p>
        </button>
        <button
          type="button"
          onClick={() => setStatusFilter('generated')}
          className={statCardClass('generated', 'border-green-100 bg-green-50')}
        >
          <p className="text-xs text-green-700">{t('characters.generatedCount')}</p>
          <p className="mt-1 text-xl font-semibold text-green-700">{characterStats.generated}</p>
        </button>
        <button
          type="button"
          onClick={() => setStatusFilter('notGenerated')}
          className={statCardClass('notGenerated', 'border-gray-200 bg-gray-50')}
        >
          <p className="text-xs text-gray-600">{t('characters.notGeneratedCount')}</p>
          <p className="mt-1 text-xl font-semibold text-gray-700">{characterStats.notGenerated}</p>
        </button>
        <button
          type="button"
          onClick={() => setStatusFilter('running')}
          className={statCardClass('running', 'border-blue-100 bg-blue-50')}
        >
          <p className="text-xs text-blue-700">{t('characters.runningCount')}</p>
          <p className="mt-1 text-xl font-semibold text-blue-700">{characterStats.running}</p>
        </button>
        <button
          type="button"
          onClick={() => setStatusFilter('pending')}
          className={statCardClass('pending', 'border-amber-100 bg-amber-50')}
        >
          <p className="text-xs text-amber-700">{t('characters.pendingCount')}</p>
          <p className="mt-1 text-xl font-semibold text-amber-700">{characterStats.pending}</p>
        </button>
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
              onEditImage={openImageEdit}
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

      {showVoiceBatchModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-6xl max-h-[88vh] flex flex-col">
            <div className="flex items-center justify-between border-b px-5 py-4">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">生成角色音色</h2>
                <p className="text-sm text-gray-500">选择角色后通过串行 worker 批量生成音色，可上传音频替代生成。</p>
              </div>
              <button
                onClick={() => setShowVoiceBatchModal(false)}
                className="p-2 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-lg"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex flex-wrap items-center gap-3 border-b px-5 py-3">
              <button onClick={selectAllVoices} className="btn-secondary text-sm">
                <Check className="mr-2 h-4 w-4" />全选
              </button>
              <button onClick={selectMissingVoices} className="btn-secondary text-sm">
                选择未生成的
              </button>
              <button
                onClick={() => setSelectedVoiceIds(new Set())}
                className="btn-secondary text-sm"
              >
                清空选择
              </button>
              <div className="text-sm text-gray-500">已选择 {selectedVoiceIds.size} / {characters.length}</div>
              <button
                onClick={submitVoiceBatch}
                disabled={selectedVoiceIds.size === 0 || submittingVoiceBatch}
                className="btn-primary ml-auto disabled:opacity-50"
              >
                {submittingVoiceBatch ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Mic className="mr-2 h-4 w-4" />}
                批量生成音色
              </button>
            </div>

            <div className="overflow-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="sticky top-0 bg-gray-50 z-10">
                  <tr>
                    <th className="w-12 px-4 py-3"></th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">角色图</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">角色名</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">音色提示词</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">音色播放</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">状态</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {sortedCharacters.map(character => {
                    const activeVoice = character.voiceTaskStatus === 'pending' || character.voiceTaskStatus === 'running';
                    return (
                      <tr key={character.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 align-top">
                          <input
                            type="checkbox"
                            checked={selectedVoiceIds.has(character.id)}
                            disabled={!character.voicePrompt || activeVoice}
                            onChange={() => toggleVoiceSelection(character.id)}
                            className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                          />
                        </td>
                        <td className="px-4 py-3 align-top">
                          {character.imageUrl ? (
                            <div className="aspect-video w-28 overflow-hidden rounded bg-gray-100">
                              <img src={character.imageUrl} alt={character.name} className="h-full w-full object-cover" />
                            </div>
                          ) : (
                            <div className="aspect-video w-28 rounded bg-gray-100 flex items-center justify-center text-gray-300">
                              <User className="h-7 w-7" />
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3 align-top">
                          <div className="font-medium text-gray-900">{character.name}</div>
                          {character.isNarrator && <div className="mt-1 text-xs text-purple-600">旁白</div>}
                        </td>
                        <td className="px-4 py-3 align-top max-w-md">
                          <p className="text-sm text-gray-700 line-clamp-3">{character.voicePrompt || '未设置音色提示词'}</p>
                        </td>
                        <td className="px-4 py-3 align-top min-w-64">
                          {character.referenceAudioUrl ? (
                            <audio controls src={character.referenceAudioUrl} className="h-9 w-64" />
                          ) : (
                            <span className="text-sm text-gray-400">未生成音色</span>
                          )}
                        </td>
                        <td className="px-4 py-3 align-top">
                          {activeVoice ? (
                            <div className="flex items-center gap-2 text-sm text-blue-600">
                              <Loader2 className="h-4 w-4 animate-spin" />
                              {character.voiceTaskStatus === 'pending' ? '待生成' : `生成中 ${character.voiceTaskProgress || 0}%`}
                            </div>
                          ) : character.referenceAudioUrl ? (
                            <span className="text-sm text-green-600">已生成</span>
                          ) : character.voiceTaskStatus === 'failed' ? (
                            <span className="text-sm text-red-600" title={character.voiceTaskMessage || ''}>生成失败</span>
                          ) : character.voicePrompt ? (
                            <span className="text-sm text-amber-600">未生成</span>
                          ) : (
                            <span className="text-sm text-gray-400">缺少提示词</span>
                          )}
                        </td>
                        <td className="px-4 py-3 align-top">
                          <div className="flex flex-wrap gap-2">
                            <button
                              onClick={() => generateVoice(character)}
                              disabled={!character.voicePrompt || activeVoice}
                              className="btn-secondary text-xs text-pink-600 border-pink-200 hover:bg-pink-50 disabled:opacity-50"
                            >
                              {activeVoice ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Play className="mr-1 h-3 w-3" />}
                              {character.referenceAudioUrl ? '重新生成' : '生成'}
                            </button>
                            <button
                              onClick={() => triggerAudioUpload(character.id)}
                              disabled={uploadingAudioId === character.id}
                              className="btn-secondary text-xs text-blue-600 border-blue-200 hover:bg-blue-50 disabled:opacity-50"
                            >
                              {uploadingAudioId === character.id ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Upload className="mr-1 h-3 w-3" />}
                              上传音频
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Image Preview Modal */}
      <ImagePreviewModal
        isOpen={previewImage.isOpen}
        url={previewImage.url}
        name={previewImage.name}
        showDownload={true}
        onClose={closeImagePreview}
        showNavigation={true}
        totalCount={filteredCharacters.filter(c => c.imageUrl).length}
        onPrev={() => navigatePreview('prev')}
        onNext={() => navigatePreview('next')}
      />

      {/* Image Edit Modal */}
      {imageEditCharacter && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg w-full max-w-4xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b px-6 py-4">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">{t('characters.editImageTitle')}</h2>
                <p className="mt-1 text-sm text-gray-500">{imageEditCharacter.name}</p>
              </div>
              <button
                type="button"
                onClick={closeImageEdit}
                disabled={Boolean(editingImageId || replacingImageId)}
                className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-50"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="grid gap-6 p-6 lg:grid-cols-[280px_1fr]">
              <div className="space-y-4">
                <div>
                  <p className="mb-2 text-sm font-medium text-gray-700">{t('characters.editImageOptions')}</p>
                  <div className="space-y-2">
                    {[
                      { key: 'keepOriginalLayout', label: t('characters.keepOriginalLayout') },
                      { key: 'removeWeapons', label: t('characters.removeWeapons') },
                      { key: 'makeFourView', label: t('characters.makeFourView') },
                      { key: 'other', label: t('characters.otherEdit') },
                    ].map(option => (
                      <label key={option.key} className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm hover:bg-gray-50">
                        <input
                          type="checkbox"
                          checked={imageEditOptions.includes(option.key)}
                          onChange={() => toggleImageEditOption(option.key)}
                          className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                        />
                        {option.label}
                      </label>
                    ))}
                  </div>
                </div>
                {imageEditOptions.includes('other') && (
                  <textarea
                    rows={4}
                    value={imageEditOther}
                    onChange={(event) => setImageEditOther(event.target.value)}
                    className="input-field"
                    placeholder={t('characters.otherEditPlaceholder')}
                  />
                )}
                <button
                  type="button"
                  onClick={handleEditImage}
                  disabled={editingImageId === imageEditCharacter.id}
                  className="btn-primary w-full justify-center disabled:opacity-70"
                >
                  {editingImageId === imageEditCharacter.id ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Image className="mr-2 h-4 w-4" />
                  )}
                  {editingImageId === imageEditCharacter.id ? t('characters.editingImage') : t('characters.editImage')}
                </button>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <p className="mb-2 text-sm font-medium text-gray-700">原图</p>
                  <div className="aspect-square overflow-hidden rounded-lg bg-gray-100">
                    <img src={imageEditCharacter.imageUrl} alt={imageEditCharacter.name} className="h-full w-full object-contain" />
                  </div>
                </div>
                <div>
                  <p className="mb-2 text-sm font-medium text-gray-700">编辑结果</p>
                  <div className="aspect-square overflow-hidden rounded-lg bg-gray-100 flex items-center justify-center">
                    {editingImageId === imageEditCharacter.id ? (
                      <div className="text-center text-sm text-gray-500">
                        <Loader2 className="mx-auto mb-2 h-8 w-8 animate-spin text-primary-600" />
                        {t('characters.editingImage')}
                      </div>
                    ) : imageEditResultUrl ? (
                      <img
                        src={imageEditResultUrl}
                        alt={`${imageEditCharacter.name} edited`}
                        className="h-full w-full object-contain"
                        onLoad={(event) => setImageEditResultSize({
                          width: event.currentTarget.naturalWidth,
                          height: event.currentTarget.naturalHeight,
                        })}
                      />
                    ) : (
                      <span className="text-sm text-gray-400">生成后在这里预览</span>
                    )}
                  </div>
                  {imageEditResultUrl && (
                    <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                      <span className="text-sm text-gray-500">
                        {imageEditResultSize ? `${imageEditResultSize.width} x ${imageEditResultSize.height} px` : ''}
                      </span>
                      <button
                        type="button"
                        onClick={handleReplaceImage}
                        disabled={replacingImageId === imageEditCharacter.id}
                        className="btn-primary disabled:opacity-70"
                      >
                        {replacingImageId === imageEditCharacter.id && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                        {t('characters.replaceImage')}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

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
