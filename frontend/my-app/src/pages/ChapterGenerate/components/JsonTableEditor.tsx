import { useState, useEffect, useRef } from 'react';
import {
  Users,
  MapPin,
  Package,
  Plus,
  Trash2,
  X,
  AlertCircle,
  MessageSquare,
  Mic,
  Loader2,
  Volume2,
  Play,
  Square,
  RefreshCw,
  Upload,
  Music
} from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import type { JsonTableEditorProps, DialogueData } from '../types';

export default function JsonTableEditor({
  value,
  onChange,
  availableScenes = [],
  availableCharacters = [],
  availableProps = [],
  activeShotWorkflow,
  audioUrls = {},
  audioSources = {},
  isShotAudioGenerating,
  getShotAudioTasks,
  onRegenerateAudio,
  onGenerateDialogueAudio,
  onUploadDialogueAudio,
  onDeleteDialogueAudio,
  isAudioUploading,
}: JsonTableEditorProps) {
  const { t } = useTranslation();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string>('');
  const [activeSection, setActiveSection] = useState<'characters' | 'scenes' | 'shots' | 'props'>('shots');
  // 存储角色输入的临时值（key: shotIndex, value: 输入字符串）
  const [characterInputs, setCharacterInputs] = useState<Record<number, string>>({});
  // 存储道具输入的临时值（key: shotIndex, value: 输入字符串）
  const [propInputs, setPropInputs] = useState<Record<number, string>>({});
  // 当前选中的分镜索引
  const [activeShotIndex, setActiveShotIndex] = useState<number>(0);
  // 当前播放的音频
  const [playingAudio, setPlayingAudio] = useState<string | null>(null); // key: "shotIndex_characterName"
  const audioRef = useState<HTMLAudioElement | null>(null)[0];
  const [, setAudioElement] = useState<HTMLAudioElement | null>(null);

  // 台词本地编辑缓存（key: "shotIndex_dialogueIndex", value: { text, emotion_prompt }）
  // 用于在用户输入时保持输入框状态稳定，避免因 JSON 更新导致的重渲染问题
  const [dialogueEditCache, setDialogueEditCache] = useState<Record<string, { text: string; emotion_prompt: string }>>({});

  // 台词角色历史缓存（key: "shotIndex_dialogueIndex_characterName", value: { text, emotion_prompt }）
  // 用于在切换角色时恢复之前该角色在该台词位置的内容
  const [dialogueCharacterHistory, setDialogueCharacterHistory] = useState<Record<string, { text: string; emotion_prompt: string }>>({});
  
  // 验证分镜场景是否在场景库中
  const getInvalidShotIndices = () => {
    if (!data?.shots || availableScenes.length === 0) return [];
    return data.shots
      .map((shot: any, idx: number) => ({ idx, scene: shot.scene }))
      .filter((item: any) => item.scene && !availableScenes.includes(item.scene))
      .map((item: any) => item.idx);
  };
  
  const invalidShotIndices = getInvalidShotIndices();
  const hasInvalidScenes = invalidShotIndices.length > 0;

  // 解析JSON
  useEffect(() => {
    try {
      if (value.trim()) {
        const parsed = JSON.parse(value);
        setData(parsed);
        setError('');
        // 外部数据变化时清除本地输入状态
        setCharacterInputs({});
      } else {
        setData(null);
      }
    } catch (e) {
      setError(t('chapterGenerate.jsonFormatError'));
    }
  }, [value]);

  // 更新JSON
  const updateJson = (newData: any) => {
    setData(newData);
    onChange(JSON.stringify(newData, null, 2));
  };

  // 更新角色
  const updateCharacter = (index: number, value: string) => {
    if (!data) return;
    const newCharacters = [...(data.characters || [])];
    newCharacters[index] = value;
    updateJson({ ...data, characters: newCharacters });
  };

  // 添加角色
  const addCharacter = () => {
    if (!data) return;
    const newCharacters = [...(data.characters || []), t('chapterGenerate.newCharacter')];
    updateJson({ ...data, characters: newCharacters });
  };

  // 删除角色
  const removeCharacter = (index: number) => {
    if (!data) return;
    const newCharacters = (data.characters || []).filter((_: any, i: number) => i !== index);
    updateJson({ ...data, characters: newCharacters });
  };

  // 更新场景
  const updateScene = (index: number, value: string) => {
    if (!data) return;
    const newScenes = [...(data.scenes || [])];
    newScenes[index] = value;
    updateJson({ ...data, scenes: newScenes });
  };

  // 添加场景
  const addScene = () => {
    if (!data) return;
    const newScenes = [...(data.scenes || []), t('chapterGenerate.newScene')];
    updateJson({ ...data, scenes: newScenes });
  };

  // 删除场景
  const removeScene = (index: number) => {
    if (!data) return;
    const newScenes = (data.scenes || []).filter((_: any, i: number) => i !== index);
    updateJson({ ...data, scenes: newScenes });
  };

  // 更新分镜
  const updateShot = (index: number, field: string, value: any) => {
    if (!data) return;
    const newShots = [...(data.shots || [])];
    newShots[index] = { ...newShots[index], [field]: value };
    updateJson({ ...data, shots: newShots });
  };

  // 添加分镜
  const addShot = () => {
    if (!data) return;
    const newShot = {
      index: (data.shots?.length || 0) + 1,
      description: t('chapterGenerate.newShotDesc'),
      video_description: '',
      characters: [],
      scene: '',
      props: [],
      duration: 4
    };
    updateJson({ ...data, shots: [...(data.shots || []), newShot] });
  };

  // 删除分镜
  const removeShot = (index: number) => {
    if (!data) return;
    const newShots = (data.shots || []).filter((_: any, i: number) => i !== index);
    // 重新编号
    newShots.forEach((shot: any, i: number) => { shot.index = i + 1; });
    updateJson({ ...data, shots: newShots });
  };

  // ==================== 台词管理 ====================

  // 添加台词
  const addDialogue = (shotIndex: number) => {
    if (!data) return;
    const newShots = [...(data.shots || [])];
    const shot = newShots[shotIndex];
    if (!shot.dialogues) {
      shot.dialogues = [];
    }
    // 添加空白台词
    shot.dialogues.push({
      character_name: '',
      text: '',
      emotion_prompt: '自然'
    });
    updateJson({ ...data, shots: newShots });
  };

  // 更新台词
  const updateDialogue = (shotIndex: number, dialogueIndex: number, field: string, value: string) => {
    if (!data) return;

    // 更新本地编辑缓存
    const cacheKey = `${shotIndex}_${dialogueIndex}`;
    setDialogueEditCache(prev => ({
      ...prev,
      [cacheKey]: {
        text: field === 'text' ? value : (prev[cacheKey]?.text ?? data.shots[shotIndex]?.dialogues?.[dialogueIndex]?.text ?? ''),
        emotion_prompt: field === 'emotion_prompt' ? value : (prev[cacheKey]?.emotion_prompt ?? data.shots[shotIndex]?.dialogues?.[dialogueIndex]?.emotion_prompt ?? '自然')
      }
    }));

    const newShots = [...(data.shots || [])];
    const shot = newShots[shotIndex];
    if (shot.dialogues && shot.dialogues[dialogueIndex]) {
      shot.dialogues[dialogueIndex] = {
        ...shot.dialogues[dialogueIndex],
        [field]: value
      };
      updateJson({ ...data, shots: newShots });
    }
  };

  // 获取台词的本地缓存值（用于输入框显示）
  const getDialogueLocalValue = (shotIndex: number, dialogueIndex: number, field: 'text' | 'emotion_prompt', dialogue: DialogueData) => {
    const cacheKey = `${shotIndex}_${dialogueIndex}`;
    const cached = dialogueEditCache[cacheKey];
    if (cached && cached[field] !== undefined) {
      return cached[field];
    }
    return dialogue[field] || '';
  };

  // 清除台词本地缓存（当角色切换时）
  const clearDialogueCache = (shotIndex: number, dialogueIndex: number) => {
    const cacheKey = `${shotIndex}_${dialogueIndex}`;
    setDialogueEditCache(prev => {
      const newCache = { ...prev };
      delete newCache[cacheKey];
      return newCache;
    });
  };

  // 切换台词角色时的处理
  const handleDialogueCharacterChange = (shotIndex: number, dialogueIndex: number, newCharacterName: string) => {
    if (!data) return;

    const shot = data.shots[shotIndex];
    const oldCharacterName = shot.dialogues?.[dialogueIndex]?.character_name;
    const oldDialogue = shot.dialogues?.[dialogueIndex];

    // 如果角色没有变化，不需要处理
    if (oldCharacterName === newCharacterName) return;

    // 清除该台词条目的本地编辑缓存
    const cacheKey = `${shotIndex}_${dialogueIndex}`;
    setDialogueEditCache(prev => {
      const newCache = { ...prev };
      delete newCache[cacheKey];
      return newCache;
    });

    // 计算历史缓存的 key
    const newHistoryKey = `${shotIndex}_${dialogueIndex}_${newCharacterName}`;

    // 使用函数式更新来获取最新的缓存状态
    setDialogueCharacterHistory(prev => {
      // 保存旧角色的台词到历史缓存（如果有内容）
      const updatedHistory = { ...prev };
      if (oldCharacterName && (oldDialogue?.text || oldDialogue?.emotion_prompt)) {
        const oldHistoryKey = `${shotIndex}_${dialogueIndex}_${oldCharacterName}`;
        updatedHistory[oldHistoryKey] = {
          text: oldDialogue.text || '',
          emotion_prompt: oldDialogue.emotion_prompt || '自然'
        };
      }

      // 从历史缓存中恢复新角色的台词
      const cachedDialogue = updatedHistory[newHistoryKey];

      const newShots = [...(data.shots || [])];
      const targetShot = newShots[shotIndex];
      if (targetShot.dialogues && targetShot.dialogues[dialogueIndex]) {
        if (cachedDialogue) {
          // 恢复缓存的台词和情感
          targetShot.dialogues[dialogueIndex] = {
            ...targetShot.dialogues[dialogueIndex],
            character_name: newCharacterName,
            text: cachedDialogue.text,
            emotion_prompt: cachedDialogue.emotion_prompt
          };
        } else {
          // 没有缓存，使用默认值
          targetShot.dialogues[dialogueIndex] = {
            ...targetShot.dialogues[dialogueIndex],
            character_name: newCharacterName,
            text: '',
            emotion_prompt: '自然'
          };
        }
        updateJson({ ...data, shots: newShots });
      }

      return updatedHistory;
    });
  };

  // 删除台词
  const removeDialogue = (shotIndex: number, dialogueIndex: number) => {
    if (!data) return;
    const newShots = [...(data.shots || [])];
    const shot = newShots[shotIndex];
    if (shot.dialogues) {
      shot.dialogues = shot.dialogues.filter((_: any, i: number) => i !== dialogueIndex);
      updateJson({ ...data, shots: newShots });
    }
  };

  // ==================== 音频播放管理 ====================

  // 播放/暂停音频
  const toggleAudioPlay = (shotIndex: number, characterName: string, audioUrl: string) => {
    const key = `${shotIndex}_${characterName}`;

    if (playingAudio === key) {
      // 暂停当前播放
      setPlayingAudio(null);
    } else {
      // 播放新音频
      setPlayingAudio(key);
    }
  };

  // 获取台词的音频 URL
  const getDialogueAudioUrl = (shotIndex: number, characterName: string, dialogue?: DialogueData) => {
    // 优先从外部传入的 audioUrls 获取（实时任务生成的）
    const key = `${shotIndex + 1}_${characterName}`;
    if (audioUrls[key]) {
      return audioUrls[key];
    }
    // 否则从台词数据中获取
    return dialogue?.audio_url;
  };

  // 获取台词的音频任务状态
  const getDialogueAudioStatus = (shotIndex: number, characterName: string) => {
    if (isShotAudioGenerating && isShotAudioGenerating(shotIndex + 1)) {
      const tasks = getShotAudioTasks ? getShotAudioTasks(shotIndex + 1) : [];
      const task = tasks.find(t => t.characterName === characterName);
      if (task) {
        return task.status;
      }
    }
    return null;
  };

  if (error) {
    return (
      <div className="h-[500px] flex items-center justify-center bg-red-50 rounded-lg border border-red-200">
        <div className="text-center">
          <AlertCircle className="h-8 w-8 text-red-400 mx-auto mb-2" />
          <p className="text-red-600 text-sm">{error}</p>
          <p className="text-gray-500 text-xs mt-1">{t('chapterGenerate.checkJsonMode')}</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="h-[500px] flex items-center justify-center bg-gray-50 rounded-lg border border-gray-200">
        <p className="text-gray-400 text-sm">{t('chapterGenerate.noDataYet')}</p>
      </div>
    );
  }

  return (
    <div className="h-[500px] flex flex-col bg-white rounded-lg border border-gray-200 overflow-hidden">
      {/* 标签切换 */}
      <div className="flex border-b border-gray-200">
        <button
          onClick={() => setActiveSection('shots')}
          className={`flex-1 px-4 py-2 text-sm font-medium transition-colors ${
            activeSection === 'shots'
              ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50'
              : 'text-gray-600 hover:bg-gray-50'
          }`}
        >
          {t('chapterGenerate.shots')} ({data.shots?.length || 0})
        </button>
        <button
          onClick={() => setActiveSection('characters')}
          className={`flex-1 px-4 py-2 text-sm font-medium transition-colors ${
            activeSection === 'characters'
              ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50'
              : 'text-gray-600 hover:bg-gray-50'
          }`}
        >
          {t('chapterGenerate.characters')} ({data.characters?.length || 0})
        </button>
        <button
          onClick={() => setActiveSection('scenes')}
          className={`flex-1 px-4 py-2 text-sm font-medium transition-colors ${
            activeSection === 'scenes'
              ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50'
              : 'text-gray-600 hover:bg-gray-50'
          }`}
        >
          {t('chapterGenerate.scenes')} ({data.scenes?.length || 0})
        </button>
        <button
          onClick={() => setActiveSection('props')}
          className={`flex-1 px-4 py-2 text-sm font-medium transition-colors ${
            activeSection === 'props'
              ? 'text-amber-600 border-b-2 border-amber-600 bg-amber-50'
              : 'text-gray-600 hover:bg-gray-50'
          }`}
        >
          {t('chapterGenerate.props')} ({data.props?.length || 0})
        </button>
      </div>

      {/* 内容区域 */}
      <div className="flex-1 overflow-auto p-4">
        {activeSection === 'characters' && (
          <div className="space-y-2">
            {/* 已添加的角色列表 */}
            {data.characters?.map((char: string, idx: number) => (
              <div key={idx} className="flex items-center gap-2">
                <Users className="h-4 w-4 text-blue-500 flex-shrink-0" />
                <span className="flex-1 px-3 py-2 bg-blue-50 text-blue-700 rounded-md text-sm font-medium">
                  {char}
                </span>
                <button
                  onClick={() => removeCharacter(idx)}
                  className="p-2 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-md"
                  title={t('chapterGenerate.removeCharacter')}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
            {/* 从角色库添加角色 */}
            {(() => {
              const existingCharacters = data.characters || [];
              const availableToAdd = availableCharacters.filter(c => !existingCharacters.includes(c));

              if (availableToAdd.length === 0) {
                return (
                  <div className="text-center py-3 text-gray-400 text-sm">
                    {availableCharacters.length === 0
                      ? t('chapterGenerate.noCharactersInLibrary')
                      : t('chapterGenerate.allCharactersAdded')}
                  </div>
                );
              }

              return (
                <div className="flex items-center gap-2">
                  <select
                    onChange={(e) => {
                      if (e.target.value) {
                        const newCharacters = [...(data.characters || []), e.target.value];
                        updateJson({ ...data, characters: newCharacters });
                        e.target.value = '';
                      }
                    }}
                    className="flex-1 px-3 py-2 border border-gray-200 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                    defaultValue=""
                  >
                    <option value="">{t('chapterGenerate.selectCharacterFromLibrary')}</option>
                    {availableToAdd.map((char) => (
                      <option key={char} value={char}>{char}</option>
                    ))}
                  </select>
                </div>
              );
            })()}
          </div>
        )}

        {activeSection === 'scenes' && (
          <div className="space-y-2">
            {/* 已添加的场景列表 */}
            {data.scenes?.map((scene: string, idx: number) => (
              <div key={idx} className="flex items-center gap-2">
                <MapPin className="h-4 w-4 text-green-500 flex-shrink-0" />
                <span className="flex-1 px-3 py-2 bg-green-50 text-green-700 rounded-md text-sm font-medium">
                  {scene}
                </span>
                <button
                  onClick={() => removeScene(idx)}
                  className="p-2 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-md"
                  title={t('chapterGenerate.removeScene')}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
            {/* 从场景库添加场景 */}
            {(() => {
              const existingScenes = data.scenes || [];
              const availableToAdd = availableScenes.filter(s => !existingScenes.includes(s));

              if (availableToAdd.length === 0) {
                return (
                  <div className="text-center py-3 text-gray-400 text-sm">
                    {availableScenes.length === 0
                      ? t('chapterGenerate.noScenesInLibrary')
                      : t('chapterGenerate.allScenesAdded')}
                  </div>
                );
              }

              return (
                <div className="flex items-center gap-2">
                  <select
                    onChange={(e) => {
                      if (e.target.value) {
                        const newScenes = [...(data.scenes || []), e.target.value];
                        updateJson({ ...data, scenes: newScenes });
                        e.target.value = '';
                      }
                    }}
                    className="flex-1 px-3 py-2 border border-gray-200 rounded-md text-sm focus:ring-2 focus:ring-green-500 focus:outline-none"
                    defaultValue=""
                  >
                    <option value="">{t('chapterGenerate.selectSceneFromLibrary')}</option>
                    {availableToAdd.map((scene) => (
                      <option key={scene} value={scene}>{scene}</option>
                    ))}
                  </select>
                </div>
              );
            })()}
          </div>
        )}

        {activeSection === 'props' && (
          <div className="space-y-2">
            {/* 已添加的道具列表 */}
            {data.props?.map((prop: string, idx: number) => (
              <div key={idx} className="flex items-center gap-2">
                <Package className="h-4 w-4 text-amber-500 flex-shrink-0" />
                <span className="flex-1 px-3 py-2 bg-amber-50 text-amber-700 rounded-md text-sm font-medium">
                  {prop}
                </span>
                <button
                  onClick={() => {
                    const newProps = (data.props || []).filter((_: string, i: number) => i !== idx);
                    updateJson({ ...data, props: newProps });
                  }}
                  className="p-2 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-md"
                  title={t('chapterGenerate.removeProp')}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
            {/* 从道具库添加道具 */}
            {(() => {
              const existingProps = data.props || [];
              const availableToAdd = availableProps.filter(p => !existingProps.includes(p));

              if (availableToAdd.length === 0) {
                return (
                  <div className="text-center py-3 text-gray-400 text-sm">
                    {availableProps.length === 0
                      ? t('chapterGenerate.noPropsInLibrary')
                      : t('chapterGenerate.allPropsAdded')}
                  </div>
                );
              }

              return (
                <div className="flex items-center gap-2">
                  <select
                    onChange={(e) => {
                      if (e.target.value) {
                        const newProps = [...(data.props || []), e.target.value];
                        updateJson({ ...data, props: newProps });
                        e.target.value = '';
                      }
                    }}
                    className="flex-1 px-3 py-2 border border-gray-200 rounded-md text-sm focus:ring-2 focus:ring-amber-500 focus:outline-none"
                    defaultValue=""
                  >
                    <option value="">{t('chapterGenerate.selectPropFromLibrary')}</option>
                    {availableToAdd.map((prop) => (
                      <option key={prop} value={prop}>{prop}</option>
                    ))}
                  </select>
                </div>
              );
            })()}
          </div>
        )}

        {activeSection === 'shots' && (
          <div className={`space-y-3 h-full flex flex-col ${hasInvalidScenes && activeShotWorkflow?.nodeMapping?.scene_reference_image_node_id ? 'border-2 border-red-400 rounded-lg p-2' : ''}`}>
            {/* 场景验证错误提示 - 只有配置了场景参考图节点时才显示 */}
            {hasInvalidScenes && activeShotWorkflow?.nodeMapping?.scene_reference_image_node_id && (
              <div className="bg-red-50 border border-red-200 rounded-md p-3 flex items-start gap-2">
                <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="text-sm font-medium text-red-700">
                    检测到 {invalidShotIndices.length} 个分镜使用了不在场景库中的场景：
                  </p>
                  <p className="text-xs text-red-600 mt-1">
                    {invalidShotIndices.map((idx: number) => `Shot ${data.shots[idx].id}: "${data.shots[idx].scene}"`).join('、')}
                  </p>
                  <p className="text-xs text-red-500 mt-1">
                    请修改分镜场景或先到场景库添加对应场景
                  </p>
                </div>
              </div>
            )}
            {/* 分镜 Tab 列表 */}
            {data.shots?.length > 0 && (
              <div className="flex flex-wrap gap-1 border-b border-gray-200 pb-2">
                {data.shots.map((shot: any, idx: number) => {
                  const isInvalidScene = shot.scene && !availableScenes.includes(shot.scene);
                  const showInvalid = isInvalidScene && activeShotWorkflow?.nodeMapping?.scene_reference_image_node_id;
                  return (
                    <button
                      key={idx}
                      onClick={() => setActiveShotIndex(idx)}
                      className={`px-3 py-1.5 text-sm font-medium rounded-t-md transition-colors ${
                        activeShotIndex === idx
                          ? 'text-blue-600 bg-blue-50 border-b-2 border-blue-600'
                          : 'text-gray-600 hover:bg-gray-100'
                      } ${showInvalid ? 'bg-red-100 text-red-600 border-red-400' : ''}`}
                      title={showInvalid ? `场景 "${shot.scene}" 不在场景库中` : ''}
                    >
                      {t('chapterGenerate.shot')}{shot.index}
                      {showInvalid && ' ⚠️'}
                    </button>
                  );
                })}
                <button
                  onClick={addShot}
                  className="px-2 py-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-t-md transition-colors"
                  title={t('chapterGenerate.addShot')}
                >
                  <Plus className="h-4 w-4" />
                </button>
              </div>
            )}
            
            {/* 当前选中的分镜编辑区域 */}
            {data.shots?.length > 0 && activeShotIndex < data.shots.length ? (
              <div className="flex-1 overflow-auto">
                {(() => {
                  const idx = activeShotIndex;
                  const shot = data.shots[idx];
                  return (
                    <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
                      <div className="flex items-center justify-between mb-3">
                        <span className="font-medium text-sm text-gray-700">{t('chapterGenerate.shotId', { id: shot.index, total: data.shots.length })}</span>
                        <div className="flex gap-2">
                          {activeShotIndex > 0 && (
                            <button
                              onClick={() => setActiveShotIndex(activeShotIndex - 1)}
                              className="px-2 py-1 text-xs text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded"
                            >
                              ← {t('chapterGenerate.prevShot')}
                            </button>
                          )}
                          {activeShotIndex < data.shots.length - 1 && (
                            <button
                              onClick={() => setActiveShotIndex(activeShotIndex + 1)}
                              className="px-2 py-1 text-xs text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded"
                            >
                              {t('chapterGenerate.nextShot')} →
                            </button>
                          )}
                          <button
                            onClick={() => {
                              removeShot(idx);
                              if (activeShotIndex >= data.shots.length - 1) {
                                setActiveShotIndex(Math.max(0, data.shots.length - 2));
                              }
                            }}
                            className="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 rounded"
                            title={t('chapterGenerate.deleteShot')}
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </div>
                      <div className="space-y-3">
                        <div>
                          <label className="block text-xs text-gray-500 mb-1">{t('chapterGenerate.shotDescForImage')}</label>
                          <textarea
                            value={shot.description}
                            onChange={(e) => updateShot(idx, 'description', e.target.value)}
                            placeholder={t('chapterGenerate.shotDescPlaceholder')}
                            className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none resize-none"
                            rows={8}
                          />
                          {/* 占位符提示 */}
                          <div className="mt-1.5 p-2 bg-blue-50 rounded-md">
                            <p className="text-xs text-blue-600 font-medium mb-1">{t('chapterGenerate.placeholderHint')}</p>
                            <div className="flex flex-wrap gap-1.5 text-xs text-blue-500">
                              <span className="px-1.5 py-0.5 bg-blue-100 rounded">{t('chapterGenerate.placeholderStyle')}</span>
                              <span className="px-1.5 py-0.5 bg-blue-100 rounded">{t('chapterGenerate.placeholderScene')}</span>
                              <span className="px-1.5 py-0.5 bg-blue-100 rounded">{t('chapterGenerate.placeholderCharacters')}</span>
                              <span className="px-1.5 py-0.5 bg-blue-100 rounded">{t('chapterGenerate.placeholderProps')}</span>
                            </div>
                          </div>
                        </div>
                        <div>
                          <label className="block text-xs text-gray-500 mb-1">{t('chapterGenerate.videoDescForVideo')}</label>
                          <textarea
                            value={shot.video_description || ''}
                            onChange={(e) => updateShot(idx, 'video_description', e.target.value)}
                            placeholder={t('chapterGenerate.videoDescPlaceholder')}
                            className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none resize-none"
                            rows={8}
                          />
                        </div>
                        {/* 场景选择器 - 从当前章节场景列表选择 */}
                        <div className="space-y-2">
                          <label className="block text-xs text-gray-500 mb-1">{t('chapterGenerate.scene')}</label>
                          <select
                            value={shot.scene || ''}
                            onChange={(e) => updateShot(idx, 'scene', e.target.value)}
                            className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                          >
                            <option value="">{t('chapterGenerate.selectSceneFromChapter')}</option>
                            {(data.scenes || []).map((scene: string) => (
                              <option key={scene} value={scene}>{scene}</option>
                            ))}
                          </select>
                        </div>
                        <div className="space-y-2">
                          <label className="block text-xs text-gray-500 mb-1">{t('chapterGenerate.durationLabel')}</label>
                          <input
                            type="number"
                            value={shot.duration}
                            onChange={(e) => updateShot(idx, 'duration', parseInt(e.target.value) || 4)}
                            placeholder={t('chapterGenerate.durationSec')}
                            className="w-24 px-3 py-2 border border-gray-200 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                          />
                        </div>
                        {/* 角色选择器 - 从当前章节角色列表选择 */}
                        <div className="space-y-2">
                          <label className="block text-xs text-gray-500 mb-1">{t('chapterGenerate.charactersLabel')}</label>
                          {/* 已选角色标签 */}
                          <div className="flex flex-wrap gap-1.5">
                            {(shot.characters || []).map((char: string, charIdx: number) => (
                              <span
                                key={charIdx}
                                className="inline-flex items-center gap-1 px-2 py-1 bg-blue-100 text-blue-700 rounded-full text-xs font-medium"
                              >
                                <Users className="h-3 w-3" />
                                {char}
                                <button
                                  onClick={() => {
                                    const newChars = (shot.characters || []).filter((_: string, i: number) => i !== charIdx);
                                    updateShot(idx, 'characters', newChars);
                                  }}
                                  className="ml-1 hover:text-red-500"
                                >
                                  <X className="h-3 w-3" />
                                </button>
                              </span>
                            ))}
                          </div>
                          {/* 从当前章节角色列表选择 */}
                          <select
                            onChange={(e) => {
                              if (e.target.value && !(shot.characters || []).includes(e.target.value)) {
                                const newChars = [...(shot.characters || []), e.target.value];
                                updateShot(idx, 'characters', newChars);
                              }
                              e.target.value = '';
                            }}
                            className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs focus:ring-2 focus:ring-blue-500 focus:outline-none"
                            defaultValue=""
                          >
                            <option value="">{t('chapterGenerate.selectCharacterFromChapter')}</option>
                            {(data.characters || [])
                              .filter((c: string) => !(shot.characters || []).includes(c))
                              .map((char: string) => (
                                <option key={char} value={char}>{char}</option>
                              ))}
                          </select>
                        </div>

                        {/* 台词编辑区 */}
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <label className="block text-xs text-gray-500">{t('chapterGenerate.dialogues')}</label>
                            <button
                              onClick={() => addDialogue(idx)}
                              disabled={(shot.characters || []).length === 0}
                              className={`px-2 py-0.5 text-xs rounded flex items-center gap-1 ${
                                (shot.characters || []).length === 0
                                  ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                                  : 'bg-purple-50 text-purple-600 hover:bg-purple-100'
                              }`}
                              title={(shot.characters || []).length === 0 ? t('chapterGenerate.addDialogueDisabledHint') : t('chapterGenerate.addDialogue')}
                            >
                              <Plus className="h-3 w-3" />
                              {t('chapterGenerate.addDialogue')}
                            </button>
                          </div>

                          {/* 台词列表 */}
                          {(shot.dialogues || []).length > 0 && (
                            <div className="space-y-2 border border-gray-200 rounded-md p-2 bg-gray-50">
                              {(shot.dialogues || []).map((dialogue: DialogueData, dialogueIdx: number) => {
                                const audioUrl = getDialogueAudioUrl(idx, dialogue.character_name, dialogue);
                                const audioStatus = getDialogueAudioStatus(idx, dialogue.character_name);
                                const isAudioLoading = audioStatus === 'pending' || audioStatus === 'running';
                                const isAudioFailed = audioStatus === 'failed';
                                const audioKey = `${idx}_${dialogue.character_name}`;
                                const isThisPlaying = playingAudio === audioKey;

                                return (
                                  <div key={dialogueIdx} className="bg-white rounded p-2 border border-gray-100 space-y-1.5">
                                    <div className="flex items-center gap-2">
                                      {/* 角色选择 */}
                                      <select
                                        value={dialogue.character_name || ''}
                                        onChange={(e) => handleDialogueCharacterChange(idx, dialogueIdx, e.target.value)}
                                        className="flex-shrink-0 px-2 py-1 border border-gray-200 rounded text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none"
                                      >
                                        <option value="">{t('chapterGenerate.selectCharacter')}</option>
                                        {(shot.characters || []).map((char: string) => (
                                          <option key={char} value={char}>{char}</option>
                                        ))}
                                      </select>
                                      {/* 删除按钮 */}
                                      <button
                                        onClick={() => removeDialogue(idx, dialogueIdx)}
                                        className="p-1 text-red-400 hover:text-red-600 hover:bg-red-50 rounded"
                                        title={t('chapterGenerate.deleteDialogue')}
                                      >
                                        <Trash2 className="h-3 w-3" />
                                      </button>
                                    </div>
                                    {/* 台词文本 */}
                                    <textarea
                                      value={getDialogueLocalValue(idx, dialogueIdx, 'text', dialogue)}
                                      onChange={(e) => updateDialogue(idx, dialogueIdx, 'text', e.target.value)}
                                      placeholder={t('chapterGenerate.dialogueTextPlaceholder')}
                                      className="w-full px-2 py-1 border border-gray-200 rounded text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none resize-none"
                                      rows={2}
                                    />
                                    {/* 情感提示词 */}
                                    <div className="flex items-center gap-2">
                                      <span className="text-xs text-gray-400">{t('chapterGenerate.emotionPrompt')}</span>
                                      <input
                                        type="text"
                                        value={getDialogueLocalValue(idx, dialogueIdx, 'emotion_prompt', dialogue)}
                                        onChange={(e) => updateDialogue(idx, dialogueIdx, 'emotion_prompt', e.target.value)}
                                        placeholder={t('chapterGenerate.emotionPromptPlaceholder')}
                                        className="flex-1 px-2 py-1 border border-gray-200 rounded text-xs focus:ring-2 focus:ring-purple-500 focus:outline-none"
                                      />
                                    </div>
                                    {/* 音频状态和播放器 */}
                                    {dialogue.character_name && (
                                      <div className="flex flex-col gap-1.5 pt-1 border-t border-gray-100">
                                        {/* 音频状态 */}
                                        {isAudioLoading && (
                                          <div className="flex items-center gap-1 text-xs text-blue-500">
                                            <Loader2 className="h-3 w-3 animate-spin" />
                                            <span>{t('chapterGenerate.generatingAudio')}</span>
                                          </div>
                                        )}
                                        {isAudioFailed && (
                                          <div className="flex items-center gap-1 text-xs text-red-500">
                                            <AlertCircle className="h-3 w-3" />
                                            <span>{t('chapterGenerate.audioGenerateFailed')}</span>
                                            {onRegenerateAudio && (
                                              <button
                                                onClick={() => onRegenerateAudio(idx, dialogue.character_name, dialogue)}
                                                className="ml-1 text-blue-500 hover:underline"
                                              >
                                                {t('chapterGenerate.regenerateAudio')}
                                              </button>
                                            )}
                                          </div>
                                        )}
                                        {/* 无音频时显示生成和上传按钮 */}
                                        {!audioUrl && !isAudioLoading && !isAudioFailed && (
                                          <div className="flex items-center gap-2">
                                            {onGenerateDialogueAudio && (
                                              <button
                                                onClick={() => onGenerateDialogueAudio(idx, dialogue)}
                                                className="flex items-center gap-1 px-2 py-0.5 bg-green-50 hover:bg-green-100 text-green-600 rounded text-xs transition-colors"
                                                title={t('chapterGenerate.generateAudio')}
                                              >
                                                <Volume2 className="h-3 w-3" />
                                                {t('chapterGenerate.generateAudio')}
                                              </button>
                                            )}
                                            {onUploadDialogueAudio && (
                                              <label className="flex items-center gap-1 px-2 py-0.5 bg-blue-50 hover:bg-blue-100 text-blue-600 rounded text-xs transition-colors cursor-pointer">
                                                <Upload className="h-3 w-3" />
                                                {t('chapterGenerate.uploadAudio')}
                                                <input
                                                  type="file"
                                                  accept=".mp3,.wav,.flac"
                                                  className="hidden"
                                                  onChange={(e) => {
                                                    const file = e.target.files?.[0];
                                                    if (file) {
                                                      // 检查文件大小（10MB限制）
                                                      if (file.size > 10 * 1024 * 1024) {
                                                        alert(t('chapterGenerate.audioFileTooLarge'));
                                                        return;
                                                      }
                                                      onUploadDialogueAudio(idx, dialogue.character_name, file);
                                                    }
                                                    e.target.value = '';
                                                  }}
                                                />
                                              </label>
                                            )}
                                          </div>
                                        )}
                                        {/* 音频播放器和操作按钮 */}
                                        {audioUrl && !isAudioLoading && !isAudioFailed && (
                                          <div className="flex items-center gap-2 flex-wrap">
                                            {/* 音频来源标签 */}
                                            <span className={`px-1.5 py-0.5 rounded text-xs ${
                                              audioSources[audioKey] === 'uploaded'
                                                ? 'bg-blue-100 text-blue-600'
                                                : 'bg-purple-100 text-purple-600'
                                            }`}>
                                              {audioSources[audioKey] === 'uploaded'
                                                ? t('chapterGenerate.audioSourceUploaded')
                                                : t('chapterGenerate.audioSourceAi')}
                                            </span>
                                            {/* 播放按钮 */}
                                            <button
                                              onClick={() => toggleAudioPlay(idx, dialogue.character_name, audioUrl)}
                                              className="flex items-center gap-1 px-2 py-0.5 bg-green-100 hover:bg-green-200 text-green-700 rounded text-xs transition-colors"
                                            >
                                              {isThisPlaying ? (
                                                <>
                                                  <Square className="h-3 w-3" />
                                                  <span>{t('characters.stopAudio')}</span>
                                                </>
                                              ) : (
                                                <>
                                                  <Play className="h-3 w-3" />
                                                  <span>{t('chapterGenerate.playAudio')}</span>
                                                </>
                                              )}
                                            </button>
                                            {isThisPlaying && (
                                              <audio
                                                src={audioUrl}
                                                autoPlay
                                                onEnded={() => setPlayingAudio(null)}
                                                onError={() => setPlayingAudio(null)}
                                              />
                                            )}
                                            {/* 上传替换按钮 */}
                                            {onUploadDialogueAudio && (
                                              <label className="flex items-center gap-1 px-2 py-0.5 text-gray-500 hover:text-blue-600 cursor-pointer text-xs" title={t('chapterGenerate.uploadReplaceAudio')}>
                                                <Upload className="h-3 w-3" />
                                                <input
                                                  type="file"
                                                  accept=".mp3,.wav,.flac"
                                                  className="hidden"
                                                  onChange={(e) => {
                                                    const file = e.target.files?.[0];
                                                    if (file) {
                                                      if (file.size > 10 * 1024 * 1024) {
                                                        alert(t('chapterGenerate.audioFileTooLarge'));
                                                        return;
                                                      }
                                                      onUploadDialogueAudio(idx, dialogue.character_name, file);
                                                    }
                                                    e.target.value = '';
                                                  }}
                                                />
                                              </label>
                                            )}
                                            {/* 重新生成按钮（AI生成） */}
                                            {onRegenerateAudio && (
                                              <button
                                                onClick={() => onRegenerateAudio(idx, dialogue.character_name, dialogue)}
                                                className="flex items-center gap-1 px-2 py-0.5 text-gray-500 hover:text-gray-700 text-xs"
                                                title={t('chapterGenerate.regenerateAudio')}
                                              >
                                                <RefreshCw className="h-3 w-3" />
                                              </button>
                                            )}
                                            {/* 删除按钮 */}
                                            {onDeleteDialogueAudio && (
                                              <button
                                                onClick={() => {
                                                  if (confirm(t('chapterGenerate.confirmDeleteAudio'))) {
                                                    onDeleteDialogueAudio(idx, dialogue.character_name);
                                                  }
                                                }}
                                                className="flex items-center gap-1 px-2 py-0.5 text-gray-500 hover:text-red-600 text-xs"
                                                title={t('chapterGenerate.deleteAudio')}
                                              >
                                                <Trash2 className="h-3 w-3" />
                                              </button>
                                            )}
                                          </div>
                                        )}
                                        {/* 上传中状态 */}
                                        {isAudioUploading && isAudioUploading(idx, dialogue.character_name) && (
                                          <div className="flex items-center gap-1 text-xs text-blue-500">
                                            <Loader2 className="h-3 w-3 animate-spin" />
                                            <span>{t('chapterGenerate.uploadingAudio')}</span>
                                          </div>
                                        )}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          )}

                          {/* 无台词提示 */}
                          {(shot.dialogues || []).length === 0 && (
                            <p className="text-xs text-gray-400 italic">{t('chapterGenerate.noDialogues')}</p>
                          )}
                        </div>

                        {/* 道具选择器 - 从当前章节道具列表选择 */}
                        <div className="space-y-2">
                          <label className="block text-xs text-gray-500 mb-1">{t('chapterGenerate.props')}</label>
                          {/* 已选道具标签 */}
                          <div className="flex flex-wrap gap-1.5">
                            {(shot.props || []).map((prop: string, propIdx: number) => (
                              <span
                                key={propIdx}
                                className="inline-flex items-center gap-1 px-2 py-1 bg-amber-100 text-amber-700 rounded-full text-xs font-medium"
                              >
                                <Package className="h-3 w-3" />
                                {prop}
                                <button
                                  onClick={() => {
                                    const newProps = (shot.props || []).filter((_: string, i: number) => i !== propIdx);
                                    updateShot(idx, 'props', newProps);
                                  }}
                                  className="ml-1 hover:text-red-500"
                                >
                                  <X className="h-3 w-3" />
                                </button>
                              </span>
                            ))}
                          </div>
                          {/* 从章节道具列表选择 */}
                          <select
                            onChange={(e) => {
                              if (e.target.value && !(shot.props || []).includes(e.target.value)) {
                                const newProps = [...(shot.props || []), e.target.value];
                                updateShot(idx, 'props', newProps);
                              }
                              e.target.value = '';
                            }}
                            className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs focus:ring-2 focus:ring-amber-500 focus:outline-none"
                            defaultValue=""
                          >
                            <option value="">{t('chapterGenerate.selectPropFromChapter')}</option>
                            {(data.props || [])
                              .filter((p: string) => !(shot.props || []).includes(p))
                              .map((prop: string) => (
                                <option key={prop} value={prop}>{prop}</option>
                              ))}
                          </select>
                        </div>
                      </div>
                    </div>
                  );
                })()}
              </div>
            ) : (
              <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
                {t('chapterGenerate.noShotData')}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}