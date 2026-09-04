/**
 * ShotForm - 分镜可视化表单组件
 *
 * 替代 JSON 编辑器的可视化表单，包含：
 * - 分镜描述编辑（文本域）
 * - 角色选择（多选下拉）
 * - 场景选择（单选下拉）
 * - 道具选择（多选下拉）
 *
 * 数据源统一使用 store.shots（从后端 Shot 表获取）
 */

import { useState, useMemo, useEffect } from 'react';
import { Copy } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import { useChapterGenerateStore } from '../stores';
import { toast } from '../../../stores/toastStore';
import { dialogueEmotion, dialogueText, estimateDialogueSeconds, getDialogueDurationWarning } from '../../../utils';
import type { DialogueData } from '../types';
import type { Shot } from '../../../api/shots';
import type { AudioDriveEvent, AudioEventType } from '../../../api/audioDrive';

interface ShotFormProps {
  /** 当前分镜索引 */
  shotIndex: number;
  /** 分镜数据（Shot 类型） */
  shotData?: Shot;
  /** 分镜数据变化回调 */
  onChange?: (shotData: Partial<Shot>) => void;
  /** 可用角色列表（从章节级资源读取） */
  availableCharacters?: string[];
  /** 可用场景列表（从章节级资源读取） */
  availableScenes?: string[];
  /** 可用道具列表（从章节级资源读取） */
  availableProps?: string[];
  /** 只读模式 */
  readOnly?: boolean;
  /** 是否显示台词编辑（默认 true） */
  showDialogues?: boolean;
  /** 是否显示视频描述编辑（默认 false） */
  showVideoDescription?: boolean;
  /** 是否显示时长编辑（默认 false） */
  showDuration?: boolean;
  /** 保存快捷键回调 */
  onSave?: () => void | Promise<void>;
}

const pauseAfterOptions: Array<{ value: AudioDriveEvent['pauseAfter']; label: string }> = [
  { value: 'NONE', label: 'NONE · 0.0s' },
  { value: 'SHORT', label: 'SHORT · 0.3s' },
  { value: 'MEDIUM', label: 'MEDIUM · 0.6s' },
  { value: 'LONG', label: 'LONG · 1.2s' },
];

export function ShotForm({
  shotIndex: propShotIndex,
  shotData: propShotData,
  onChange,
  availableCharacters: propAvailableCharacters,
  availableScenes: propAvailableScenes,
  availableProps: propAvailableProps,
  readOnly = false,
  showDialogues = true,
  showVideoDescription = false,
  showDuration = false,
  onSave,
}: ShotFormProps) {
  const { t } = useTranslation();
  const currentShotIndex = useChapterGenerateStore((state) => state.currentShotIndex);
  const storeShots = useChapterGenerateStore((state) => state.shots);
  const setShots = useChapterGenerateStore((state) => state.setShots);

  // 从 store 获取章节级资源
  const chapterCharacters = useChapterGenerateStore((state) => state.chapterCharacters);
  const chapterScenes = useChapterGenerateStore((state) => state.chapterScenes);
  const chapterProps = useChapterGenerateStore((state) => state.chapterProps);
  const libraryCharacters = useChapterGenerateStore((state) => state.characters);
  const libraryScenes = useChapterGenerateStore((state) => state.scenes);
  const libraryProps = useChapterGenerateStore((state) => state.props);

  // 优先使用 props 中的 shotIndex 和 shotData，否则从 store 获取
  const shotIndex = propShotIndex || currentShotIndex;
  const shotData = propShotData || storeShots[shotIndex - 1];

  const mergeNames = (primary: string[], library: any[]) => {
    const names = library.map((item) => item?.name).filter(Boolean);
    return Array.from(new Set([...primary, ...names]));
  };

  // 可用资源：章节资源 + 小说资源库，避免手动创建的资源无法在分镜里选择。
  const availableCharacters = propAvailableCharacters || mergeNames(chapterCharacters, libraryCharacters);
  const availableScenes = propAvailableScenes || mergeNames(chapterScenes, libraryScenes);
  const availableProps = propAvailableProps || mergeNames(chapterProps, libraryProps);

  // 本地状态
  const [description, setDescription] = useState(shotData?.description || '');
  const [videoDescription, setVideoDescription] = useState(shotData?.video_description || '');
  const [selectedCharacters, setSelectedCharacters] = useState<string[]>(shotData?.characters || []);
  const [selectedScene, setSelectedScene] = useState(shotData?.scene || '');
  const [selectedProps, setSelectedProps] = useState<string[]>(shotData?.props || []);
  const [estimatedDuration, setEstimatedDuration] = useState(shotData?.estimatedDuration || shotData?.duration || 5);
  const [duration, setDuration] = useState(shotData?.duration || 5);
  const [continuityMode, setContinuityMode] = useState(shotData?.continuity_mode || 'NORMAL');
  const [dialogues, setDialogues] = useState<DialogueData[]>(shotData?.dialogues || []);
  const [audioEvents, setAudioEvents] = useState<AudioDriveEvent[]>(shotData?.audioEvents || []);

  // 当 shotIndex 或 shotData 变化时，同步本地状态
  useEffect(() => {
    if (shotData) {
      setDescription(shotData.description || '');
      setVideoDescription(shotData.video_description || '');
      setSelectedCharacters(shotData.characters || []);
      setSelectedScene(shotData.scene || '');
      setSelectedProps(shotData.props || []);
      setEstimatedDuration(shotData.estimatedDuration || shotData.duration || 5);
      setDuration(shotData.duration || 5);
      setContinuityMode(shotData.continuity_mode || 'NORMAL');
      setDialogues(shotData.dialogues || []);
      setAudioEvents(shotData.audioEvents || []);
    }
  }, [shotIndex, shotData]);

  // 搜索状态
  const [characterSearch, setCharacterSearch] = useState('');
  const [sceneSearch, setSceneSearch] = useState('');
  const [propSearch, setPropSearch] = useState('');

  // 下拉框展开状态
  const [characterExpanded, setCharacterExpanded] = useState(false);
  const [sceneExpanded, setSceneExpanded] = useState(false);
  const [propExpanded, setPropExpanded] = useState(false);

  // 过滤后的选项
  const filteredCharacters = useMemo(() => {
    return availableCharacters.filter((c) =>
      c.toLowerCase().includes(characterSearch.toLowerCase())
    );
  }, [availableCharacters, characterSearch]);

  const filteredScenes = useMemo(() => {
    return availableScenes.filter((s) =>
      s.toLowerCase().includes(sceneSearch.toLowerCase())
    );
  }, [availableScenes, sceneSearch]);

  const filteredProps = useMemo(() => {
    return availableProps.filter((p) =>
      p.toLowerCase().includes(propSearch.toLowerCase())
    );
  }, [availableProps, propSearch]);

  // 同步本地状态到父组件和 store
  const handleChange = () => {
    const newShotData: Partial<Shot> = {
      description,
      video_description: videoDescription,
      characters: selectedCharacters,
      scene: selectedScene,
      props: selectedProps,
      estimatedDuration,
      duration,
      continuity_mode: continuityMode,
      dialogues,
      audioEvents,
    };
    onChange?.(newShotData);
  };

  // 同步到 store.shots
  const syncToStore = () => {
    if (shotData?.id) {
      const updatedShots = storeShots.map((shot) =>
        shot.id === shotData.id
          ? {
              ...shot,
              description,
              video_description: videoDescription,
              characters: selectedCharacters,
              scene: selectedScene,
              props: selectedProps,
              estimatedDuration,
              duration,
              continuity_mode: continuityMode,
              dialogues,
              audioEvents,
            }
          : shot
      );
      setShots(updatedShots);
    }
  };

  // 处理变化
  useEffect(() => {
    handleChange();
    syncToStore();
  }, [description, videoDescription, selectedCharacters, selectedScene, selectedProps, estimatedDuration, duration, continuityMode, dialogues, audioEvents]);

  // 处理角色选择切换
  const toggleCharacter = (charName: string) => {
    setSelectedCharacters((prev) =>
      prev.includes(charName)
        ? prev.filter((c) => c !== charName)
        : [...prev, charName]
    );
  };

  // 处理道具选择切换
  const toggleProp = (propName: string) => {
    setSelectedProps((prev) =>
      prev.includes(propName)
        ? prev.filter((p) => p !== propName)
        : [...prev, propName]
    );
  };

  // 台词编辑相关函数
  const addDialogue = (type: 'character' | 'narration' = 'character') => {
    const newOrder = dialogues.length;
    if (type === 'narration') {
      setDialogues([...dialogues, {
        character_name: '旁白',
        text: '',
        emotion_prompt: ''
      }]);
    } else {
      setDialogues([...dialogues, {
        character_name: '',
        text: '',
        emotion_prompt: ''
      }]);
    }
  };

  const removeDialogue = (index: number) => {
    const newDialogues = dialogues.filter((_, i) => i !== index);
    setDialogues(newDialogues);
  };

  const updateDialogue = (index: number, field: keyof DialogueData, value: string | number) => {
    const newDialogues = [...dialogues];
    newDialogues[index] = { ...newDialogues[index], [field]: value };
    setDialogues(newDialogues);
  };

  const addAudioEvent = (type: AudioEventType = 'DIALOGUE') => {
    const isNarration = type === 'NARRATION';
    const newEvent: AudioDriveEvent = {
      id: `local-${Date.now()}-${audioEvents.length}`,
      shotId: shotData?.id || '',
      order: audioEvents.length,
      type,
      voiceOwnerName: isNarration ? '旁白' : '',
      visibleSpeakerName: isNarration ? null : '',
      requiresVisibleLipsync: type === 'DIALOGUE',
      text: '',
      emotionPrompt: '',
      pauseAfter: 'NONE',
      ttsStatus: 'NOT_GENERATED',
    };
    setAudioEvents([...audioEvents, newEvent]);
  };

  const removeAudioEvent = (index: number) => {
    setAudioEvents(audioEvents.filter((_, i) => i !== index).map((event, order) => ({ ...event, order })));
  };

  const updateAudioEvent = (index: number, field: keyof AudioDriveEvent, value: string | boolean) => {
    const nextEvents = [...audioEvents];
    nextEvents[index] = { ...nextEvents[index], [field]: value };
    if (field === 'type') {
      const type = value as AudioEventType;
      nextEvents[index].requiresVisibleLipsync = type === 'DIALOGUE';
      if (type === 'NARRATION') {
        nextEvents[index].voiceOwnerName = nextEvents[index].voiceOwnerName || '旁白';
        nextEvents[index].visibleSpeakerName = null;
      }
    }
    setAudioEvents(nextEvents);
  };

  const copyText = async (content: string) => {
    if (!content) return;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(content);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = content;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      toast.success(t('common.copied'));
    } catch (error) {
      console.error('复制分镜文本失败:', error);
      toast.error(t('common.copyFailed'));
    }
  };

  // 台词编辑区域展开/收起状态
  const [dialoguesExpanded, setDialoguesExpanded] = useState(false);

  useEffect(() => {
    if (!onSave) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        onSave();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onSave]);

  const dialogueDurationTotal = dialogues.reduce((total, dialogue) => (
    total + estimateDialogueSeconds(dialogueText(dialogue), dialogueEmotion(dialogue))
  ), 0);
  const dialogueWarning = getDialogueDurationWarning(estimatedDuration, dialogueDurationTotal);
  const audioEventCounts = audioEvents.reduce(
    (stats, event) => ({
      eventCount: stats.eventCount + 1,
      visibleLipsyncCount: stats.visibleLipsyncCount + (event.requiresVisibleLipsync ? 1 : 0),
      narrationCount: stats.narrationCount + (event.type === 'NARRATION' ? 1 : 0),
    }),
    { eventCount: 0, visibleLipsyncCount: 0, narrationCount: 0 }
  );

  return (
    <div className="shot-form space-y-4">
      {/* 分镜描述 */}
      <div className="shot-description-field">
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium text-gray-700">
            {t('chapterGenerate.shotDescForImage')}
          </label>
          <button
            type="button"
            onClick={() => copyText(description)}
            disabled={!description}
            className="p-1.5 text-gray-400 hover:text-blue-600 transition-colors rounded hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed"
            title={t('common.copy')}
            aria-label={t('common.copy')}
          >
            <Copy className="h-4 w-4" />
          </button>
        </div>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          disabled={readOnly}
          rows={4}
          className="shot-description-textarea input-field"
          placeholder={t('chapterGenerate.shotDescPlaceholder')}
        />
      </div>

      {/* 视频描述 */}
      {showVideoDescription && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="block text-sm font-medium text-gray-700">
              {t('chapterGenerate.videoDescForVideo')}
            </label>
            <button
              type="button"
              onClick={() => copyText(videoDescription)}
              disabled={!videoDescription}
              className="p-1.5 text-gray-400 hover:text-blue-600 transition-colors rounded hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed"
              title={t('common.copy')}
              aria-label={t('common.copy')}
            >
              <Copy className="h-4 w-4" />
            </button>
          </div>
          <textarea
            value={videoDescription}
            onChange={(e) => setVideoDescription(e.target.value)}
            disabled={readOnly}
            rows={4}
            className="input-field"
            placeholder={t('chapterGenerate.videoDescPlaceholder')}
          />
        </div>
      )}

      <div className={showDialogues ? 'grid grid-cols-1 lg:grid-cols-2 gap-4 items-start' : 'space-y-4'}>
      <div className="space-y-4 min-w-0">
      {/* 角色选择 */}
      <div className="min-w-0">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('chapterGenerate.appearingCharacters')}
        </label>
        <div className="min-h-7 mb-2 flex flex-wrap gap-1 items-start">
          {selectedCharacters.length > 0 && (
            <>
            {selectedCharacters.map((charName) => (
              <span
                key={charName}
                className="inline-flex items-center gap-1 px-2 py-1 bg-blue-100 text-blue-700 rounded text-xs"
              >
                {charName}
                <button
                  onClick={() => toggleCharacter(charName)}
                  className="hover:text-blue-900"
                >
                  ×
                </button>
              </span>
            ))}
            </>
          )}
        </div>
        <button
          onClick={() => setCharacterExpanded(!characterExpanded)}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 flex items-center justify-between mb-2 input-field"
        >
          <span>{characterExpanded ? t('common.collapse') : characterSearch || t('chapterGenerate.selectCharacterFromLibrary')}</span>
          <svg className={`w-4 h-4 transition-transform ${characterExpanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
        {characterExpanded && (
          <div className="border border-gray-300 rounded-lg overflow-hidden">
            <input
              type="text"
              value={characterSearch}
              onChange={(e) => setCharacterSearch(e.target.value)}
              className="w-full px-3 py-2 border-b border-gray-300 focus:outline-none text-sm input-field border-none rounded-none"
              placeholder={t('chapterGenerate.selectCharacter')}
              autoFocus
            />
            <div className="max-h-40 overflow-y-auto p-2 space-y-1">
              {filteredCharacters.map((charName) => (
                <label
                  key={charName}
                  className="flex items-center gap-2 p-2 hover:bg-gray-50 rounded cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selectedCharacters.includes(charName)}
                    onChange={() => toggleCharacter(charName)}
                    className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                  />
                  <span className="text-sm text-gray-700">{charName}</span>
                </label>
              ))}
              {filteredCharacters.length === 0 && (
                <p className="text-sm text-gray-500 p-2">{t('chapterGenerate.noCharactersInLibrary')}</p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 场景选择 */}
      <div className="min-w-0">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('chapterGenerate.scene')}
        </label>
        <div className="min-h-7 mb-2 flex flex-wrap gap-1 items-start">
          {selectedScene && (
            <span className="inline-flex items-center px-2 py-1 bg-green-100 text-green-700 rounded text-xs">
              {selectedScene}
              <button
                onClick={() => setSelectedScene('')}
                className="ml-1 hover:text-green-900"
              >
                ×
              </button>
            </span>
          )}
        </div>
        <button
          onClick={() => setSceneExpanded(!sceneExpanded)}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 flex items-center justify-between mb-2 input-field"
        >
          <span>{sceneExpanded ? t('common.collapse') : selectedScene || t('chapterGenerate.selectSceneFromLibrary')}</span>
          <svg className={`w-4 h-4 transition-transform ${sceneExpanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
        {sceneExpanded && (
          <div className="border border-gray-300 rounded-lg overflow-hidden">
            <input
              type="text"
              value={sceneSearch}
              onChange={(e) => setSceneSearch(e.target.value)}
              className="w-full px-3 py-2 border-b border-gray-300 focus:outline-none text-sm input-field border-none rounded-none"
              placeholder={t('chapterGenerate.selectScene')}
              autoFocus
            />
            <div className="max-h-40 overflow-y-auto p-2 space-y-1">
              {filteredScenes.map((sceneName) => (
                <label
                  key={sceneName}
                  className="flex items-center gap-2 p-2 hover:bg-gray-50 rounded cursor-pointer"
                >
                  <input
                    type="radio"
                    name="scene"
                    checked={selectedScene === sceneName}
                    onChange={() => setSelectedScene(sceneName)}
                    className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                  />
                  <span className="text-sm text-gray-700">{sceneName}</span>
                </label>
              ))}
              {filteredScenes.length === 0 && (
                <p className="text-sm text-gray-500 p-2">{t('chapterGenerate.noScenesInLibrary')}</p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 道具选择 */}
      <div className="min-w-0">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('chapterGenerate.props')}
        </label>
        <div className="min-h-7 mb-2 flex flex-wrap gap-1 items-start">
          {selectedProps.length > 0 && (
            <>
            {selectedProps.map((propName) => (
              <span
                key={propName}
                className="inline-flex items-center gap-1 px-2 py-1 bg-purple-100 text-purple-700 rounded text-xs"
              >
                {propName}
                <button
                  onClick={() => toggleProp(propName)}
                  className="hover:text-purple-900"
                >
                  ×
                </button>
              </span>
            ))}
            </>
          )}
        </div>
        <button
          onClick={() => setPropExpanded(!propExpanded)}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 flex items-center justify-between mb-2 input-field"
        >
          <span>{propExpanded ? t('common.collapse') : propSearch || t('chapterGenerate.selectPropFromLibrary')}</span>
          <svg className={`w-4 h-4 transition-transform ${propExpanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
        {propExpanded && (
          <div className="border border-gray-300 rounded-lg overflow-hidden">
            <input
              type="text"
              value={propSearch}
              onChange={(e) => setPropSearch(e.target.value)}
              className="w-full px-3 py-2 border-b border-gray-300 focus:outline-none text-sm input-field border-none rounded-none"
              placeholder={t('chapterGenerate.selectProp')}
              autoFocus
            />
            <div className="max-h-40 overflow-y-auto p-2 space-y-1">
              {filteredProps.map((propName) => (
                <label
                  key={propName}
                  className="flex items-center gap-2 p-2 hover:bg-gray-50 rounded cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selectedProps.includes(propName)}
                    onChange={() => toggleProp(propName)}
                    className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                  />
                  <span className="text-sm text-gray-700">{propName}</span>
                </label>
              ))}
              {filteredProps.length === 0 && (
                <p className="text-sm text-gray-500 p-2">{t('chapterGenerate.noPropsInLibrary')}</p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 时长设置 */}
      {showDuration && (
        <div className="min-w-0">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            预计时长
          </label>
          <input
            type="number"
            value={estimatedDuration}
            onChange={(e) => setEstimatedDuration(Math.min(180, Math.max(1, parseInt(e.target.value) || 5)))}
            disabled={readOnly}
            min={1}
            max={180}
            className="input-field"
          />
          <p className="text-xs text-gray-500 mt-1">Shot Director 预估值，Audio Timeline READY 后以 resolved duration 为准。</p>
          <p className="text-xs text-gray-500 mt-1">当前 resolved duration: {duration}{t('common.second')}</p>
        </div>
      )}

      {showDuration && (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            镜头连续性
          </label>
          <select
            value={continuityMode}
            onChange={(e) => setContinuityMode(e.target.value)}
            disabled={readOnly}
            className="input-field"
          >
            <option value="NORMAL">普通镜头（允许切镜）</option>
            <option value="CONTINUOUS_TAKE">一镜到底（禁止切镜）</option>
          </select>
          <p className="text-xs text-gray-500 mt-1">Shot 级剪辑方式约束，不是 Single / First-Last / Multi-Keyframe 生成模式。</p>
        </div>
      )}
      </div>

      {/* 角色台词 */}
      {showDialogues && (
        <div>
          <div className="mb-4 rounded-lg border border-cyan-100 bg-cyan-50/40 p-3">
            <div className="flex items-center justify-between gap-3 mb-3">
              <div>
                <label className="text-sm font-medium text-gray-700">Audio Events</label>
                <p className="text-xs text-gray-500 mt-1">
                  声音语义源：{audioEventCounts.eventCount} events · {audioEventCounts.visibleLipsyncCount} 口型 · {audioEventCounts.narrationCount} 旁白
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => addAudioEvent('DIALOGUE')}
                  disabled={readOnly}
                  className="px-2 py-1 text-xs rounded bg-cyan-600 text-white hover:bg-cyan-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  + 对白
                </button>
                <button
                  type="button"
                  onClick={() => addAudioEvent('NARRATION')}
                  disabled={readOnly}
                  className="px-2 py-1 text-xs rounded bg-gray-700 text-white hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  + 旁白
                </button>
              </div>
            </div>

            <div className="space-y-3">
              {audioEvents.map((event, idx) => (
                <div key={event.id || idx} className="rounded-lg border border-gray-200 bg-white p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-gray-500">Event {idx + 1} · {event.ttsStatus || 'NOT_GENERATED'}</span>
                    <button
                      type="button"
                      onClick={() => removeAudioEvent(idx)}
                      disabled={readOnly}
                      className="text-xs text-red-600 hover:text-red-800 disabled:opacity-50"
                    >
                      {t('common.delete')}
                    </button>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">类型</label>
                      <select
                        value={event.type}
                        onChange={(e) => updateAudioEvent(idx, 'type', e.target.value as AudioEventType)}
                        disabled={readOnly}
                        className="input-field text-sm"
                      >
                        <option value="DIALOGUE">对白</option>
                        <option value="NARRATION">旁白</option>
                        <option value="INNER_MONOLOGUE">内心独白</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">Voice Owner</label>
                      <select
                        value={event.voiceOwnerName || ''}
                        onChange={(e) => updateAudioEvent(idx, 'voiceOwnerName', e.target.value)}
                        disabled={readOnly}
                        className="input-field text-sm"
                      >
                        <option value="">选择音色角色</option>
                        <option value="旁白">旁白</option>
                        {availableCharacters.map((charName) => (
                          <option key={charName} value={charName}>{charName}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">Visible Speaker</label>
                      <select
                        value={event.visibleSpeakerName || ''}
                        onChange={(e) => updateAudioEvent(idx, 'visibleSpeakerName', e.target.value)}
                        disabled={readOnly || event.type === 'NARRATION'}
                        className="input-field text-sm"
                      >
                        <option value="">无可见说话人</option>
                        {availableCharacters.map((charName) => (
                          <option key={charName} value={charName}>{charName}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">Pause After</label>
                      <select
                        value={event.pauseAfter || 'NONE'}
                        onChange={(e) => updateAudioEvent(idx, 'pauseAfter', e.target.value)}
                        disabled={readOnly}
                        className="input-field text-sm"
                      >
                        {pauseAfterOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                      </select>
                    </div>
                  </div>

                  <label className="inline-flex items-center gap-2 text-xs text-gray-600">
                    <input
                      type="checkbox"
                      checked={event.requiresVisibleLipsync}
                      onChange={(e) => updateAudioEvent(idx, 'requiresVisibleLipsync', e.target.checked)}
                      disabled={readOnly || event.type === 'NARRATION'}
                      className="rounded border-gray-300 text-cyan-600 focus:ring-cyan-500"
                    />
                    requires visible lipsync
                  </label>

                  <div>
                    <label className="block text-xs text-gray-500 mb-1">文本</label>
                    <textarea
                      value={event.text || ''}
                      onChange={(e) => updateAudioEvent(idx, 'text', e.target.value)}
                      disabled={readOnly}
                      rows={2}
                      className="input-field text-sm"
                      placeholder="输入对白、旁白或内心独白文本"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">情绪提示</label>
                    <input
                      type="text"
                      value={event.emotionPrompt || ''}
                      onChange={(e) => updateAudioEvent(idx, 'emotionPrompt', e.target.value)}
                      disabled={readOnly}
                      className="input-field text-sm"
                      placeholder="例如：压低声音、迟疑、克制愤怒"
                    />
                  </div>
                </div>
              ))}

              {audioEvents.length === 0 && (
                <p className="text-xs text-gray-500 text-center py-4 bg-white rounded border border-dashed border-gray-200">暂无 Audio Events。旧章节可继续使用下方兼容台词，或新增声音事件。</p>
              )}
            </div>
          </div>

          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium text-gray-700 flex items-center gap-2">
              <span>{t('chapterGenerate.dialogues')}（兼容旧数据）</span>
              {dialogues.length > 0 && (
                <span className={`rounded-full border px-2 py-0.5 text-xs font-normal ${dialogueWarning.style.className}`}>
                  {dialogueWarning.style.label} · 最低 {dialogueDurationTotal.toFixed(2)}s / 当前 {dialogueWarning.duration.toFixed(0)}s
                  {dialogueWarning.level !== 'normal' && ` · 建议至少 ${dialogueWarning.suggestedDuration}s`}
                </span>
              )}
            </label>
            <button
              onClick={() => setDialoguesExpanded(!dialoguesExpanded)}
              className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1"
            >
              {dialoguesExpanded ? t('common.collapse') : t('common.expand')}
              <svg className={`w-3 h-3 transition-transform ${dialoguesExpanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
          </div>

          {/* 已选台词概览 */}
          {!dialoguesExpanded && dialogues.length > 0 && (
            <div className="space-y-2 mb-2">
              {dialogues.map((d, idx) => (
                <div key={idx} className="text-xs p-2 bg-gray-50 rounded border border-gray-200 flex items-start gap-2">
                  <span className="font-medium text-blue-600">{d.character_name || t('chapterGenerate.selectCharacter')}</span>
                  <span className="text-gray-600 flex-1">{d.text}</span>
                  <span className="text-gray-500 whitespace-nowrap">
                    最低所需 {estimateDialogueSeconds(dialogueText(d), dialogueEmotion(d)).toFixed(2)}s
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* 展开编辑 */}
          {dialoguesExpanded && (
            <div className="space-y-3">
              {dialogues.map((dialogue, idx) => (
                <div key={idx} className="border border-gray-200 rounded-lg p-3 space-y-2 bg-gray-50">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-gray-500">
                      {t('chapterGenerate.dialogues')} {idx + 1}
                      <span className="ml-2 font-normal">
                        最低所需 {estimateDialogueSeconds(dialogueText(dialogue), dialogueEmotion(dialogue)).toFixed(2)}s
                      </span>
                    </span>
                    <button
                      onClick={() => removeDialogue(idx)}
                      className="text-xs text-red-600 hover:text-red-800"
                    >
                      {t('common.delete')}
                    </button>
                  </div>

                  <div>
                    <label className="block text-xs text-gray-500 mb-1">{t('chapterGenerate.characters')}</label>
                    <select
                      value={dialogue.character_name}
                      onChange={(e) => updateDialogue(idx, 'character_name', e.target.value)}
                      disabled={readOnly}
                      className="input-field text-sm"
                    >
                      <option value="">{t('chapterGenerate.selectCharacter')}</option>
                      {availableCharacters.map((charName) => (
                        <option key={charName} value={charName}>
                          {charName}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs text-gray-500 mb-1">{t('chapterGenerate.dialogueTextPlaceholder')}</label>
                    <textarea
                      value={dialogue.text}
                      onChange={(e) => updateDialogue(idx, 'text', e.target.value)}
                      disabled={readOnly}
                      rows={2}
                      className="input-field text-sm"
                      placeholder={t('chapterGenerate.dialogueTextPlaceholder')}
                    />
                  </div>

                  <div>
                    <label className="block text-xs text-gray-500 mb-1">{t('chapterGenerate.emotionPrompt')}</label>
                    <input
                      type="text"
                      value={dialogue.emotion_prompt || ''}
                      onChange={(e) => updateDialogue(idx, 'emotion_prompt', e.target.value)}
                      disabled={readOnly}
                      className="input-field text-sm"
                      placeholder={t('chapterGenerate.emotionPromptPlaceholder')}
                    />
                  </div>
                </div>
              ))}

              {dialogues.length === 0 && (
                <p className="text-xs text-gray-500 text-center py-4">{t('chapterGenerate.noDialogues')}</p>
              )}

              <button
                onClick={() => addDialogue('character')}
                disabled={readOnly || availableCharacters.length === 0}
                className="w-full px-3 py-2 border-2 border-dashed border-gray-300 rounded-lg text-sm text-gray-600 hover:border-blue-500 hover:text-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                + {t('chapterGenerate.addDialogue')}
              </button>
            </div>
          )}
        </div>
      )}
      </div>
    </div>
  );
}

export default ShotForm;
