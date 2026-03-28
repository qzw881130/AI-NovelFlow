/**
 * AudioGenTab - 音频生成 Tab
 *
 * 四栏布局：
 * - 左 1：章节角色列表（显示当前章节有台词的所有角色，可收缩）
 * - 左 2：分镜角色列表（显示当前分镜有台词的角色）
 * - 右侧：编辑区域（编辑台词、情感提示词，播放/上传音频）
 * - 最右：ComfyUI 状态
 */

import { useState, useRef } from 'react';
import { useChapterGenerateStore, useShotNavigatorSlice } from '../stores';
import { useResizable } from '../../../hooks/useResizable';
import { useTranslation } from '../../../stores/i18nStore';
import {
  Mic,
  Play,
  Pause,
  Upload,
  Trash2,
  UserPlus,
  Volume2,
  VolumeX,
  Loader2,
  ChevronRight,
  Check,
  Plus,
  X,
  Square,
  Save,
} from 'lucide-react';
import { shotsApi } from '../../../api/shots';
import { characterApi } from '../../../api/characters';
import type { Character as CharacterType } from '../types';
import type { DialogueData, Shot } from '../stores/slices/types';
import ComfyUIStatus from '../../../components/ComfyUIStatus';

interface AudioGenTabProps {
  novelId: string;
  chapterId: string;
}

// 角色卡片组件 - 章节角色列表
interface ChapterCharacterCardProps {
  character: CharacterType;
  isSelected: boolean;
  isInCurrentShot: boolean;
  isAdding: boolean;
  onSelect: (charId: string, charName: string) => void;
  onAddToShot: (charName: string, e: React.MouseEvent) => void;
  onPlayVoice: (charId: string, e: React.MouseEvent) => void;
  isPlaying: boolean;
  t: (key: string) => string;
}

function ChapterCharacterCard({
  character,
  isSelected,
  isInCurrentShot,
  isAdding,
  onSelect,
  onAddToShot,
  onPlayVoice,
  isPlaying,
  t,
}: ChapterCharacterCardProps) {
  return (
    <div
      onClick={() => onSelect(character.id, character.name)}
      className={`p-3 border border-gray-200 rounded-lg cursor-pointer hover:bg-gray-50 transition-all ${
        isSelected ? 'bg-blue-50 border-blue-300' : ''
      } ${isInCurrentShot ? 'border-l-4 border-l-green-500' : ''}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium text-gray-900 truncate">
              {character.name}
            </p>
            {isInCurrentShot && (
              <Check className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />
            )}
          </div>
          {character.voicePrompt && (
            <p className="text-xs text-gray-500 mt-1 line-clamp-2" title={character.voicePrompt}>
              {character.voicePrompt}
            </p>
          )}
          {character.referenceAudioUrl && (
            <button
              onClick={(e) => onPlayVoice(character.id, e)}
              className="mt-1.5 flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800"
            >
              {isPlaying ? (
                <>
                  <Volume2 className="w-3 h-3 animate-pulse" />
                  {t('chapterGenerate.playingVoice')}
                </>
              ) : (
                <>
                  <VolumeX className="w-3 h-3" />
                  {t('chapterGenerate.previewVoice')}
                </>
              )}
            </button>
          )}
        </div>
        {!isInCurrentShot && (
          <button
            onClick={(e) => onAddToShot(character.name, e)}
            disabled={isAdding}
            className="p-1 text-gray-400 hover:text-green-600 hover:bg-green-50 rounded transition-colors flex-shrink-0"
            title={t('chapterGenerate.addToCurrentShot')}
          >
            {isAdding ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Plus className="w-4 h-4" />
            )}
          </button>
        )}
      </div>
    </div>
  );
}

// 角色卡片组件 - 分镜角色列表
interface ShotCharacterCardProps {
  charName: string;
  isSelected: boolean;
  dialogue?: DialogueData;
  hasAudio: boolean;
  isRemoving: boolean;
  isNarrator?: boolean;
  onSelect: (charName: string) => void;
  onRemove: (charName: string, e: React.MouseEvent) => void;
  t: (key: string) => string;
}

function ShotCharacterCard({
  charName,
  isSelected,
  dialogue,
  hasAudio,
  isRemoving,
  isNarrator,
  onSelect,
  onRemove,
  t,
}: ShotCharacterCardProps) {
  return (
    <div
      onClick={() => onSelect(charName)}
      className={`p-3 border border-gray-200 rounded-lg cursor-pointer hover:bg-gray-50 transition-all ${
        isSelected ? (isNarrator ? 'bg-purple-50 border-purple-300' : 'bg-blue-50 border-blue-300') : ''
      } ${isNarrator ? 'border-l-4 border-l-purple-400' : ''}`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <ChevronRight className={`w-4 h-4 flex-shrink-0 ${isSelected ? (isNarrator ? 'text-purple-500' : 'text-blue-500') : 'text-gray-400'}`} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <p className="text-sm font-medium text-gray-900 truncate">{charName}</p>
              {isNarrator && (
                <span className="text-xs px-1.5 py-0.5 bg-purple-100 text-purple-600 rounded">{t('chapterGenerate.narration')}</span>
              )}
            </div>
            {dialogue?.text && (
              <p className="text-xs text-gray-500 mt-0.5 line-clamp-1">{dialogue.text}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1">
          {hasAudio && (
            <div className="w-2 h-2 bg-green-500 rounded-full" title={t('chapterGenerate.hasAudio')}></div>
          )}
          {!isNarrator && (
            <button
              onClick={(e) => onRemove(charName, e)}
              disabled={isRemoving}
              className="p-1 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
              title={t('chapterGenerate.removeFromShot')}
            >
              {isRemoving ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <X className="w-3.5 h-3.5" />
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// 音频播放器组件
interface AudioPlayerProps {
  audioUrl: string;
  characterName: string;
  t: (key: string) => string;
}

function AudioPlayer({ audioUrl, characterName, t }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);

  const handlePlay = () => {
    if (!audioRef.current) {
      audioRef.current = new Audio(audioUrl);
      audioRef.current.onended = () => setIsPlaying(false);
      audioRef.current.play();
    } else if (isPlaying) {
      audioRef.current.pause();
      setIsPlaying(false);
    } else {
      audioRef.current.play();
      setIsPlaying(true);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={handlePlay}
        className="p-2 text-blue-600 hover:bg-blue-50 rounded-full transition-colors"
        title={isPlaying ? t('common.pause') : t('common.play')}
      >
        {isPlaying ? (
          <Pause className="w-4 h-4" />
        ) : (
          <Play className="w-4 h-4" />
        )}
      </button>
      <span className="text-xs text-gray-500">
        {characterName} - {isPlaying ? t('chapterGenerate.playingVoice') : t('chapterGenerate.audioGenerated')}
      </span>
    </div>
  );
}

export function AudioGenTab({ novelId, chapterId }: AudioGenTabProps) {
  const { t } = useTranslation();
  const store = useChapterGenerateStore();
  const { currentShotIndex } = useShotNavigatorSlice();

  const {
    characters,
    chapterCharacters,
    shots,
    audioUrls,
    audioSources,
    generatingAudios,
    uploadingAudios,
    audioWarnings,
    generateShotAudio,
    uploadDialogueAudio,
    deleteDialogueAudio,
    updateShot,
  } = store;

  const [selectedChapterChar, setSelectedChapterChar] = useState<string | null>(null);
  const [selectedShotChar, setSelectedShotChar] = useState<string | null>(null);
  const [addingChars, setAddingChars] = useState<Set<string>>(new Set());
  const [editingDialogues, setEditingDialogues] = useState<Record<string, DialogueData>>({});
  const [playingVoiceId, setPlayingVoiceId] = useState<string | null>(null);
  const [leftPanelCollapsed, setLeftPanelCollapsed] = useState(false);
  const [rightPanelCollapsed, setRightPanelCollapsed] = useState(false);
  const [showBatchSelectModal, setShowBatchSelectModal] = useState(false);
  const [selectedShots, setSelectedShots] = useState<Set<number>>(new Set());
  const [isGeneratingAll, setIsGeneratingAll] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [showWarnings, setShowWarnings] = useState(false);

  // 右侧栏可拖动调整宽度
  const rightResizable = useResizable({
    initialWidth: 288,
    minWidth: 200,
    maxWidth: 400,
    collapsedWidth: 48,
    collapsed: rightPanelCollapsed,
    storageKey: 'audioGenerate_rightPanelWidth',
    direction: 'left', // 右侧栏：向左拖动增加宽度
  });

  // 获取当前分镜数据
  const currentShotData: Shot | undefined = shots.find(s => s.index === currentShotIndex);
  const currentShotId = currentShotData?.id || '';
  const currentShotCharacters = currentShotData?.characters || [];
  const currentShotDialogues = currentShotData?.dialogues || [];

  // 获取当前分镜中的旁白角色（从 dialogues 中提取 type='narration' 的）
  const narrationCharacters = currentShotDialogues
    .filter(d => d.type === 'narration')
    .map(d => d.character_name || t('chapterGenerate.narration'));

  // 章节角色列表 - 有台词的角色 + 旁白角色（去重）
  const narratorCharacter = characters.find(c => c.isNarrator);
  const chapterCharactersWithDialogues = [
    ...characters.filter(char => chapterCharacters.includes(char.name)),
    ...(narratorCharacter && chapterCharacters.some(name =>
      shots.some(s => s.dialogues?.some(d => d.type === 'narration'))
    ) && !chapterCharacters.includes(narratorCharacter.name) ? [narratorCharacter] : []),
  ];

  // 分镜角色列表 - 当前分镜有台词的角色 + 旁白角色（去重）
  const shotCharacters = [...new Set([...currentShotCharacters, ...narrationCharacters])];

  // 获取角色的台词数据
  const getDialogueForCharacter = (charName: string): DialogueData | undefined => {
    // 检查是否是旁白角色
    const narratorName = t('chapterGenerate.narration');
    if (charName === narratorName || narrationCharacters.includes(charName)) {
      // 对于旁白，查找 type='narration' 的台词
      return currentShotDialogues.find(d => d.type === 'narration');
    }
    return currentShotDialogues.find(d => d.character_name === charName && d.type !== 'narration');
  };

  // 检查是否是旁白角色
  const isNarratorCharacter = (charName: string): boolean => {
    const narratorName = t('chapterGenerate.narration');
    return charName === narratorName || narrationCharacters.includes(charName);
  };

  // 检查是否有音频
  const hasAudio = (charName: string): boolean => {
    const key = `${currentShotId}-${charName}`;
    return !!audioUrls[key];
  };

  // 获取音频 URL
  const getAudioUrl = (charName: string): string | undefined => {
    const key = `${currentShotId}-${charName}`;
    return audioUrls[key];
  };

  // 检查是否正在生成
  const isGenerating = (charName: string): boolean => {
    const key = `${currentShotId}-${charName}`;
    return generatingAudios.has(key);
  };

  // 检查是否正在上传
  const isUploading = (charName: string): boolean => {
    const key = `${currentShotId}-${charName}`;
    return uploadingAudios.has(key);
  };

  // 处理章节角色选择
  const handleChapterCharacterSelect = (charId: string, charName: string) => {
    setSelectedChapterChar(charId);
    // 如果该角色不在当前分镜，点击添加到分镜
    if (!currentShotCharacters.includes(charName)) {
      handleAddToShot(charName);
    }
  };

  // 添加角色到当前分镜
  const handleAddToShot = async (charName: string) => {
    if (!currentShotData || currentShotCharacters.includes(charName)) return;

    setAddingChars(prev => new Set(prev).add(charName));
    try {
      const updatedCharacters = [...currentShotCharacters, charName];
      await updateShot(currentShotData.id, { characters: updatedCharacters });

      // 同时添加默认台词
      const newDialogue: DialogueData = {
        character_name: charName,
        text: '',
        emotion_prompt: '',
      };
      const updatedDialogues = [...currentShotDialogues, newDialogue];
      await updateShot(currentShotData.id, { dialogues: updatedDialogues });

      setSelectedShotChar(charName);
    } catch (error) {
      console.error('添加角色到分镜失败:', error);
    } finally {
      setAddingChars(prev => {
        const next = new Set(prev);
        next.delete(charName);
        return next;
      });
    }
  };

  // 从分镜移除角色
  const handleRemoveFromShot = async (charName: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!currentShotData) return;

    try {
      const updatedCharacters = currentShotCharacters.filter(c => c !== charName);
      const updatedDialogues = currentShotDialogues.filter(d => d.character_name !== charName);

      await updateShot(currentShotData.id, {
        characters: updatedCharacters,
        dialogues: updatedDialogues,
      });

      if (selectedShotChar === charName) {
        setSelectedShotChar(null);
      }
    } catch (error) {
      console.error('从分镜移除角色失败:', error);
    }
  };

  // 添加旁白到当前分镜
  const handleAddNarratorToShot = async () => {
    if (!currentShotData) return;

    const narratorName = t('chapterGenerate.narration');
    const newDialogue: DialogueData = {
      type: 'narration',
      order: currentShotDialogues.length,
      character_name: narratorName,
      text: '',
      emotion_prompt: '',
    };

    try {
      const updatedDialogues = [...currentShotDialogues, newDialogue];
      await updateShot(currentShotData.id, { dialogues: updatedDialogues });
      setSelectedShotChar(narratorName);
    } catch (error) {
      console.error('添加旁白失败:', error);
    }
  };

  // 处理分镜角色选择
  const handleShotCharacterSelect = (charName: string) => {
    setSelectedShotChar(charName);
  };

  // 播放角色音色
  const handlePlayVoice = async (charId: string, e: React.MouseEvent) => {
    e.stopPropagation();

    if (playingVoiceId === charId) {
      setPlayingVoiceId(null);
      return;
    }

    try {
      const char = characters.find(c => c.id === charId);
      if (char?.referenceAudioUrl) {
        setPlayingVoiceId(charId);
        const audio = new Audio(char.referenceAudioUrl);
        audio.onended = () => setPlayingVoiceId(null);
        audio.play();
      }
    } catch (error) {
      console.error('播放音色失败:', error);
      setPlayingVoiceId(null);
    }
  };

  // 更新台词
  const handleDialogueChange = (charName: string, field: keyof DialogueData, value: string) => {
    const isNarrator = isNarratorCharacter(charName);
    const currentDialogue = getDialogueForCharacter(charName);
    const updated: DialogueData = {
      ...currentDialogue,
      type: isNarrator ? 'narration' : 'character',
      character_name: charName,
      text: field === 'text' ? value : currentDialogue?.text || '',
      emotion_prompt: field === 'emotion_prompt' ? value : currentDialogue?.emotion_prompt || '',
    };
    setEditingDialogues(prev => ({ ...prev, [charName]: updated }));
  };

  // 保存台词
  const handleSaveDialogue = async (charName: string) => {
    if (!currentShotData || !editingDialogues[charName]) return;

    try {
      const isNarrator = isNarratorCharacter(charName);
      const updatedDialogues = currentShotDialogues.map(d => {
        // 对于旁白，按 type 匹配；对于普通角色，按 character_name 匹配
        if (isNarrator && d.type === 'narration') {
          return editingDialogues[charName]!;
        }
        if (!isNarrator && d.character_name === charName && d.type !== 'narration') {
          return editingDialogues[charName]!;
        }
        return d;
      });
      await updateShot(currentShotData.id, { dialogues: updatedDialogues });
      setEditingDialogues(prev => {
        const next = { ...prev };
        delete next[charName];
        return next;
      });
    } catch (error) {
      console.error('保存台词失败:', error);
    }
  };

  // 生成音频
  const handleGenerateAudio = async (charName: string) => {
    if (!currentShotData) {
      console.error('当前分镜数据不存在');
      return;
    }

    const dialogue = editingDialogues[charName] || getDialogueForCharacter(charName);
    if (!dialogue || !dialogue.text) {
      alert('请输入台词文本');
      return;
    }

    const isNarrator = isNarratorCharacter(charName);

    // 只传递必要的字段给后端
    const dialogueData: DialogueData = {
      type: isNarrator ? 'narration' : 'character',
      character_name: charName,
      text: dialogue.text,
      emotion_prompt: dialogue.emotion_prompt || '',
    };

    console.log('生成音频请求:', {
      novelId,
      chapterId,
      shotIndex: currentShotIndex,
      dialogues: [dialogueData],
    });

    try {
      await generateShotAudio(novelId, chapterId, currentShotData.id, [dialogueData]);
      console.log('音频生成任务已提交');
    } catch (error) {
      console.error('生成音频失败:', error);
      alert('生成失败：' + (error as Error).message);
    }
  };

  // 上传音频
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const handleUploadAudio = (charName: string) => {
    fileInputRef.current?.click();
    // 存储当前选中的角色名供后续使用
    (fileInputRef.current as any).dataset.charName = charName;
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    const charName = (e.target as any).dataset.charName;

    if (!file || !charName || !currentShotData) return;

    try {
      await uploadDialogueAudio(novelId, chapterId, currentShotData.id, charName, file);
    } catch (error) {
      console.error('上传音频失败:', error);
    }

    e.target.value = '';
  };

  // 删除音频
  const handleDeleteAudio = async (charName: string) => {
    if (!currentShotData) return;

    try {
      await deleteDialogueAudio(novelId, chapterId, currentShotData.id, charName);
    } catch (error) {
      console.error('删除音频失败:', error);
    }
  };

  // ========== 批量生成音频功能 ==========

  // 打开批量选择弹窗
  const handleOpenBatchSelect = () => {
    // 初始化选择：默认选中所有有对话的分镜
    const shotsWithDialogues = shots.filter(s => s.dialogues && s.dialogues.length > 0).map(s => s.index);
    setSelectedShots(new Set(shotsWithDialogues));
    setShowBatchSelectModal(true);
  };

  // 切换分镜选择状态
  const toggleShotSelection = (index: number) => {
    // 检查该分镜是否有对话
    const shot = shots.find(s => s.index === index);
    const hasDialogues = shot?.dialogues && shot.dialogues.length > 0;
    if (!hasDialogues) return; // 没有对话的分镜不能被选择

    setSelectedShots(prev => {
      const newSet = new Set(prev);
      if (newSet.has(index)) {
        newSet.delete(index);
      } else {
        newSet.add(index);
      }
      return newSet;
    });
  };

  // 全选/取消全选
  const toggleSelectAll = () => {
    // 只选择有对话的分镜
    const shotsWithDialogues = shots.filter(s => s.dialogues && s.dialogues.length > 0).map(s => s.index);
    const allSelected = shotsWithDialogues.every(index => selectedShots.has(index));

    if (allSelected) {
      setSelectedShots(new Set());
    } else {
      setSelectedShots(new Set(shotsWithDialogues));
    }
  };

  // 处理批量生成音频
  const handleGenerateAllAudio = async () => {
    if (!novelId || !chapterId) return;
    setIsGeneratingAll(true);
    try {
      console.log('开始批量生成音频，选中的分镜:', Array.from(selectedShots));

      // 依次生成选中的分镜音频
      for (const shotIndex of selectedShots) {
        const shot = shots.find(s => s.index === shotIndex);
        console.log(`分镜 ${shotIndex}:`, shot);

        if (shot?.dialogues && shot.dialogues.length > 0) {
          // 过滤出必要的字段，包含 type
          const dialoguesData: DialogueData[] = shot.dialogues.map(d => ({
            type: d.type || 'character',
            character_name: d.character_name,
            text: d.text,
            emotion_prompt: d.emotion_prompt || '',
          }));

          console.log(`生成分镜 ${shotIndex} 的音频，dialogues:`, dialoguesData);

          const result = await generateShotAudio(novelId, chapterId, shot.id, dialoguesData);
          console.log(`分镜 ${shotIndex} 生成结果:`, result);
        }
      }
    } catch (error) {
      console.error('批量生成音频失败:', error);
      alert('批量生成失败：' + (error as Error).message);
    } finally {
      setIsGeneratingAll(false);
      setShowBatchSelectModal(false);
    }
  };

  // ========== 保存分镜信息功能 ==========

  // 保存当前分镜信息
  const handleSaveShot = async () => {
    if (!currentShotData || !novelId || !chapterId) return;

    setIsSaving(true);
    try {
      // 调用批量更新接口保存当前分镜
      const result = await shotsApi.batchUpdateShots(novelId, chapterId, [currentShotData]);

      if (result.success) {
        console.log('分镜保存成功');
      } else {
        console.error('分镜保存失败:', result.message);
      }
    } catch (error) {
      console.error('分镜保存失败:', error);
    } finally {
      setIsSaving(false);
    }
  };

  // 渲染编辑区域
  const renderEditPanel = () => {
    const dialogue = selectedShotChar ? (editingDialogues[selectedShotChar] || getDialogueForCharacter(selectedShotChar)) : null;
    const audioKey = selectedShotChar ? `${currentShotId}-${selectedShotChar}` : '';
    const hasGeneratedAudio = selectedShotChar ? !!audioUrls[audioKey] : false;
    const isGen = selectedShotChar ? isGenerating(selectedShotChar) : false;
    const isUpload = selectedShotChar ? isUploading(selectedShotChar) : false;
    const isNarrator = selectedShotChar ? isNarratorCharacter(selectedShotChar) : false;

    if (!selectedShotChar) {
      return (
        <div className="flex items-center justify-center h-full text-gray-500 text-sm">
          {t('chapterGenerate.selectCharacterToEdit')}
        </div>
      );
    }

    return (
      <div className="space-y-4">
        {/* 角色信息 */}
        <div className="pb-3 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-semibold text-gray-900">{selectedShotChar}</h3>
            {isNarrator && (
              <span className="text-xs px-2 py-1 bg-purple-100 text-purple-600 rounded">{t('chapterGenerate.narration')}</span>
            )}
          </div>
        </div>

        {/* 台词文本 */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            {isNarrator ? t('chapterGenerate.narration') : t('chapterGenerate.dialogueText')}
          </label>
          <textarea
            value={dialogue?.text || ''}
            onChange={(e) => handleDialogueChange(selectedShotChar, 'text', e.target.value)}
            placeholder={t('chapterGenerate.dialogueTextPlaceholder')}
            rows={3}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
          />
        </div>

        {/* 情感提示词 */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            {t('chapterGenerate.emotionPrompt')}
          </label>
          <input
            type="text"
            value={dialogue?.emotion_prompt || ''}
            onChange={(e) => handleDialogueChange(selectedShotChar, 'emotion_prompt', e.target.value)}
            placeholder={t('chapterGenerate.emotionPromptExample')}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
          />
        </div>

        {/* 编辑保存按钮 */}
        {editingDialogues[selectedShotChar] && (
          <button
            onClick={() => handleSaveDialogue(selectedShotChar)}
            className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium"
          >
            {t('common.saveChanges')}
          </button>
        )}

        {/* 音频区域 */}
        <div className="pt-3 border-t border-gray-200">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            {t('chapterGenerate.audio')}
          </label>

          {hasGeneratedAudio ? (
            <div className="space-y-2">
              {/* 播放已有音频 */}
              <AudioPlayer
                audioUrl={audioUrls[audioKey]}
                characterName={selectedShotChar}
                t={t}
              />

              {/* 操作按钮 */}
              <div className="flex gap-2">
                <button
                  onClick={() => handleGenerateAudio(selectedShotChar)}
                  disabled={isGen}
                  className="flex-1 px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm flex items-center justify-center gap-1"
                >
                  {isGen ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      {t('chapterGenerate.generating')}
                    </>
                  ) : (
                    <>
                      <Mic className="w-3.5 h-3.5" />
                      {t('chapterGenerate.regenerate')}
                    </>
                  )}
                </button>
                <button
                  onClick={() => handleDeleteAudio(selectedShotChar)}
                  className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
                  title={t('common.delete')}
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <button
                onClick={() => handleGenerateAudio(selectedShotChar)}
                disabled={isGen || !(dialogue?.text)}
                className="w-full px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm flex items-center justify-center gap-1"
              >
                {isGen ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    {t('chapterGenerate.generating')}
                  </>
                ) : (
                  <>
                    <Mic className="w-3.5 h-3.5" />
                    {t('chapterGenerate.generateAudio')}
                  </>
                )}
              </button>

              <div className="relative">
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="text-gray-400 text-xs">{t('common.or')}</span>
                </div>
                <div className="border-t border-gray-200"></div>
              </div>

              <button
                onClick={() => handleUploadAudio(selectedShotChar)}
                disabled={isUpload}
                className="w-full px-3 py-1.5 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50 text-sm flex items-center justify-center gap-1"
              >
                {isUpload ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    {t('chapterGenerate.uploading')}
                  </>
                ) : (
                  <>
                    <Upload className="w-3.5 h-3.5" />
                    {t('chapterGenerate.uploadFromLocal')}
                  </>
                )}
              </button>

              <input
                ref={fileInputRef}
                type="file"
                accept="audio/*"
                onChange={handleFileChange}
                className="hidden"
                data-char-name=""
              />
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="h-full flex flex-col">
      {/* 隐藏的文件输入 */}
      <input
        ref={fileInputRef}
        type="file"
        accept="audio/mpeg,audio/mp3,audio/wav,audio/x-wav,audio/flac,audio/x-flac"
        onChange={handleFileChange}
        className="hidden"
      />

      {/* 主体内容区 */}
      <div className="flex-1 min-h-0 flex overflow-hidden">
        {/* 左 1：章节角色列表（可收缩） */}
      <div
        className={`relative flex-shrink-0 transition-all duration-200 ease-in-out ${
          leftPanelCollapsed ? 'w-12' : 'w-64'
        }`}
      >
        <div className="h-full border-r border-gray-200 flex flex-col bg-gray-50">
          {!leftPanelCollapsed && (
            <>
              <div className="p-3 border-b border-gray-200 bg-gray-50">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-medium text-gray-700">{t('chapterGenerate.chapterCharacters')}</h3>
                    <p className="text-xs text-gray-500 mt-0.5">{t('chapterGenerate.clickToAddToShot')}</p>
                  </div>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto p-2 space-y-2">
                {chapterCharactersWithDialogues.map((char) => (
                  <ChapterCharacterCard
                    key={char.id}
                    character={char}
                    isSelected={selectedChapterChar === char.id}
                    isInCurrentShot={currentShotCharacters.includes(char.name)}
                    isAdding={addingChars.has(char.name)}
                    onSelect={handleChapterCharacterSelect}
                    onAddToShot={(name, e) => {
                      e.stopPropagation();
                      handleAddToShot(name);
                    }}
                    onPlayVoice={handlePlayVoice}
                    isPlaying={playingVoiceId === char.id}
                    t={t}
                  />
                ))}
                {/* 添加旁白按钮 */}
                {narrationCharacters.length === 0 && (
                  <button
                    onClick={() => handleAddNarratorToShot()}
                    className="w-full p-3 border-2 border-dashed border-purple-300 rounded-lg text-sm text-purple-600 hover:border-purple-500 hover:bg-purple-50 transition-colors flex items-center justify-center gap-2"
                  >
                    <Plus className="w-4 h-4" />
                    {t('chapterGenerate.addNarration')}
                  </button>
                )}
                {chapterCharactersWithDialogues.length === 0 && narrationCharacters.length > 0 && (
                  <div className="p-4 text-center text-gray-500 text-sm">
                    {t('chapterGenerate.noCharactersInChapter')}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* 收起/展开按钮 */}
        <button
          onClick={() => setLeftPanelCollapsed(!leftPanelCollapsed)}
          className={`absolute top-4 z-10 w-6 h-6 bg-white border border-gray-200 rounded-full shadow-sm flex items-center justify-center hover:bg-gray-50 transition-colors ${
            leftPanelCollapsed ? '-right-3' : '-right-3'
          }`}
          title={leftPanelCollapsed ? t('common.expand') : t('common.collapse')}
        >
          {leftPanelCollapsed ? (
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          ) : (
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          )}
        </button>
      </div>

      {/* 左 2：分镜角色列表和编辑区域容器 */}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        {/* 顶部操作栏 - 跨越分镜角色列表和编辑区域 */}
        <div className="flex-shrink-0 flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-white">
          <div className="flex items-center gap-4">
            <button
              onClick={handleOpenBatchSelect}
              disabled={isGeneratingAll || !chapterId}
              className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2 whitespace-nowrap"
            >
              {isGeneratingAll ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {t('chapterGenerate.generating')}
                </>
              ) : (
                <>
                  <Mic className="w-4 h-4" />
                  {t('chapterGenerate.batchGenerate')}
                </>
              )}
            </button>
            <button
              onClick={handleSaveShot}
              disabled={isSaving || !chapterId}
              className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2 whitespace-nowrap"
            >
              {isSaving ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {t('chapterGenerate.saving')}
                </>
              ) : (
                <>
                  <Save className="w-4 h-4" />
                  {t('chapterGenerate.saveShot')}
                </>
              )}
            </button>
          </div>
          <div className="text-sm text-gray-500">
            {t('chapterGenerate.shot', { number: currentShotIndex })} / {shots.length}
          </div>
        </div>

        {/* 警告信息显示 */}
        {audioWarnings.length > 0 && (
          <div className="mx-4 mt-2 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
            <div className="flex items-start justify-between">
              <div className="flex items-start gap-2">
                <span className="text-yellow-600 text-sm font-medium">⚠️ {t('chapterGenerate.audioWarnings', { count: audioWarnings.length })}</span>
              </div>
              <button
                onClick={() => setShowWarnings(!showWarnings)}
                className="text-xs text-yellow-700 hover:text-yellow-900"
              >
                {showWarnings ? t('common.collapse') : t('common.expand')}
              </button>
            </div>
            {showWarnings && (
              <ul className="mt-2 space-y-1">
                {audioWarnings.map((warning, idx) => (
                  <li key={idx} className="text-xs text-yellow-700">
                    • {warning.character_name}: {warning.reason}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* 分镜角色列表和编辑区域 */}
        <div className="flex-1 min-w-0 flex overflow-hidden">
          {/* 左侧：分镜角色列表 */}
          <div className="w-56 flex-shrink-0 border-r border-gray-200 flex flex-col">
            <div className="p-3 border-b border-gray-200 bg-gray-50">
              <h3 className="text-sm font-medium text-gray-700">{t('chapterGenerate.shotCharacters')}</h3>
              <p className="text-xs text-gray-500 mt-0.5">{t('chapterGenerate.shotNumber', { number: currentShotIndex })}</p>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-2">
              {shotCharacters.map((charName) => (
                <ShotCharacterCard
                  key={charName}
                  charName={charName}
                  isSelected={selectedShotChar === charName}
                  dialogue={getDialogueForCharacter(charName)}
                  hasAudio={hasAudio(charName)}
                  isRemoving={addingChars.has(charName)}
                  isNarrator={isNarratorCharacter(charName)}
                  onSelect={handleShotCharacterSelect}
                  onRemove={handleRemoveFromShot}
                  t={t}
                />
              ))}
              {shotCharacters.length === 0 && (
                <div className="p-4 text-center text-gray-500 text-sm">
                  {t('chapterGenerate.noCharactersInCurrentShot')}
                </div>
              )}
            </div>
          </div>

          {/* 右侧：编辑区域 */}
          <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
            {/* 编辑内容区 */}
            <div className="flex-1 overflow-y-auto p-6">
              {renderEditPanel()}
            </div>
          </div>
        </div>
      </div>

      {/* 最右：ComfyUI 状态（可收缩、可拖拽调整宽度） */}
      <div
        className="relative flex-shrink-0 transition-all duration-200 ease-in-out"
        style={{
          width: rightPanelCollapsed ? 48 : rightResizable.width,
        }}
      >
        {/* 拖动把手 */}
        {!rightPanelCollapsed && (
          <div
            onMouseDown={rightResizable.handleMouseDown}
            className="absolute top-0 left-0 w-1 h-full cursor-col-resize hover:bg-blue-200 hover:opacity-50 transition-colors z-20"
          />
        )}

        {/* 收起/展开按钮 */}
        <button
          onClick={() => setRightPanelCollapsed(!rightPanelCollapsed)}
          className="absolute -left-3 top-4 z-30 w-6 h-6 bg-white border border-gray-200 rounded-full shadow-sm flex items-center justify-center hover:bg-gray-50 transition-colors"
          title={rightPanelCollapsed ? t('common.expand') : t('common.collapse')}
        >
          {rightPanelCollapsed ? (
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          ) : (
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          )}
        </button>

        <div className="h-full border-l border-gray-200 flex flex-col bg-gray-50">
          {!rightPanelCollapsed && (
            <div className="flex-1 overflow-y-auto p-4">
              <ComfyUIStatus />
            </div>
          )}
        </div>
      </div>

      {/* 批量选择分镜弹窗 */}
      {showBatchSelectModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col">
            {/* 弹窗头部 */}
            <div className="flex items-center justify-between p-4 border-b border-gray-200">
              <div>
                <h3 className="text-lg font-semibold text-gray-800">{t('chapterGenerate.selectShotsForAudio')}</h3>
                <p className="text-xs text-gray-500 mt-1">{t('chapterGenerate.selectShotsHint')}</p>
              </div>
              <button
                onClick={() => setShowBatchSelectModal(false)}
                className="p-2 hover:bg-gray-100 rounded-full transition-colors"
                title={t('common.close')}
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            {/* 弹窗内容 - 分镜列表 */}
            <div className="flex-1 overflow-y-auto p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm text-gray-600">
                  {t('chapterGenerate.selectedShotsWithDialogue', { selected: selectedShots.size, total: shots.filter(s => s.dialogues && s.dialogues.length > 0).length })}
                </span>
                <button
                  onClick={toggleSelectAll}
                  disabled={shots.filter(s => s.dialogues && s.dialogues.length > 0).length === 0}
                  className="text-sm text-blue-600 hover:text-blue-800 flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {selectedShots.size === shots.filter(s => s.dialogues && s.dialogues.length > 0).length ? (
                    <>
                      <Square className="w-4 h-4" />
                      {t('common.deselectAll')}
                    </>
                  ) : (
                    <>
                      <Check className="w-4 h-4" />
                      {t('common.selectAll')}
                    </>
                  )}
                </button>
              </div>

              <div className="grid grid-cols-4 gap-3">
                {shots.map((shot) => {
                  const shotIndex = shot.index;
                  const isSelected = selectedShots.has(shotIndex);
                  const hasDialogues = shot.dialogues && shot.dialogues.length > 0;
                  const hasAudio = shot.dialogues?.some(d => d.audio_url);
                  const isDisabled = !hasDialogues;

                  return (
                    <div
                      key={shot.id}
                      onClick={() => !isDisabled && toggleShotSelection(shotIndex)}
                      className={`
                        relative aspect-square rounded-lg border-2 transition-all
                        ${isDisabled
                          ? 'border-gray-200 bg-gray-100 cursor-not-allowed'
                          : isSelected
                            ? 'border-blue-500 bg-blue-50 hover:border-blue-400 cursor-pointer'
                            : 'border-gray-300 bg-white hover:border-blue-300 cursor-pointer'
                        }
                      `}
                    >
                      {/* 分镜编号 */}
                      <div className="absolute top-1 left-1 px-1.5 py-0.5 bg-black/60 text-white text-xs rounded">
                        #{shotIndex}
                      </div>

                      {/* 选择标记 - 只有有对话的分镜显示 */}
                      {!isDisabled && (
                        <div className={`
                          absolute top-1 right-1 w-5 h-5 rounded-full flex items-center justify-center
                          ${isSelected ? 'bg-blue-500' : 'bg-gray-200'}
                        `}>
                          {isSelected && <Check className="w-3 h-3 text-white" />}
                        </div>
                      )}

                      {/* 内容区域 */}
                      <div className="w-full h-full flex flex-col items-center justify-center p-2">
                        {hasDialogues ? (
                          <>
                            <Mic className={`w-6 h-6 mb-1 ${hasAudio ? 'text-green-500' : 'text-gray-400'}`} />
                            <span className="text-xs text-gray-600 text-center">
                              {t('chapterGenerate.characterCount', { count: shot.dialogues.length })}
                            </span>
                            {hasAudio && (
                              <span className="text-xs text-green-600 mt-0.5">{t('chapterGenerate.hasAudio')}</span>
                            )}
                          </>
                        ) : (
                          <>
                            <Mic className="w-6 h-6 text-gray-300 mb-1" />
                            <span className="text-xs text-gray-400 text-center">{t('chapterGenerate.noDialogue')}</span>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* 弹窗底部按钮 */}
            <div className="flex items-center justify-end gap-3 p-4 border-t border-gray-200">
              <button
                onClick={() => setShowBatchSelectModal(false)}
                className="px-4 py-2 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleGenerateAllAudio}
                disabled={selectedShots.size === 0 || isGeneratingAll}
                className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
              >
                {isGeneratingAll ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    {t('chapterGenerate.generating')}
                  </>
                ) : (
                  <>
                    <Mic className="w-4 h-4" />
                    {t('chapterGenerate.generateAudioForShots', { count: selectedShots.size })}
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    </div>
  );
}

export default AudioGenTab;
