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
import { useTranslation } from '../../../stores/i18nStore';
import { useChapterGenerateStore } from '../stores';
import type { DialogueData } from '../types';
import type { Shot } from '../../../api/shots';

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
}

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
}: ShotFormProps) {
  const { t } = useTranslation();
  const currentShotIndex = useChapterGenerateStore((state) => state.currentShotIndex);
  const storeShots = useChapterGenerateStore((state) => state.shots);
  const setShots = useChapterGenerateStore((state) => state.setShots);

  // 从 store 获取章节级资源
  const chapterCharacters = useChapterGenerateStore((state) => state.chapterCharacters);
  const chapterScenes = useChapterGenerateStore((state) => state.chapterScenes);
  const chapterProps = useChapterGenerateStore((state) => state.chapterProps);

  // 优先使用 props 中的 shotIndex 和 shotData，否则从 store 获取
  const shotIndex = propShotIndex || currentShotIndex;
  const shotData = propShotData || storeShots[shotIndex - 1];

  // 可用资源：优先使用 props，其次使用章节级资源
  const availableCharacters = propAvailableCharacters || chapterCharacters;
  const availableScenes = propAvailableScenes || chapterScenes;
  const availableProps = propAvailableProps || chapterProps;

  // 本地状态
  const [description, setDescription] = useState(shotData?.description || '');
  const [videoDescription, setVideoDescription] = useState(shotData?.video_description || '');
  const [selectedCharacters, setSelectedCharacters] = useState<string[]>(shotData?.characters || []);
  const [selectedScene, setSelectedScene] = useState(shotData?.scene || '');
  const [selectedProps, setSelectedProps] = useState<string[]>(shotData?.props || []);
  const [duration, setDuration] = useState(shotData?.duration || 5);
  const [dialogues, setDialogues] = useState<DialogueData[]>(shotData?.dialogues || []);

  // 当 shotIndex 或 shotData 变化时，同步本地状态
  useEffect(() => {
    if (shotData) {
      setDescription(shotData.description || '');
      setVideoDescription(shotData.video_description || '');
      setSelectedCharacters(shotData.characters || []);
      setSelectedScene(shotData.scene || '');
      setSelectedProps(shotData.props || []);
      setDuration(shotData.duration || 5);
      setDialogues(shotData.dialogues || []);
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
      duration,
      dialogues,
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
              duration,
              dialogues,
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
  }, [description, videoDescription, selectedCharacters, selectedScene, selectedProps, duration, dialogues]);

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

  // 台词编辑区域展开/收起状态
  const [dialoguesExpanded, setDialoguesExpanded] = useState(false);

  return (
    <div className="space-y-4">
      {/* 分镜描述 */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('chapterGenerate.shotDescForImage')}
        </label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          disabled={readOnly}
          rows={6}
          className="input-field"
          placeholder={t('chapterGenerate.shotDescPlaceholder')}
        />
        <div className="mt-2 flex items-center gap-2 text-xs text-gray-500 flex-wrap">
          <span>{t('chapterGenerate.placeholderHint')}</span>
          <span className="px-1.5 py-0.5 bg-gray-100 rounded">{t('chapterGenerate.placeholderStyle')}</span>
          <span className="px-1.5 py-0.5 bg-gray-100 rounded">{t('chapterGenerate.placeholderScene')}</span>
          <span className="px-1.5 py-0.5 bg-gray-100 rounded">{t('chapterGenerate.placeholderCharacters')}</span>
          <span className="px-1.5 py-0.5 bg-gray-100 rounded">{t('chapterGenerate.placeholderProps')}</span>
        </div>
      </div>

      {/* 视频描述 */}
      {showVideoDescription && (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            {t('chapterGenerate.videoDescForVideo')}
          </label>
          <textarea
            value={videoDescription}
            onChange={(e) => setVideoDescription(e.target.value)}
            disabled={readOnly}
            rows={6}
            className="input-field"
            placeholder={t('chapterGenerate.videoDescPlaceholder')}
          />
          <div className="mt-2 flex items-center gap-2 text-xs text-gray-500 flex-wrap">
            <span>{t('chapterGenerate.placeholderHint')}</span>
            <span className="px-1.5 py-0.5 bg-gray-100 rounded">{t('chapterGenerate.placeholderStyle')}</span>
            <span className="px-1.5 py-0.5 bg-gray-100 rounded">{t('chapterGenerate.placeholderScene')}</span>
            <span className="px-1.5 py-0.5 bg-gray-100 rounded">{t('chapterGenerate.placeholderCharacters')}</span>
            <span className="px-1.5 py-0.5 bg-gray-100 rounded">{t('chapterGenerate.placeholderProps')}</span>
          </div>
        </div>
      )}

      {/* 角色选择 */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('chapterGenerate.appearingCharacters')}
        </label>
        {selectedCharacters.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
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
          </div>
        )}
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
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('chapterGenerate.scene')}
        </label>
        {selectedScene && (
          <div className="mb-2">
            <span className="inline-flex items-center px-2 py-1 bg-green-100 text-green-700 rounded text-xs">
              {selectedScene}
              <button
                onClick={() => setSelectedScene('')}
                className="ml-1 hover:text-green-900"
              >
                ×
              </button>
            </span>
          </div>
        )}
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
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('chapterGenerate.props')}
        </label>
        {selectedProps.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
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
          </div>
        )}
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
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            {t('chapterGenerate.durationLabel')}
          </label>
          <input
            type="number"
            value={duration}
            onChange={(e) => setDuration(Math.min(60, Math.max(1, parseInt(e.target.value) || 5)))}
            disabled={readOnly}
            min={1}
            max={60}
            className="input-field"
          />
          <p className="text-xs text-gray-500 mt-1">{t('common.recommended')} 3-10 {t('common.second')}，{t('common.max')} 60 {t('common.second')}</p>
        </div>
      )}

      {/* 角色台词 */}
      {showDialogues && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium text-gray-700">{t('chapterGenerate.dialogues')}</label>
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
                    <span className="text-xs font-medium text-gray-500">{t('chapterGenerate.dialogues')} {idx + 1}</span>
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
  );
}

export default ShotForm;