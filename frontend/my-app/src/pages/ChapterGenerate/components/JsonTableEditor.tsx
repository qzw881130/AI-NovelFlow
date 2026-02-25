import { useState, useEffect } from 'react';
import { 
  Users, 
  MapPin, 
  Plus, 
  Trash2, 
  X, 
  AlertCircle 
} from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';
import type { JsonTableEditorProps } from '../types';

export default function JsonTableEditor({ 
  value, 
  onChange, 
  availableScenes = [], 
  availableCharacters = [], 
  activeShotWorkflow 
}: JsonTableEditorProps) {
  const { t } = useTranslation();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string>('');
  const [activeSection, setActiveSection] = useState<'characters' | 'scenes' | 'shots'>('shots');
  // 存储角色输入的临时值（key: shotIndex, value: 输入字符串）
  const [characterInputs, setCharacterInputs] = useState<Record<number, string>>({});
  // 当前选中的分镜索引
  const [activeShotIndex, setActiveShotIndex] = useState<number>(0);
  
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
      id: (data.shots?.length || 0) + 1,
      description: t('chapterGenerate.newShotDesc'),
      video_description: '',
      characters: [],
      scene: '',
      duration: 4
    };
    updateJson({ ...data, shots: [...(data.shots || []), newShot] });
  };

  // 删除分镜
  const removeShot = (index: number) => {
    if (!data) return;
    const newShots = (data.shots || []).filter((_: any, i: number) => i !== index);
    // 重新编号
    newShots.forEach((shot: any, i: number) => { shot.id = i + 1; });
    updateJson({ ...data, shots: newShots });
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

        {activeSection === 'shots' && (
          <div className={`space-y-3 h-full flex flex-col ${hasInvalidScenes && activeShotWorkflow?.extension?.reference_image_count === 'dual' ? 'border-2 border-red-400 rounded-lg p-2' : ''}`}>
            {/* 场景验证错误提示 - 只有双图工作流时才显示 */}
            {hasInvalidScenes && activeShotWorkflow?.extension?.reference_image_count === 'dual' && (
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
                  const showInvalid = isInvalidScene && activeShotWorkflow?.extension?.reference_image_count === 'dual';
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
                      {t('chapterGenerate.shot')}{shot.id}
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
                        <span className="font-medium text-sm text-gray-700">{t('chapterGenerate.shotId', { id: shot.id, total: data.shots.length })}</span>
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
